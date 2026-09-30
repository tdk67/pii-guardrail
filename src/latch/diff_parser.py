"""Git diff inspection, extraction, and batch packing for Latch.

Extracts staged additions, filters out binary files and pure deletions,
and packs added lines into structured context buffers for Julia-1.
"""

from __future__ import annotations
import fnmatch
from pathlib import PurePath
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from typing import List, Optional, Sequence


class DiffParserError(Exception):
    """Raised when git diff cannot be extracted or environment is invalid."""
    pass


def estimate_line_tokens(content: str) -> int:
    """Canonical token estimation for a diff line (approx 4 chars/token + 2 formatting overhead)."""
    return max(1, len(content) // 4) + 2


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


@dataclass
class ParserStats:
    """Statistics on parsed diff additions and exemptions."""
    exempted_allowlist_files: int = 0
    exempted_allowlist_lines: int = 0
    exempted_pragma_lines: int = 0

    @property
    def total_exempted(self) -> int:
        return self.exempted_allowlist_lines + self.exempted_pragma_lines


class DiffParser:
    """Extracts, filters, and batches staged git diff additions."""
    last_stats: ParserStats = ParserStats()

    def __init__(
        self,
        max_chunk_tokens: int = 750,
        context_lines: int = 3,
        allowlist_paths: Optional[Sequence[str]] = None,
    ) -> None:
        self.max_chunk_tokens = max_chunk_tokens
        self.context_lines = context_lines
        self.allowlist_paths = list(allowlist_paths or [])
        self.last_stats: ParserStats = ParserStats()

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

    def get_staged_batches(self) -> List[DiffBatch]:
        """Extracts staged added lines and packs them into token-bounded DiffBatches."""
        lines = self.get_staged_added_lines()
        return self.pack_into_batches(lines)

    def _is_allowlisted(self, file_path: str) -> bool:
        """Check if file matches any path pattern in allowlist_paths."""
        if not self.allowlist_paths:
            return False
        clean_path = file_path.replace("\\", "/")
        p = PurePath(clean_path)
        for pattern in self.allowlist_paths:
            clean_pat = pattern.replace("\\", "/")
            if "/" in clean_pat or "**" in clean_pat:
                if fnmatch.fnmatch(clean_path, clean_pat):
                    return True
            else:
                # Top-level glob pattern without slashes (e.g. *.md) only matches root-level files
                if "/" not in clean_path and fnmatch.fnmatch(clean_path, clean_pat):
                    return True
                # Exact basename match if pattern is a specific filename without wildcards (e.g. LICENSE)
                if "*" not in clean_pat and p.name == clean_pat:
                    return True
        return False

    def parse_diff_text(self, diff_text: str) -> List[AddedLine]:
        """Pure functional parser extracting added lines and line numbers."""
        added_lines: List[AddedLine] = []
        self.last_stats = ParserStats()
        allowlisted_files_seen: set[str] = set()

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

            # Check if current file is in allowlist
            if self._is_allowlisted(current_file):
                if line.startswith("+") and not line.startswith("+++"):
                    self.last_stats.exempted_allowlist_lines += 1
                    if current_file not in allowlisted_files_seen:
                        allowlisted_files_seen.add(current_file)
                        self.last_stats.exempted_allowlist_files += 1
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
                content = line[1:]  # Strip leading +

                # Inline pragma: skip line if explicitly marked with latch:ignore
                if "latch:ignore" in content:
                    self.last_stats.exempted_pragma_lines += 1
                    current_target_line += 1
                    continue

                # Oversized single line splitting (protects model context from giant minified lines)
                max_line_chars = max(100, (self.max_chunk_tokens - 10) * 4)
                if len(content) > max_line_chars:
                    for start in range(0, len(content), max_line_chars):
                        chunk_content = content[start : start + max_line_chars]
                        added_lines.append(
                            AddedLine(
                                file_path=current_file,
                                line_number=current_target_line,
                                content=chunk_content,
                            )
                        )
                else:
                    added_lines.append(
                        AddedLine(
                            file_path=current_file,
                            line_number=current_target_line,
                            content=content,
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
            line_tokens = estimate_line_tokens(line.content)

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


def bisect_buffer(batch: DiffBatch) -> tuple[DiffBatch, DiffBatch]:
    """Splits a DiffBatch into two halves by file boundaries or line midpoint.

    If multiple files are present, splits at the file boundary closest to
    the line count midpoint. Otherwise, splits the lines of the single file in half.
    """
    lines = batch.lines
    if len(lines) <= 1:
        return batch, batch

    mid = len(lines) // 2

    # Check if multiple files exist
    files = {line.file_path for line in lines}
    split_idx = mid

    if len(files) > 1:
        # Find file boundary closest to midpoint
        best_boundary = -1
        best_distance = len(lines)
        for i in range(1, len(lines)):
            if lines[i].file_path != lines[i - 1].file_path:
                distance = abs(i - mid)
                if distance < best_distance:
                    best_distance = distance
                    best_boundary = i
        if best_boundary != -1 and 0 < best_boundary < len(lines):
            split_idx = best_boundary

    left_lines = lines[:split_idx]
    right_lines = lines[split_idx:]

    left_tokens = sum(estimate_line_tokens(l.content) for l in left_lines)
    right_tokens = sum(estimate_line_tokens(l.content) for l in right_lines)

    left_batch = DiffBatch(
        batch_id=f"{batch.batch_id}-L",
        lines=left_lines,
        estimated_tokens=left_tokens,
    )
    right_batch = DiffBatch(
        batch_id=f"{batch.batch_id}-R",
        lines=right_lines,
        estimated_tokens=right_tokens,
    )
    return left_batch, right_batch

