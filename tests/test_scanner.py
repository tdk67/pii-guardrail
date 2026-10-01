from pathlib import Path
from unittest.mock import MagicMock
from latch.config import LatchConfig
from latch.dissection import DissectionResult
from latch.engine import EvaluationResult
from latch.scanner import DEFAULT_IGNORED_DIRS, ScanReport, Scanner, is_binary_file
from latch.cli import run_scan


def test_is_binary_file(tmp_path: Path):
    text_file = tmp_path / "clean.py"
    text_file.write_text("print('hello')", encoding="utf-8")
    assert is_binary_file(text_file) is False

    bin_file = tmp_path / "binary.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03binary")
    assert is_binary_file(bin_file) is True


def test_collect_source_files_filters_ignored_dirs(tmp_path: Path):
    # Setup test tree
    (tmp_path / ".git").mkdir()  # latch:ignore
    (tmp_path / ".git" / "config").write_text("git config", encoding="utf-8")  # latch:ignore
    (tmp_path / ".venv").mkdir()  # latch:ignore
    (tmp_path / ".venv" / "lib.py").write_text("venv code", encoding="utf-8")  # latch:ignore
    (tmp_path / "node_modules").mkdir()  # latch:ignore
    (tmp_path / "node_modules" / "pkg.js").write_text("module", encoding="utf-8")  # latch:ignore

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("def main(): pass", encoding="utf-8")
    (src_dir / "util.ts").write_text("export const x = 1;", encoding="utf-8")
    (src_dir / "image.png").write_bytes(b"\x00\x00PNG")

    scanner = Scanner(config=LatchConfig())
    matched, allowlisted = scanner.collect_source_files(
        target_dir=tmp_path,
        extensions={".py", ".ts"},
        ignored_dirs=set(DEFAULT_IGNORED_DIRS),
    )

    filenames = [p.name for p in matched]
    assert "app.py" in filenames
    assert "util.ts" in filenames
    assert "config" not in filenames
    assert "lib.py" not in filenames
    assert "pkg.js" not in filenames
    assert "image.png" not in filenames
    assert allowlisted == 0


def test_collect_source_files_ignores_lockfiles_and_minified(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "index.js").write_text("console.log('hi');", encoding="utf-8")
    (src_dir / "bundle.min.js").write_text("console.log('min');", encoding="utf-8")
    (src_dir / "style.min.css").write_text("body{margin:0}", encoding="utf-8")
    (src_dir / "package-lock.json").write_text('{"name": "test"}', encoding="utf-8")
    (src_dir / "yarn.lock").write_text("# yarn lock", encoding="utf-8")

    scanner = Scanner(config=LatchConfig())
    matched, _ = scanner.collect_source_files(
        target_dir=tmp_path,
        extensions={".js", ".css", ".json"},
        ignored_dirs=set(DEFAULT_IGNORED_DIRS),
    )

    names = [p.name for p in matched]
    assert "index.js" in names
    assert "bundle.min.js" not in names
    assert "style.min.css" not in names
    assert "package-lock.json" not in names
    assert "yarn.lock" not in names


def test_scanner_handles_giant_single_line_without_overflow(tmp_path: Path):
    # Giant 50,000 char line file (e.g. minified json or bundled code)
    giant_file = tmp_path / "big_data.json"
    giant_file.write_text('{"data": "' + ("A" * 50000) + '"}', encoding="utf-8")

    received_batches = []
    mock_client = MagicMock()

    def mock_eval(prompt, request_id=""):
        received_batches.append(prompt)
        return EvaluationResult(probability=0.01, latency_ms=5)

    mock_client.evaluate.side_effect = mock_eval
    mock_client.last_mode = "in_process"

    scanner = Scanner(config=LatchConfig(max_chunk_tokens=750), client=mock_client)
    report = scanner.scan(target_dir=str(tmp_path), extensions=[".json"])

    assert report.is_clean is True
    assert report.total_chunks > 1
    # Check that each evaluated prompt never exceeds the model context window
    for prompt in received_batches:
        assert len(prompt) < 15000  # Well within safe context budget (< 8192 tokens)


