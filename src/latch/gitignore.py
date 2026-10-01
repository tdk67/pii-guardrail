"""Zero-dependency .gitignore parser and path filter.

Implements standard Git ignore pattern matching rules (wildcards, directory-only
patterns, anchored paths, comments, and negations) to ensure uncommitted or
git-ignored artifacts (e.g. local build outputs, documents, virtual environments)
are not scanned by Latch.
"""

from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class GitignoreRule:
    """Represents a single parsed .gitignore pattern."""
    raw_pattern: str
    is_negated: bool
    dir_only: bool
    pattern_re: re.Pattern[str]
    base_dir: str


def _pattern_to_regex(pattern: str) -> Tuple[bool, bool, re.Pattern[str]]:
    """Converts a gitignore glob pattern to a compiled regex."""
    is_negated = pattern.startswith("!")
    if is_negated:
        pattern = pattern[1:]

    dir_only = pattern.endswith("/")
    if dir_only:
        pattern = pattern[:-1]

    # Trailing escaped spaces or trailing backslashes
    pattern = pattern.rstrip()

    anchored = False
    if pattern.startswith("/"):
        anchored = True
        pattern = pattern[1:]
    elif "/" in pattern:
        anchored = True

    # Translate glob tokens into regular expression
    res: List[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    res.append("(?:.*/)?")
                    i += 3
                    continue
                else:
                    res.append(".*")
                    i += 2
                    continue
            else:
                res.append("[^/]*")
                i += 1
                continue
        elif c == "?":
            res.append("[^/]")
        elif c in ".+^$()[]{}|\\":
            res.append("\\" + c)
        else:
            res.append(c)
        i += 1

    regex_str = "".join(res)
    # Case-insensitive matching on Windows, standard on Linux
    flags = re.IGNORECASE if os.name == "nt" else 0
    if anchored:
        pattern_re = re.compile(f"^{regex_str}(?:/.*)?$", flags)
    else:
        pattern_re = re.compile(f"(?:^|/){regex_str}(?:/.*)?$", flags)

    return is_negated, dir_only, pattern_re


class GitignoreParser:
    """Manages collection of Gitignore rules and evaluates path exemptions."""

    def __init__(self, root_dir: Optional[Path | str] = None) -> None:
        self.root_dir = Path(root_dir).resolve() if root_dir else Path.cwd().resolve()
        self.rules: List[GitignoreRule] = []

    @classmethod
    def from_directory(cls, target_dir: Path | str) -> GitignoreParser:
        """Constructs a parser discovering .gitignore in target_dir or its parent git root."""
        base_path = Path(target_dir).resolve()
        parser = cls(root_dir=base_path)

        # Check target_dir for .gitignore
        target_gitignore = base_path / ".gitignore"
        if target_gitignore.is_file():
            parser.add_file(target_gitignore, base_dir=base_path)
            return parser

        # Walk up to find git root if target_dir is a subfolder
        curr = base_path.parent
        while curr != curr.parent:
            candidate = curr / ".gitignore"
            if candidate.is_file():
                parser.add_file(candidate, base_dir=curr)
                break
            if (curr / ".git").exists():
                break
            curr = curr.parent

        return parser

    def add_file(self, gitignore_path: Path | str, base_dir: Optional[Path | str] = None) -> None:
        """Reads rules from a .gitignore file."""
        p = Path(gitignore_path).resolve()
        if not p.is_file():
            return
        base = Path(base_dir).resolve() if base_dir else p.parent
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            self.add_rules(content.splitlines(), base_dir=base)
        except OSError:
            pass

    def add_rules(self, lines: Sequence[str], base_dir: Path | str) -> None:
        """Parses gitignore lines and appends rules."""
        base_str = str(Path(base_dir).resolve()).replace("\\", "/")
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            is_negated, dir_only, pattern_re = _pattern_to_regex(stripped)
            self.rules.append(
                GitignoreRule(
                    raw_pattern=stripped,
                    is_negated=is_negated,
                    dir_only=dir_only,
                    pattern_re=pattern_re,
                    base_dir=base_str,
                )
            )

    def _matches_any_rule(self, abs_str: str, is_dir: bool) -> bool:
        """Evaluates whether an individual path string matches rules."""
        ignored = False
        for rule in self.rules:
            if not abs_str.startswith(rule.base_dir):
                continue

            rel = abs_str[len(rule.base_dir):].lstrip("/")
            if not rel:
                continue

            if rule.dir_only and not is_dir:
                continue

            if rule.pattern_re.search(rel):
                if rule.is_negated:
                    ignored = False
                else:
                    ignored = True
        return ignored

    def is_ignored(self, path: Path | str, is_dir: bool = False) -> bool:
        """Returns True if the path or any of its parent directories matches gitignore rules."""
        if not self.rules:
            return False

        abs_path = Path(path).resolve()
        abs_str = str(abs_path).replace("\\", "/")

        # 1. Check parent directories first (from base down)
        try:
            rel = abs_path.relative_to(self.root_dir)
            parts = rel.parts
            for i in range(1, len(parts)):
                parent_sub = str(self.root_dir / Path(*parts[:i])).replace("\\", "/")
                if self._matches_any_rule(parent_sub, is_dir=True):
                    return True
        except ValueError:
            pass

        # 2. Check the path itself
        return self._matches_any_rule(abs_str, is_dir=is_dir)
