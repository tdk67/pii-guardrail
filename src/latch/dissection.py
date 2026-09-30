"""Binary dissection and localization engine for Latch.

Divide-and-conquer algorithm that bisects an offending multi-file or large-file
diff batch down to the specific file and a tight context window (<= 25 lines).
Implements conservative fallback: if both split halves score below threshold
(e.g., when multi-line PII spans the split line), the parent window is returned.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
from latch.config import DEFAULT_PII_THRESHOLD
from latch.diff_parser import DiffBatch, bisect_buffer
from latch.engine import EvaluationResult


@dataclass
class DissectionResult:
    """Localized context window isolating the detected PII or credential."""
    offending_file: str
    start_line: int
    end_line: int
    snippet: str
    probability: float


class Dissector:
    """Recursively localizes sensitive leaks within a DiffBatch."""

    def __init__(
        self,
        threshold: float = DEFAULT_PII_THRESHOLD,
        window_limit: int = 25,
        max_depth: int = 15,
    ) -> None:
        self.threshold = threshold
        self.window_limit = window_limit
        self.max_depth = max_depth

    def dissect(
        self,
        batch: DiffBatch,
        evaluate_fn: Callable[[str], EvaluationResult],
        initial_probability: Optional[float] = None,
    ) -> DissectionResult:
        """Divide-and-conquer localization to pinpoint leak to <= window_limit lines."""
        current = batch
        depth = 0

        # Use passed parent evaluation if available to eliminate wasted redundant inference
        if initial_probability is not None:
            current_prob = initial_probability
        else:
            init_eval = evaluate_fn(current.formatted_text())
            current_prob = init_eval.probability

        while (len({l.file_path for l in current.lines}) > 1 or len(current.lines) > self.window_limit) and depth < self.max_depth:
            depth += 1
            left, right = bisect_buffer(current)

            # Prevent zero progress
            if len(left.lines) == 0 or len(right.lines) == 0:
                break

            # Evaluate left branch
            left_eval = evaluate_fn(left.formatted_text())
            if left_eval.probability >= self.threshold:
                current = left
                current_prob = left_eval.probability
                continue

            # Evaluate right branch
            right_eval = evaluate_fn(right.formatted_text())
            if right_eval.probability >= self.threshold:
                current = right
                current_prob = right_eval.probability
                continue

            # Conservative Fallback:
            # If neither half exceeded the threshold, the sensitive token or context
            # likely spans the exact split boundary. Conservatively return current parent.
            break

        return self._build_result(current, current_prob)

    def _build_result(self, batch: DiffBatch, probability: float) -> DissectionResult:
        """Constructs DissectionResult and formats line-numbered snippet accurately."""
        lines = batch.lines
        if not lines:
            return DissectionResult(
                offending_file="unknown",
                start_line=1,
                end_line=1,
                snippet="",
                probability=probability,
            )

        unique_files = list(dict.fromkeys(l.file_path for l in lines))
        first_line = lines[0]
        last_line = lines[-1]

        # Strictly respect self.window_limit (<= 25 lines)
        display_lines = lines[: self.window_limit]
        snippet_lines = []
        last_file = None
        for l in display_lines:
            if len(unique_files) > 1 and l.file_path != last_file:
                snippet_lines.append(f"--- File: {l.file_path} ---")
                last_file = l.file_path
            snippet_lines.append(f"{l.line_number:4d} | {l.content}")

        if len(lines) > len(display_lines):
            snippet_lines.append(f"     ... ({len(lines) - len(display_lines)} more lines in parent window)")

        snippet = "\n".join(snippet_lines)

        offending_file = first_line.file_path if len(unique_files) == 1 else ", ".join(unique_files)
        start_line = first_line.line_number
        end_line = last_line.line_number

        return DissectionResult(
            offending_file=offending_file,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet,
            probability=probability,
        )

