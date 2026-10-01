"""Full-codebase scanner for Latch.

Traverses a repository or directory, filters source files, packs lines into
context windows, and evaluates content using Julia-1 and the  # latch:ignore
binary dissection localization engine.
"""

from __future__ import annotations
import datetime
import fnmatch
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from latch.client import Client
from latch.config import DEFAULT_PII_THRESHOLD, LatchConfig, get_config
from latch.diff_parser import AddedLine, DiffBatch, DiffParser, LATCH_IGNORE_PRAGMA
from latch.dissection import DissectionResult, Dissector
from latch.prompt import StateBuilder

DEFAULT_SCAN_EXTENSIONS: FrozenSet[str] = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".sql", ".html", ".css", ".sh", ".bash", ".zsh", ".ps1",
    ".md", ".env", ".txt", ".cfg", ".ini", ".conf",
})

DEFAULT_IGNORED_DIRS: FrozenSet[str] = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".latch", "dist", "build", ".egg-info",
    ".idea", ".vscode", "models", ".next", ".nuxt", "out",
    "coverage", ".turbo", ".cache", ".parcel-cache",
})

DEFAULT_IGNORED_FILES: FrozenSet[str] = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Pipfile.lock",
    "poetry.lock", "composer.lock", "Cargo.lock",
})


