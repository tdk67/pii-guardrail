"""Git diff inspection, extraction, and batch packing for Latch.

Extracts staged additions, filters out binary files and pure deletions,
and packs added lines into structured context buffers for Julia-1.
"""

from __future__ import annotations
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import List, Sequence


class DiffParserError(Exception):
    """Raised when git diff cannot be extracted or environment is invalid."""
    pass


@dataclass(frozen=True)
class AddedLine:
    """Represents a single added line in the staged git diff."""
    file_path: str
    line_number: int
    content: str


@dataclass
class DiffBatch:
    """A batch of added lines formatted for Julia-1 context evaluation."""
    batch_id: str
    lines: List[AddedLine]
    estimated_tokens: int

    def formatted_text(self) -> str:
        """Renders lines into formatted file blocks: === File: <path> ===."""
        if not self.lines:
            return ""
        
        blocks: List[str] = []
        current_file: str | None = None
        current_file_lines: List[str] = []

        for line in self.lines:
            if line.file_path != current_file:
                if current_file is not None:
                    blocks.append(f"=== File: {current_file} ===\n" + "\n".join(current_file_lines))
                current_file = line.file_path
                current_file_lines = []
            current_file_lines.append(f"+ {line.content}")

        if current_file is not None and current_file_lines:
            blocks.append(f"=== File: {current_file} ===\n" + "\n".join(current_file_lines))

        return "\n\n".join(blocks)


class DiffParser:
    """Extracts, filters, and batches staged git diff additions."""

    def __init__(self, max_chunk_tokens: int = 750) -> None:
        self.max_chunk_tokens = max_chunk_tokens

    @staticmethod
    def preflight_check() -> None:
        """Verify git executable is on PATH and current dir is in a git repo."""
        if shutil.which("git") is None:
            raise DiffParserError(
                "'git' executable not found on PATH. Install Git 2.25+ and ensure it is on system PATH."
            )
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0 or res.stdout.strip() != "true":
                raise DiffParserError(
                    "Not a git repository. Run latch from within a git-tracked project."
                )
        except Exception as err:
            if isinstance(err, DiffParserError):
                raise
            raise DiffParserError(f"Git pre-flight check failed: {err}") from err

    def get_staged_diff_text(self) -> str:
        """Run git diff --staged and return raw output."""
        self.preflight_check()
        try:
            res = subprocess.run(
                ["git", "diff", "--staged", "--no-ext-diff", "--no-color"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            return res.stdout
        except subprocess.CalledProcessError as err:
            raise DiffParserError(f"Failed to execute git diff --staged: {err}") from err

    def get_staged_added_lines(self) -> List[AddedLine]:
        """Fetch and parse staged diff additions."""
        raw_diff = self.get_staged_diff_text()
        return self.parse_diff_text(raw_diff)

    def parse_diff_text(self, diff_text: str) -> List[AddedLine]:
        """Pure functional parser extracting added lines and line numbers."""
        added_lines: List[AddedLine] = []
        if not diff_text.strip():
            return added_lines

        current_file: str | None = None
        current_target_line: int = 0
        in_binary_file: bool = False

        diff_file_pattern = re.compile(r"^diff --git a/(.*?) b/(.*?)$")
        hunk_header_pattern = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

        for line in diff_text.splitlines():
            # Check for new file diff
            file_match = diff_file_pattern.match(line)
            if file_match:
                current_file = file_match.group(2)
                current_target_line = 0
                in_binary_file = False
                continue

            # Check for binary file notification
            if "Binary files " in line and " differ" in line:
                in_binary_file = True
                continue

            if in_binary_file or current_file is None:
                continue

            # Check for hunk header
            hunk_match = hunk_header_pattern.match(line)
            if hunk_match:
                current_target_line = int(hunk_match.group(1))
                continue

            if current_target_line == 0:
                continue

            # Parse additions, deletions, and context
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(
                    AddedLine(
                        file_path=current_file,
                        line_number=current_target_line,
                        content=line[1:],  # Strip leading +
                    )
                )
                current_target_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                # Deletions do not advance target (new file) line counter
                continue
            else:
                # Unchanged context line advances target line counter
                current_target_line += 1

        return added_lines

    def pack_into_batches(self, lines: Sequence[AddedLine]) -> List[DiffBatch]:
        """Packs AddedLine items into DiffBatch objects up to max_chunk_tokens."""
        if not lines:
            return []

        batches: List[DiffBatch] = []
        current_lines: List[AddedLine] = []
        current_tokens = 0

        for line in lines:
            # Estimate tokens: roughly 4 chars per token + formatting overhead
            line_tokens = max(1, len(line.content) // 4) + 2

            if current_lines and (current_tokens + line_tokens > self.max_chunk_tokens):
                batches.append(
                    DiffBatch(
                        batch_id=str(uuid.uuid4()),
                        lines=current_lines,
                        estimated_tokens=current_tokens,
                    )
                )
                current_lines = [line]
                current_tokens = line_tokens
            else:
                current_lines.append(line)
                current_tokens += line_tokens

        if current_lines:
            batches.append(
                DiffBatch(
                    batch_id=str(uuid.uuid4()),
                    lines=current_lines,
                    estimated_tokens=current_tokens,
                )
            )

        return batches
