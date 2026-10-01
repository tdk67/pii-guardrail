from pathlib import Path
from latch.gitignore import GitignoreParser, _pattern_to_regex


def test_pattern_to_regex_basic():
    is_neg, dir_only, pattern_re = _pattern_to_regex("*.pyc")
    assert not is_neg
    assert not dir_only
    assert pattern_re.search("foo.pyc")
    assert pattern_re.search("nested/bar.pyc")
    assert not pattern_re.search("foo.py")


def test_pattern_to_regex_dir_only():
    is_neg, dir_only, pattern_re = _pattern_to_regex("CoverLetters/")
    assert not is_neg
    assert dir_only
    assert pattern_re.search("CoverLetters")
    assert pattern_re.search("nested/CoverLetters")


def test_pattern_to_regex_anchored():
    is_neg, dir_only, pattern_re = _pattern_to_regex("/build")
    assert not is_neg
    assert pattern_re.search("build")
    assert pattern_re.search("build/output.js")
    assert not pattern_re.search("src/build")


def test_pattern_to_regex_negation():
    is_neg, dir_only, pattern_re = _pattern_to_regex("!important.txt")
    assert is_neg
    assert not dir_only
    assert pattern_re.search("important.txt")


def test_gitignore_parser_filters_files_and_directories(tmp_path: Path):
    gitignore_file = tmp_path / ".gitignore"
    gitignore_file.write_text(
        "CoverLetters/\n"
        "*.local.json\n"
        "reports/*.pdf\n"
        "!reports/keep.pdf\n",
        encoding="utf-8",
    )

    parser = GitignoreParser.from_directory(tmp_path)
    assert len(parser.rules) == 4

    # Directory match
    assert parser.is_ignored(tmp_path / "CoverLetters", is_dir=True) is True
    assert parser.is_ignored(tmp_path / "CoverLetters" / "letter.html", is_dir=False) is True

    # File wildcard match
    assert parser.is_ignored(tmp_path / "config.local.json", is_dir=False) is True
    assert parser.is_ignored(tmp_path / "sub" / "secret.local.json", is_dir=False) is True
    assert parser.is_ignored(tmp_path / "config.json", is_dir=False) is False

    # Path pattern match and negation
    assert parser.is_ignored(tmp_path / "reports" / "summary.pdf", is_dir=False) is True
    assert parser.is_ignored(tmp_path / "reports" / "keep.pdf", is_dir=False) is False


def test_gitignore_parser_nested_discovery(tmp_path: Path):
    sub = tmp_path / "subproject"
    sub.mkdir()
    (sub / ".gitignore").write_text("sub_ignored/\n", encoding="utf-8")

    parser = GitignoreParser(root_dir=tmp_path)
    parser.add_file(sub / ".gitignore", base_dir=sub)

    assert parser.is_ignored(sub / "sub_ignored", is_dir=True) is True
    assert parser.is_ignored(sub / "sub_ignored" / "file.txt", is_dir=False) is True
    assert parser.is_ignored(tmp_path / "other" / "sub_ignored", is_dir=True) is False
