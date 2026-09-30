import pytest
from latch.diff_parser import DiffParser, AddedLine, DiffBatch


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

