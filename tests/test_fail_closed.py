from unittest.mock import MagicMock
from latch.cli import run_check
from latch.config import LatchConfig
from latch.diff_parser import AddedLine, DiffBatch, DiffParser, DiffParserError
from latch.engine import EvaluationResult, JuliaEngine, JuliaEngineError


def test_run_check_fails_closed_when_weights_missing(capsys):
    """When model weights are missing or corrupt, check must exit 1 and show error banner."""
    cfg = LatchConfig(model_path="/nonexistent/models/julia-1")
    
    mock_parser = MagicMock(spec=DiffParser)
    mock_parser.get_staged_added_lines.return_value = [
        AddedLine(file_path="auth.py", line_number=1, content="api_key = 123")
    ]
    mock_parser.pack_into_batches.return_value = [
        DiffBatch(batch_id="b1", lines=[
            AddedLine(file_path="auth.py", line_number=1, content="api_key = 123")
        ], estimated_tokens=10)
    ]

    mock_engine = MagicMock(spec=JuliaEngine)
    mock_engine.evaluate.side_effect = JuliaEngineError("Model weights not found at /nonexistent/models/julia-1")

    exit_code = run_check(config=cfg, parser=mock_parser, engine=mock_engine)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Julia-1 Engine Failure" in captured.err
    assert "download-model" in captured.err


def test_run_check_fails_closed_when_diff_parser_errors(capsys):
    """When git diff fails, check must exit 1 and show error banner."""
    mock_parser = MagicMock(spec=DiffParser)
    mock_parser.get_staged_added_lines.side_effect = DiffParserError("git diff command failed")

    exit_code = run_check(parser=mock_parser)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Git Environment Error" in captured.err


def test_run_check_fails_closed_when_daemon_returns_eval_error(capsys):
    """When evaluation returns an unhandled error, check must exit 1."""
    cfg = LatchConfig()
    mock_parser = MagicMock(spec=DiffParser)
    mock_parser.get_staged_added_lines.return_value = [
        AddedLine(file_path="data.py", line_number=1, content="token = 'xyz'")
    ]
    mock_parser.pack_into_batches.return_value = [
        DiffBatch(batch_id="b1", lines=[
            AddedLine(file_path="data.py", line_number=1, content="token = 'xyz'")
        ], estimated_tokens=10)
    ]

    mock_engine = MagicMock(spec=JuliaEngine)
    # Return probability 1.0 with an error string (fail-closed)
    mock_engine.evaluate.return_value = EvaluationResult(
        probability=1.0, latency_ms=0, error="Out of memory in tensor forward pass"
    )

    exit_code = run_check(config=cfg, parser=mock_parser, engine=mock_engine)
    assert exit_code == 1


def test_scanner_fails_closed_when_client_returns_error(tmp_path):
    """When client returns an evaluation error during scan, report must not be clean."""
    from latch.scanner import Scanner
    from latch.client import Client

    test_file = tmp_path / "test.py"
    test_file.write_text("x = 1\n", encoding="utf-8")

    mock_client = MagicMock(spec=Client)
    mock_client.evaluate.return_value = EvaluationResult(
        probability=0.0,
        latency_ms=5,
        error="Daemon crashed or socket timeout",
    )
    mock_client.last_mode = "daemon"

    scanner = Scanner(client=mock_client)
    report = scanner.scan(target_dir=str(tmp_path))

    assert report.errored_chunks == 1
    assert report.is_clean is False
    assert report.to_dict()["status"] == "ERROR"


def test_cli_run_scan_fails_closed_on_errored_chunks(tmp_path, capsys):
    """When chunks fail during scan, CLI must report fail-closed and exit 1."""
    from latch.cli import run_scan
    from latch.scanner import Scanner
    from latch.client import Client

    test_file = tmp_path / "code.py"
    test_file.write_text("a = 1\n", encoding="utf-8")

    mock_client = MagicMock(spec=Client)
    mock_client.is_daemon_alive.return_value = False
    mock_client.evaluate.return_value = EvaluationResult(
        probability=0.0,
        latency_ms=5,
        error="Model evaluation failed",
    )
    mock_client.last_mode = "in_process"

    scanner = Scanner(client=mock_client)
    exit_code = run_scan(path=str(tmp_path), scanner=scanner)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "FAIL-CLOSED" in captured.err
