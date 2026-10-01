from latch.diff_parser import DiffParser, AddedLine


SAMPLE_DIFF = """diff --git a/src/user.py b/src/user.py
index 1234567..89abcdef 100644
--- a/src/user.py
+++ b/src/user.py
@@ -10,6 +10,8 @@ def existing_fn():
     pass
 
+def new_fn():
+    phone = "+1-555-0199"
-    old_call()
     return True
diff --git a/docs/notes.txt b/docs/notes.txt
index 0000000..1111111 100644
--- a/docs/notes.txt
+++ b/docs/notes.txt
@@ -0,0 +1,2 @@
+Line one of notes
+Line two of notes
"""

SAMPLE_DELETIONS_ONLY = """diff --git a/src/clean.py b/src/clean.py
index 1234567..89abcdef 100644
--- a/src/clean.py
+++ b/src/clean.py
@@ -10,3 +10,1 @@ def fn():
-    deprecated_one()
-    deprecated_two()
     return True
"""

SAMPLE_BINARY_DIFF = """diff --git a/assets/logo.png b/assets/logo.png
new file mode 100644
index 0000000..1234567
Binary files /dev/null and b/assets/logo.png differ
"""


def test_parse_raw_diff():
    parser = DiffParser()
    added_lines = parser.parse_diff_text(SAMPLE_DIFF)
    
    # Should only extract additions, not deletions or unchanged lines
    assert len(added_lines) == 4
    
    assert added_lines[0].file_path == "src/user.py"
    assert added_lines[0].line_number == 12
    assert added_lines[0].content == "def new_fn():"

    assert added_lines[1].file_path == "src/user.py"
    assert added_lines[1].line_number == 13
    assert added_lines[1].content == '    phone = "+1-555-0199"'

    assert added_lines[2].file_path == "docs/notes.txt"
    assert added_lines[2].line_number == 1
    assert added_lines[2].content == "Line one of notes"


def test_parse_deletions_only():
    parser = DiffParser()
    added_lines = parser.parse_diff_text(SAMPLE_DELETIONS_ONLY)
    assert len(added_lines) == 0


def test_parse_binary_diff():
    parser = DiffParser()
    added_lines = parser.parse_diff_text(SAMPLE_BINARY_DIFF)
    assert len(added_lines) == 0


def test_pack_batches():
    parser = DiffParser(max_chunk_tokens=50)
    added_lines = parser.parse_diff_text(SAMPLE_DIFF)
    batches = parser.pack_into_batches(added_lines)
    
    assert len(batches) >= 1
    formatted = batches[0].formatted_text()
    assert "=== File: src/user.py ===" in formatted
    assert 'phone = "+1-555-0199"' in formatted


def test_diff_parser_respects_allowlist():
    parser = DiffParser(allowlist_paths=["docs/*", "impressum.tsx"])
    added_lines = parser.parse_diff_text(SAMPLE_DIFF)
    
    # docs/notes.txt is allowlisted, so only src/user.py lines remain
    files = {l.file_path for l in added_lines}
    assert "docs/notes.txt" not in files
    assert "src/user.py" in files
    assert len(added_lines) == 2


def test_diff_parser_rejects_over_permissive_near_miss_allowlist():
    diff_text = (
        "diff --git a/myapp/config/secret.env b/myapp/config/secret.env\n"
        "--- a/myapp/config/secret.env\n"
        "+++ b/myapp/config/secret.env\n"
        "@@ -0,0 +1,1 @@\n"
        "+SECRET_KEY=123\n"
        "diff --git a/app/config/secret.env b/app/config/secret.env\n"
        "--- a/app/config/secret.env\n"
        "+++ b/app/config/secret.env\n"
        "@@ -0,0 +1,1 @@\n"
        "+EXEMPTED_KEY=456\n"
    )
    parser = DiffParser(allowlist_paths=["app/config"])
    added_lines = parser.parse_diff_text(diff_text)
    files = {l.file_path for l in added_lines}
    # myapp/config/secret.env must NOT be exempted (R7-2)
    assert "myapp/config/secret.env" in files
    # app/config/secret.env IS exempted
    assert "app/config/secret.env" not in files