def test_scanner_clean_directory(tmp_path: Path):
    (tmp_path / "main.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"env": "prod"}', encoding="utf-8")

    mock_client = MagicMock()
    mock_client.evaluate.return_value = EvaluationResult(probability=0.05, latency_ms=10)
    mock_client.last_mode = "daemon"

    scanner = Scanner(config=LatchConfig(pii_threshold=0.65), client=mock_client)
    report = scanner.scan(target_dir=str(tmp_path), extensions=[".py", ".json"])

    assert report.is_clean is True
    assert report.total_files == 2
    assert report.total_chunks >= 1
    assert len(report.leaks) == 0
    assert report.mode == "daemon"


def test_scanner_detects_and_dissects_leak(tmp_path: Path):  # latch:ignore
    target_file = tmp_path / "sample.py"
    target_file.write_text("API_SECRET = 'super_secret_token_12345'\n", encoding="utf-8")  # latch:ignore

    mock_client = MagicMock()
    mock_client.evaluate.return_value = EvaluationResult(probability=0.95, latency_ms=15)
    mock_client.last_mode = "daemon"

    mock_dissector = MagicMock()
    mock_dissector.dissect.return_value = DissectionResult(
        offending_file="sample.py",
        start_line=1,
        end_line=1,
        snippet=" 1 | API_SECRET = 'super_secret_token_12345'",  # latch:ignore
        probability=0.95,  # latch:ignore
    )

    scanner = Scanner(
        config=LatchConfig(pii_threshold=0.65),
        client=mock_client,
        dissector=mock_dissector,
    )
    report = scanner.scan(target_dir=str(tmp_path), extensions=[".py"])

    assert report.is_clean is False  # latch:ignore
    assert len(report.leaks) == 1  # latch:ignore
    assert report.leaks[0].offending_file == "sample.py"  # latch:ignore
    assert report.leaks[0].start_line == 1


def test_scanner_respects_latch_ignore_pragma(tmp_path: Path):
    doc = tmp_path / "public.py"
    doc.write_text(
        "CONTACT_PHONE = '+1-555-0100'  # latch:ignore\n"
        "CLEAN_LINE = True\n",
        encoding="utf-8",
    )

    mock_client = MagicMock()
    mock_client.evaluate.return_value = EvaluationResult(probability=0.01, latency_ms=5)

    scanner = Scanner(config=LatchConfig(), client=mock_client)
    report = scanner.scan(target_dir=str(tmp_path), extensions=[".py"])

    assert report.is_clean is True
    assert report.exempted_pragma_lines == 1


def test_run_scan_cli_exit_codes(tmp_path: Path):
    clean_file = tmp_path / "clean.py"
    clean_file.write_text("x = 10\n", encoding="utf-8")

    mock_scanner = MagicMock()
    mock_scanner.scan.return_value = ScanReport(
        target_dir=str(tmp_path),
        total_files=1,
        total_lines=1,
        total_chunks=1,
        leaks=[],
        total_latency_ms=15,
        mode="daemon",
    )

    exit_code_clean = run_scan(path=str(tmp_path), scanner=mock_scanner)
    assert exit_code_clean == 0

    # Non-clean case  # latch:ignore
    mock_scanner.scan.return_value = ScanReport(
        target_dir=str(tmp_path),
        total_files=1,
        total_lines=1,
        total_chunks=1,
        leaks=[  # latch:ignore
            DissectionResult(
                offending_file="clean.py",
                start_line=1,
                end_line=1,
                snippet="1 | x = 10",
                probability=0.88,  # latch:ignore
            )
        ],
        total_latency_ms=25,
        mode="daemon",
    )

    exit_code_leak = run_scan(path=str(tmp_path), scanner=mock_scanner)  # latch:ignore
    assert exit_code_leak == 1  # latch:ignore


def test_scan_report_save_and_markdown(tmp_path: Path):
    report = ScanReport(
        target_dir=str(tmp_path),
        total_files=5,
        total_lines=120,
        total_chunks=3,
        leaks=[  # latch:ignore
            DissectionResult(
                offending_file="tests/fixtures/data.json",
                start_line=10,
                end_line=12,
                snippet=" 10 | 'token': 'abc_secret_123'",  # latch:ignore
                probability=0.99,  # latch:ignore
            )
        ],
        total_latency_ms=150,
        mode="daemon",
        threshold=0.65,
    )

    md_path, json_path = report.save_reports(str(tmp_path / "custom_report.md"))
    assert md_path.exists()
    assert json_path.exists()

    md_content = md_path.read_text(encoding="utf-8")
    assert "Latch Codebase Scan Report" in md_content
    assert "tests/fixtures/data.json" in md_content
    assert "0.99" in md_content
    # Raw secret must NOT be persisted in markdown
    assert "abc_secret_123" not in md_content
    assert "…" in md_content
    # Code structure and line number must be preserved
    assert " 10 | 'token': 'abc" in md_content
    # Template placeholders must be completely resolved
    assert "{total_lines" not in md_content
    assert "{total_latency" not in md_content
    assert "{latency_sec" not in md_content
    assert "120" in md_content

    import json
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["is_clean"] is False
    assert data["leaks_count"] == 1
    assert "tests/fixtures/*" in data["suggested_allowlists"]
    # Raw secret must NOT be persisted in json
    persisted_snippet = data["findings"][0]["snippet"]
    assert "abc_secret_123" not in persisted_snippet
    assert "…" in persisted_snippet
    assert " 10 | 'token': 'abc" in persisted_snippet


def test_redact_snippet_preserves_multiline_code_structure():  # latch:ignore
    from latch.scanner import redact_snippet  # latch:ignore

    multiline = (  # latch:ignore
        "  58 | def create_server():\n"  # latch:ignore
        "  59 |     api_key = 'sk_live_1234567890abcdef'\n"  # latch:ignore
        "  60 |     token: raw_secret_token_123456789\n"  # latch:ignore
        "  61 |     return app\n"  # latch:ignore
        "     ... (46 more lines in parent window)"  # latch:ignore
    )  # latch:ignore
    res = redact_snippet(multiline)  # latch:ignore
    lines = res.splitlines()  # latch:ignore
    assert len(lines) == 5  # latch:ignore
    assert lines[0] == "  58 | def create_server():"  # latch:ignore
    assert "sk_live_1234567890abcdef" not in lines[1]  # latch:ignore
    assert "…" in lines[1]  # latch:ignore
    assert lines[1].startswith("  59 |     api_key = 'sk_")  # latch:ignore
    assert "raw_secret_token_123456789" not in lines[2]  # latch:ignore
    assert "…" in lines[2]  # latch:ignore
    assert lines[3] == "  61 |     return app"  # latch:ignore
    assert lines[4] == "     ... (46 more lines in parent window)"  # latch:ignore


def test_scan_report_whitelist_suggestions():
    report = ScanReport(
        target_dir=".",
        total_files=10,
        total_lines=1000,
        total_chunks=10,
        leaks=[  # latch:ignore
            DissectionResult(
                offending_file="tests/fixtures/lupusalpha/form.html",
                start_line=2019,
                end_line=2019,
                snippet="<option>test</option>",
                probability=1.0,  # latch:ignore
            ),
            DissectionResult(
                offending_file="tests/mocks/mock_auth.py",
                start_line=15,
                end_line=15,
                snippet="password = 'test'",
                probability=0.85,  # latch:ignore
            ),
        ],
    )

    suggestions = report.get_suggested_allowlists()
    assert any("fixtures" in s for s in suggestions)
    assert any("mocks" in s for s in suggestions)


def test_suggested_allowlist_does_not_over_exempt():
    report = ScanReport(
        target_dir=".",
        total_files=1,
        total_lines=10,
        total_chunks=1,
        leaks=[
            DissectionResult(
                offending_file="tests/fixtures/secret.py",
                start_line=1,
                end_line=1,
                snippet="key = '123'",
                probability=0.9,
            )
        ],
    )
    suggestions = report.get_suggested_allowlists()
    assert suggestions
    from latch.allowlist import is_path_allowlisted
    # Matches the exact leak file
    assert is_path_allowlisted("tests/fixtures/secret.py", suggestions) is True
    # Does NOT match sibling paths like <parent>/.git/secret or other directories
    assert is_path_allowlisted("tests/.git/secret", suggestions) is False
    assert is_path_allowlisted("tests/other/secret.py", suggestions) is False


def test_scan_report_to_markdown_handles_literal_braces():
    report = ScanReport(
        target_dir=".",
        total_files=1,
        total_lines=5,
        total_chunks=1,
        leaks=[
            DissectionResult(
                offending_file="src/code.py",
                start_line=1,
                end_line=1,
                snippet='{"user": "{name}", "token": "secret_val"}',
                probability=0.95,
            )
        ],
    )
    md = report.to_markdown()
    assert "src/code.py" in md


def test_scanner_allowlist_patterns():
    scanner = Scanner(
        config=LatchConfig(),
        allowlist_paths=["fixtures/*", "**/mock/**", "secret_template.py"],
    )

    # Directly under fixtures
    assert scanner._is_path_allowlisted("fixtures/sample.py") is True
    # In nested directory under fixtures
    assert scanner._is_path_allowlisted("tests/fixtures/lupusalpha/form.html") is True
    # Mock pattern
    assert scanner._is_path_allowlisted("src/mock/service.py") is True
    # Exact filename match
    assert scanner._is_path_allowlisted("dir/secret_template.py") is True
    # Non-allowlisted file
    assert scanner._is_path_allowlisted("src/main.py") is False

    # Negative cases (R7-2: segment-anchored, no substring matches)
    scanner_adv = Scanner(
        config=LatchConfig(),
        allowlist_paths=["src/*", "app/config", "fixtures", "**/bar/**"],
    )
    assert scanner_adv._is_path_allowlisted("notsrc/x.py") is False
    assert scanner_adv._is_path_allowlisted("esrc/secret.py") is False
    assert scanner_adv._is_path_allowlisted("myapp/config/secret.env") is False
    assert scanner_adv._is_path_allowlisted("app/configx/y.py") is False
    assert scanner_adv._is_path_allowlisted("webapp/config/z.py") is False

    # Positive cases
    assert scanner_adv._is_path_allowlisted("src/x.py") is True
    assert scanner_adv._is_path_allowlisted("app/config/secret.env") is True
    assert scanner_adv._is_path_allowlisted("fixtures/foo") is True
    assert scanner_adv._is_path_allowlisted("foo/bar/baz") is True


def test_scanner_respects_gitignore(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("CoverLetters/\n*.local.json\n", encoding="utf-8")
    (tmp_path / "CoverLetters").mkdir()
    (tmp_path / "CoverLetters" / "letter.html").write_text("<html>Personal Data</html>", encoding="utf-8")  # latch:ignore
    (tmp_path / "config.local.json").write_text('{"secret": "val"}', encoding="utf-8")  # latch:ignore
    (tmp_path / "app.py").write_text("print('hello')", encoding="utf-8")

    scanner = Scanner(config=LatchConfig())
    matched, allowlisted, gitignored = scanner.collect_source_files(
        target_dir=tmp_path,
        extensions={".py", ".html", ".json"},
        ignored_dirs=set(DEFAULT_IGNORED_DIRS),
        use_gitignore=True,
        return_details=True,
    )

    names = [p.name for p in matched]
    assert "app.py" in names
    assert "letter.html" not in names
    assert "config.local.json" not in names
    assert gitignored >= 2


def test_scanner_custom_ignored_dirs_in_config(tmp_path: Path):
    cfg = LatchConfig(ignored_dirs=["CustomDir", "CoverLetters"])
    scanner = Scanner(config=cfg, ignored_dirs=["ExtraDir"])

    assert "CustomDir" in scanner.ignored_dirs
    assert "CoverLetters" in scanner.ignored_dirs
    assert "ExtraDir" in scanner.ignored_dirs


def test_scan_report_markdown_displays_ignored_dirs_and_gitignore():
    report = ScanReport(
        target_dir="/test/repo",
        total_files=10,
        total_lines=500,
        total_chunks=5,
        exempted_gitignore_files=7,
        ignored_dirs=["CoverLetters", "fixtures"],
    )
    md = report.to_markdown()
    assert "| **Gitignore File Exemptions** | 7 |" in md
    assert "`CoverLetters`, `fixtures`" in md