def is_binary_file(file_path: Path) -> bool:
    """Fast check whether a file contains null bytes or binary content."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except OSError:
        return True


@dataclass
class ScanReport:
    """Quantitative summary of whole-codebase scan results."""
    target_dir: str
    total_files: int
    total_lines: int
    total_chunks: int
    leaks: List[DissectionResult] = field(default_factory=list)
    total_latency_ms: int = 0
    mode: str = "in_process"
    exempted_pragma_lines: int = 0
    exempted_allowlist_files: int = 0
    threshold: float = DEFAULT_PII_THRESHOLD
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    @property
    def is_clean(self) -> bool:
        return len(self.leaks) == 0

    def get_suggested_allowlists(self) -> List[str]:
        """Analyzes leak locations and generates recommended allowlist paths."""
        if not self.leaks:
            return []
        suggestions: Set[str] = set()
        dir_counts: Dict[str, int] = {}

        for leak in self.leaks:
            norm = leak.offending_file.replace("\\", "/").strip("/")
            parts = norm.split("/")
            if len(parts) > 1:
                parent = "/".join(parts[:-1])
                dir_counts[parent] = dir_counts.get(parent, 0) + 1

            for i, part in enumerate(parts[:-1]):
                lower = part.lower()
                if any(kw in lower for kw in ("fixture", "mock", "testdata", "sample")):
                    subpath = "/".join(parts[: i + 1])
                    suggestions.add(f"{subpath}/*")
                    suggestions.add(f"**/{part}/**")

        for parent, count in dir_counts.items():
            if count >= 2:
                suggestions.add(f"{parent}/*")

        if not suggestions and dir_counts:
            for parent in sorted(dir_counts.keys())[:3]:
                suggestions.add(f"{parent}/*")

        return sorted(suggestions)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to serializable dictionary."""
        return {
            "target_dir": self.target_dir,
            "timestamp": self.timestamp,
            "is_clean": self.is_clean,
            "status": "CLEAN" if self.is_clean else "BLOCKED",
            "threshold": self.threshold,
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "total_chunks": self.total_chunks,
            "leaks_count": len(self.leaks),
            "total_latency_ms": self.total_latency_ms,
            "mode": self.mode,
            "exempted_pragma_lines": self.exempted_pragma_lines,
            "exempted_allowlist_files": self.exempted_allowlist_files,
            "suggested_allowlists": self.get_suggested_allowlists(),
            "findings": [
                {
                    "file": leak.offending_file.replace("\\", "/"),
                    "start_line": leak.start_line,
                    "end_line": leak.end_line,
                    "probability": round(leak.probability, 4),
                    "threshold": self.threshold,
                    "snippet": leak.snippet,
                }
                for leak in self.leaks
            ],
        }

    def to_markdown(self) -> str:
        """Convert report to comprehensive Markdown document using template."""
        pkg_root = Path(__file__).resolve().parent.parent.parent
        template_file = pkg_root / "templates" / "scan_report_template.md"

        template_text = ""
        if template_file.exists():
            try:
                template_text = template_file.read_text(encoding="utf-8")
            except OSError:
                template_text = ""

        if self.is_clean:
            findings_section = "✅ **No sensitive PII or credentials detected across scanned files.**"
        else:
            findings_blocks = []
            for idx, leak in enumerate(self.leaks, start=1):
                clean_file = leak.offending_file.replace("\\", "/")
                abs_target = Path(self.target_dir) / clean_file
                file_link = f"[{clean_file}](file:///{str(abs_target.resolve()).replace(os.sep, '/')}#L{leak.start_line}-L{leak.end_line})"
                block = [
                    f"### Finding {idx}: {file_link} (Lines {leak.start_line}–{leak.end_line})",
                    f"- **Confidence:** `{leak.probability:.2f}` (Threshold: `{self.threshold:.2f}`)",
                    f"- **Status:** Sensitive leak isolated by binary dissection",
                    "",
                    "```",
                    leak.snippet,
                    "```",
                    "",
                ]
                findings_blocks.append("\n".join(block))
            findings_section = "\n".join(findings_blocks)

        suggestions = self.get_suggested_allowlists()
        suggested_json = "\n".join(f'    "{p}",' for p in suggestions) if suggestions else '    "fixtures/*"'

        if template_text:
            return template_text.format(
                target_dir=self.target_dir,
                timestamp=self.timestamp,
                status="CLEAN - Passed" if self.is_clean else f"BLOCKED - {len(self.leaks)} Leak(s) Detected",
                total_files=self.total_files,
                total_lines=self.total_lines,
                total_chunks=self.total_chunks,
                leaks_count=len(self.leaks),
                exempted_pragma_lines=self.exempted_pragma_lines,
                exempted_allowlist_files=self.exempted_allowlist_files,
                total_latency_ms=self.total_latency_ms,
                latency_sec=self.total_latency_ms / 1000.0,
                mode=self.mode,
                findings_section=findings_section,
                suggested_patterns_json=suggested_json,
            )
        else:
            return f"# Latch Scan Report\n\nTarget: {self.target_dir}\nLeaks: {len(self.leaks)}\n\n{findings_section}"

    def save_reports(self, output_dir_or_file: Optional[str] = None) -> Tuple[Path, Path]:
        """Persists markdown and json reports to disk."""
        if output_dir_or_file:
            target_path = Path(output_dir_or_file).resolve()
            if target_path.suffix in (".md", ".markdown"):
                md_path = target_path
                json_path = target_path.with_suffix(".json")
            elif target_path.suffix == ".json":
                json_path = target_path
                md_path = target_path.with_suffix(".md")
            else:
                target_path.mkdir(parents=True, exist_ok=True)
                md_path = target_path / "scan_report.md"
                json_path = target_path / "scan_report.json"
        else:
            base_dir = Path(self.target_dir) if Path(self.target_dir).is_dir() else Path.cwd()
            reports_dir = base_dir / ".latch" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            md_path = reports_dir / "scan_report.md"
            json_path = reports_dir / "scan_report.json"

        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        json_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

        return md_path, json_path