def test_diff_parser_respects_latch_ignore_pragma():
    diff_with_pragma = """diff --git a/src/impressum.tsx b/src/impressum.tsx
index 123..456 100644
--- a/src/impressum.tsx
+++ b/src/impressum.tsx
@@ -1,3 +1,5 @@
+export const SupportEmail = "contact@example.com"; // latch:ignore
+export const SecretKey = "sk_live_99999";
"""
    parser = DiffParser()
    added_lines = parser.parse_diff_text(diff_with_pragma)
    
    # The line with latch:ignore must be excluded
    contents = [l.content for l in added_lines]
    assert not any("contact@example.com" in c for c in contents)
    assert any("sk_live_99999" in c for c in contents)


def test_diff_parser_splits_oversized_single_line():
    huge_line = "a" * 8000
    oversized_diff = f"""diff --git a/bundle.min.js b/bundle.min.js
index 123..456 100644
--- a/bundle.min.js
+++ b/bundle.min.js
@@ -1,1 +1,1 @@
+{huge_line}
"""
    parser = DiffParser(max_chunk_tokens=500)
    added_lines = parser.parse_diff_text(oversized_diff)
    
    # Oversized 8,000 char line must be split into chunks
    assert len(added_lines) > 1
    for line in added_lines:
        assert len(line.content) <= (500 - 10) * 4


def test_diff_parser_does_not_leak_nested_files_with_wildcard():
    """Verify *.md only matches top-level markdown, not arbitrary nested directories (N3)."""
    nested_diff = (
        "diff --git a/docs/sub/notes.md b/docs/sub/notes.md\n"
        "--- a/docs/sub/notes.md\n"
        "+++ b/docs/sub/notes.md\n"
        "@@ -0,0 +1,1 @@\n"
        "+AWS_SECRET=AKIAIOSFODNN7EXAMPLE\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -0,0 +1,1 @@\n"
        "+# Clean Readme\n"
    )
    parser = DiffParser(allowlist_paths=["*.md"])
    added_lines = parser.parse_diff_text(nested_diff)
    files = {l.file_path for l in added_lines}

    # docs/sub/notes.md must NOT be allowlisted by *.md
    assert "docs/sub/notes.md" in files
    # README.md is top-level and is allowlisted
    assert "README.md" not in files


def test_diff_parser_tracks_exemption_stats():
    """Verify ParserStats counts both allowlisted lines and pragma-ignored lines (N4)."""
    diff_text = (
        "diff --git a/fixtures/test.py b/fixtures/test.py\n"
        "--- a/fixtures/test.py\n"
        "+++ b/fixtures/test.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+secret_1 = 'val'\n"
        "+secret_2 = 'val'\n"
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+normal_code = True\n"
        "+ignored_code = 'sk_test_123' # latch:ignore\n"
    )
    parser = DiffParser(allowlist_paths=["fixtures/*"])
    added_lines = parser.parse_diff_text(diff_text)

    assert len(added_lines) == 1
    assert added_lines[0].content == "normal_code = True"
    assert parser.last_stats.exempted_allowlist_files == 1
    assert parser.last_stats.exempted_allowlist_lines == 2
    assert parser.last_stats.exempted_pragma_lines == 1
    assert parser.last_stats.total_exempted == 3


def test_pack_into_batches_chunks_oversized_single_line():
    """A giant single line (e.g. 50,000 chars minified JS/JSON) must be chunked so no batch overflows."""
    parser = DiffParser(max_chunk_tokens=750)
    giant_content = "var a = 1; " * 5000  # ~55,000 characters
    line = AddedLine(file_path="src/bundle.js", line_number=1, content=giant_content)

    batches = parser.pack_into_batches([line])
    assert len(batches) > 1
    for b in batches:
        # Every batch must strictly respect the token bound
        assert b.estimated_tokens <= 750
        assert all(l.file_path == "src/bundle.js" for l in b.lines)


