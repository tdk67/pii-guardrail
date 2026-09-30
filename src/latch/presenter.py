"""Terminal visuals and ANSI presentation for Latch.

Provides clean monospace status lines for clean commits, high-contrast framed
banners for blocked commits, and fail-closed diagnostic banners for system errors.
Isolates all UI/terminal formatting from core business and engine logic.
"""

from __future__ import annotations
import os
import sys
from typing import List, Optional


class Presenter:
    """Formats terminal alerts and messages for Latch."""

    # ANSI escape codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"

    def __init__(self, use_color: Optional[bool] = None) -> None:
        if use_color is None:
            self.use_color = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
        else:
            self.use_color = use_color

        # Check if console encoding supports unicode symbols
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        try:
            "✓┌─┐│└┘".encode(encoding)
            self.supports_unicode = True
        except (UnicodeEncodeError, LookupError):
            self.supports_unicode = False

    def _c(self, code: str, text: str) -> str:
        """Wrap text in color code if colors are enabled."""
        if not self.use_color:
            return text
        return f"{code}{text}{self.RESET}"

    def _build_frame(self, title: str) -> List[str]:
        """Constructs an ANSI-framed 3-line alert box (top, mid, bottom)."""
        banner_title = f" {title} "
        border_char = "─" if self.supports_unicode else "="
        banner_border = border_char * len(banner_title)

        c_tl = "┌" if self.supports_unicode else "+"
        c_tr = "┐" if self.supports_unicode else "+"
        c_bl = "└" if self.supports_unicode else "+"
        c_br = "┘" if self.supports_unicode else "+"
        c_bar = "│" if self.supports_unicode else "|"

        top = self._c(self.RED + self.BOLD, f"{c_tl}{banner_border}{c_tr}")
        mid = self._c(self.RED + self.BOLD, f"{c_bar}{banner_title}{c_bar}")
        bot = self._c(self.RED + self.BOLD, f"{c_bl}{banner_border}{c_br}")

        return [top, mid, bot]

    def format_clean(
        self,
        latency_ms: int,
        mode: str = "daemon",
        exempted_allowlist: int = 0,
        exempted_pragma: int = 0,
    ) -> str:
        """Quiet monospace success output for approved commits."""
        symbol = "✓" if self.supports_unicode else "[OK]"
        prefix = self._c(self.GREEN + self.BOLD, f"{symbol} Latch:")
        mode_label = "daemon" if mode == "daemon" else ("diff" if mode == "diff" else "in-process")

        exemption_parts = []
        if exempted_allowlist > 0:
            exemption_parts.append(f"{exempted_allowlist} allowlist")
        if exempted_pragma > 0:
            exemption_parts.append(f"{exempted_pragma} pragma")

        if exemption_parts:
            exemptions_str = f", {', '.join(exemption_parts)} exempted"
        else:
            exemptions_str = ""

        msg = self._c(self.GREEN, f" Clean ({latency_ms}ms, {mode_label}{exemptions_str})")
        return f"{prefix}{msg}"

    def format_blocked(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        probability: float,
        threshold: float,
        snippet: str,
    ) -> str:
        """High-contrast framed alert banner when sensitive PII is detected."""
        frame = self._build_frame("[LATCH BLOCKED] Sensitive PII or Credentials Detected")
        line_count = max(1, end_line - start_line + 1)

        details = [
            *frame,
            f"{self._c(self.BOLD, 'File:')}   {self._c(self.CYAN, file_path)}",
            f"{self._c(self.BOLD, 'Lines:')}  {start_line}-{end_line} (Pinpointed window: {line_count} lines)",
            f"{self._c(self.BOLD, 'Reason:')} PII confidence {probability:.2f} >= threshold {threshold:.2f}",
            "",
            f"{self._c(self.BOLD, 'Context Window:')}",
            snippet,
            "",
            self._c(
                self.YELLOW,
                "Commit aborted. Remove sensitive data or stage clean changes before committing."
            ),
        ]
        return "\n".join(details)

    def format_error(self, title: str, error_detail: str, action: str, context: str = "Commit") -> str:  # latch:ignore
        """Strict fail-closed system error alert banner."""
        frame = self._build_frame("[LATCH SYSTEM ERROR] Evaluation Aborted (Fail-Closed)")

        details = [
            *frame,
            f"{self._c(self.BOLD, 'Error:')}  {title}: {error_detail}",
            f"{self._c(self.BOLD, 'Action:')} {action}",
            "",
            self._c(
                self.YELLOW,
                f"{context} aborted under strict fail-closed safety policy."  # latch:ignore
            ),
        ]
        return "\n".join(details)