class Scanner:
    """Orchestrates full-codebase scanning across directory trees."""

    def __init__(
        self,
        config: Optional[LatchConfig] = None,
        client: Optional[Client] = None,
        diff_parser: Optional[DiffParser] = None,
        dissector: Optional[Dissector] = None,
        state_builder: Optional[StateBuilder] = None,
        allowlist_paths: Optional[Sequence[str]] = None,
        ignored_dirs: Optional[Sequence[str]] = None,
    ) -> None:
        self.config = config or get_config()
        self.client = client or Client(self.config)

        combined_allowlists = list(self.config.allowlist_paths or [])
        if allowlist_paths:
            combined_allowlists.extend(allowlist_paths)
        self.allowlist_paths = combined_allowlists

        combined_ignored = set(DEFAULT_IGNORED_DIRS)
        if ignored_dirs:
            combined_ignored.update(ignored_dirs)
        self.ignored_dirs = combined_ignored

        self.diff_parser = diff_parser or DiffParser(
            max_chunk_tokens=self.config.max_chunk_tokens,
            allowlist_paths=self.allowlist_paths,
        )
        self.dissector = dissector or Dissector(
            threshold=self.config.pii_threshold,
            window_limit=self.config.localization_window_lines,
            max_depth=self.config.max_dissection_depth,
        )
        self.state_builder = state_builder or StateBuilder(config=self.config)

    def _is_path_allowlisted(self, rel_path: str) -> bool:
        """Check if relative path matches any configured allowlist pattern."""
        norm_path = rel_path.replace("\\", "/").strip("/")
        path_parts = norm_path.split("/")

        for pattern in self.allowlist_paths:
            clean_pat = pattern.replace("\\", "/").strip("/")
            if not clean_pat:
                continue

            # Case 1: Direct glob match
            if fnmatch.fnmatch(norm_path, clean_pat):
                return True

            # Case 2: Match with leading wildcard (e.g. "fixtures/*" matches "tests/fixtures/foo.html")
            if fnmatch.fnmatch(norm_path, f"*/{clean_pat}") or fnmatch.fnmatch(norm_path, f"**/{clean_pat}"):
                return True

            # Case 3: Pattern has no slashes (e.g. "fixtures" or "*.min.js")
            if "/" not in clean_pat:
                if fnmatch.fnmatch(path_parts[-1], clean_pat):
                    return True
                if any(fnmatch.fnmatch(part, clean_pat) for part in path_parts[:-1]):
                    return True
            else:
                # Case 4: Directory prefix or subpath
                clean_dir = clean_pat.rstrip("/*")
                if clean_dir in norm_path or fnmatch.fnmatch(norm_path, f"{clean_dir}/*") or fnmatch.fnmatch(norm_path, f"*/{clean_dir}/*"):
                    return True

        return False


    def collect_source_files(
        self,
        target_dir: Path,
        extensions: Set[str],
        ignored_dirs: Set[str],
        ignored_files: Optional[Set[str]] = None,
    ) -> Tuple[List[Path], int]:
        """Walks directory and yields non-ignored, text source files."""
        matched_files: List[Path] = []
        allowlisted_count = 0
        active_ignored_files = ignored_files if ignored_files is not None else set(DEFAULT_IGNORED_FILES)

        for root, dirs, files in os.walk(target_dir):
            # In-place prune of ignored directory names
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]

            rel_root = os.path.relpath(root, target_dir)
            if rel_root != "." and self._is_path_allowlisted(rel_root):
                dirs.clear()
                continue

            for fname in files:
                # Skip dependency lockfiles and generated minified bundles
                lower_name = fname.lower()
                if fname in active_ignored_files:
                    continue
                if lower_name.endswith(".min.js") or lower_name.endswith(".min.css") or lower_name.endswith(".map"):
                    continue

                ext = os.path.splitext(fname)[1].lower()
                if not ext and fname.startswith("."):
                    ext = fname.lower()

                if ext in extensions:
                    full_path = Path(root) / fname
                    rel_file = str(full_path.relative_to(target_dir)).replace("\\", "/")

                    if self._is_path_allowlisted(rel_file):
                        allowlisted_count += 1
                        continue

                    if not is_binary_file(full_path):
                        matched_files.append(full_path)

        return sorted(matched_files), allowlisted_count

    def scan(
        self,
        target_dir: str = ".",
        extensions: Optional[Sequence[str]] = None,
        threshold: Optional[float] = None,
        max_chunk_tokens: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        allowlist_paths: Optional[Sequence[str]] = None,
        ignored_dirs: Optional[Sequence[str]] = None,
    ) -> ScanReport:
        """Executes full scan of target directory and returns ScanReport."""
        root_path = Path(target_dir).resolve()
        if not root_path.exists() or not root_path.is_dir():
            raise ValueError(f"Target scan directory '{target_dir}' does not exist or is not a directory.")

        active_threshold = threshold if threshold is not None else self.config.pii_threshold
        active_chunk_tokens = max_chunk_tokens if max_chunk_tokens is not None else self.config.max_chunk_tokens

        active_exts = set(e.lower() for e in extensions) if extensions else set(DEFAULT_SCAN_EXTENSIONS)
        
        active_ignored = set(self.ignored_dirs)
        if ignored_dirs:
            active_ignored.update(ignored_dirs)

        if allowlist_paths:
            for p in allowlist_paths:
                if p not in self.allowlist_paths:
                    self.allowlist_paths.append(p)

        # Collect source files
        source_files, allowlisted_files = self.collect_source_files(
            root_path,
            extensions=active_exts,
            ignored_dirs=active_ignored,
        )

        all_lines: List[AddedLine] = []
        total_source_lines = 0
        pragma_exemptions = 0

        max_line_chars = max(100, (active_chunk_tokens - 10) * 4)

        for fpath in source_files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel_path = str(fpath.relative_to(root_path)).replace("\\", "/")
            lines = content.splitlines()
            total_source_lines += len(lines)

            for i, line_content in enumerate(lines, start=1):
                if LATCH_IGNORE_PRAGMA in line_content:
                    pragma_exemptions += 1
                    continue

                if len(line_content) > max_line_chars:
                    for start in range(0, len(line_content), max_line_chars):
                        chunk_text = line_content[start : start + max_line_chars]
                        all_lines.append(
                            AddedLine(
                                file_path=rel_path,
                                line_number=i,
                                content=chunk_text,
                            )
                        )
                else:
                    all_lines.append(
                        AddedLine(
                            file_path=rel_path,
                            line_number=i,
                            content=line_content,
                        )
                    )

        # Batch lines
        custom_parser = DiffParser(
            max_chunk_tokens=active_chunk_tokens,
            allowlist_paths=self.allowlist_paths,
        )
        batches = custom_parser.pack_into_batches(all_lines)

        leaks: List[DissectionResult] = []  # latch:ignore
        total_latency = 0
        last_mode = "in_process"

        # Evaluate batches
        for idx, batch in enumerate(batches):
            if progress_callback:
                progress_callback(idx + 1, len(batches))

            prompt_state = self.state_builder.build(batch.formatted_text())
            eval_result = self.client.evaluate(prompt_state, request_id=batch.batch_id)
            total_latency += eval_result.latency_ms
            last_mode = self.client.last_mode

            if eval_result.error is not None:
                continue

            if not eval_result.is_clean(active_threshold):
                # Dissect and isolate needle window
                localized = self.dissector.dissect(
                    batch,
                    evaluate_fn=lambda txt: self.client.evaluate(
                        self.state_builder.build(txt),
                        request_id=batch.batch_id,
                    ),
                    initial_probability=eval_result.probability,
                )
                if localized.probability >= active_threshold:
                    leaks.append(localized)  # latch:ignore

        return ScanReport(
            target_dir=str(root_path),
            total_files=len(source_files),
            total_lines=total_source_lines,
            total_chunks=len(batches),
            leaks=leaks,  # latch:ignore
            total_latency_ms=total_latency,
            mode=last_mode,
            exempted_pragma_lines=pragma_exemptions,
            exempted_allowlist_files=allowlisted_files,
            threshold=active_threshold,
        )

