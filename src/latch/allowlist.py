"""Shared, segment-anchored path allowlist matching for Latch.

Both the whole-codebase scanner (scanner.py) and the staged-diff parser
(diff_parser.py) need to decide whether a repository-relative file path is
exempt from PII/credential scanning via a configured allowlist pattern.

Historically each module implemented its own matcher, and the scanner's
version used a raw substring check (`clean_dir in norm_path`) that is
dangerously over-permissive: a pattern like "src/*" would also exempt
"notsrc/x.py" or "esrc/secret.py" because those paths merely *contain* the
substring "src/". This module implements ONE matcher used by both call
sites, with no substring checks: all matching is anchored to whole path
segments.

Pattern semantics
------------------
- A pattern with no "/" (e.g. "fixtures", "*.env") matches if ANY single
  path segment (directory name or the final filename) equals the pattern
  or matches it via `fnmatch` glob rules.
- A pattern with "/" is split into segments and matched as a contiguous,
  segment-anchored window anywhere within the path's segments (it does not
  have to start at the first path segment). Each pattern segment matches
  exactly one path segment via `fnmatch`, EXCEPT:
    * "**" matches zero or more path segments (crosses segment boundaries).
    * A trailing "*" (i.e. the pattern ends in "/*") matches one or more
      remaining path segments -- "everything under this directory".
  Because segments are compared with exact `fnmatch` tokens (no substring
  checks), "app/config" matches only a path whose segments contain the
  exact contiguous sequence ["app", "config"] (e.g. "app/config/secret.env"),
  and never "myapp/config", "app/configx", or "webapp/config".
"""

from __future__ import annotations
import fnmatch
from typing import List, Sequence


def _match_from(pat_segments: Sequence[str], pi: int, path_segments: Sequence[str], si: int) -> bool:
    """Recursively match pattern segments[pi:] against path segments[si:]."""
    if pi == len(pat_segments):
        # Pattern fully consumed: window matched (trailing path segments, if
        # any, are not required to be consumed -- the match is not anchored
        # to the end of the path).
        return True

    tok = pat_segments[pi]

    if tok == "**":
        # "**" matches zero or more path segments.
        for consumed in range(0, len(path_segments) - si + 1):
            if _match_from(pat_segments, pi + 1, path_segments, si + consumed):
                return True
        return False

    if tok == "*" and pi == len(pat_segments) - 1:
        # Trailing bare "*" means "everything under this directory": require
        # at least one more path segment remains after the preceding tokens.
        return si < len(path_segments)

    if si >= len(path_segments):
        return False
    if not fnmatch.fnmatch(path_segments[si], tok):
        return False
    return _match_from(pat_segments, pi + 1, path_segments, si + 1)


def _pattern_matches_segments(pattern: str, path_segments: Sequence[str]) -> bool:
    pat_segments: List[str] = [s for s in pattern.split("/") if s != ""]
    if not pat_segments:
        return False
    # Try every possible starting offset so the pattern window may appear
    # anywhere within the path, bounded by segment boundaries.
    for start in range(len(path_segments)):
        if _match_from(pat_segments, 0, path_segments, start):
            return True
    return False


def is_path_allowlisted(rel_path: str, allowlist_paths: Sequence[str]) -> bool:
    """Check whether a repo-relative path matches any configured allowlist pattern.

    Args:
        rel_path: Forward- or back-slash separated path, relative to repo root.
        allowlist_paths: Configured allowlist glob patterns.

    Returns:
        True if the path should be exempted from scanning.
    """
    if not allowlist_paths:
        return False

    norm_path = rel_path.replace("\\", "/").strip("/")
    if not norm_path:
        return False
    path_segments = norm_path.split("/")

    for pattern in allowlist_paths:
        clean_pat = pattern.replace("\\", "/").strip("/")
        if not clean_pat:
            continue
        if "/" not in clean_pat:
            # Patterns without slashes containing wildcards only match top-level files (review_03 N3)
            if any(ch in clean_pat for ch in ("*", "?", "[")):
                if len(path_segments) == 1 and fnmatch.fnmatch(path_segments[0], clean_pat):
                    return True
            else:
                # Exact segment match (e.g. directory "fixtures" or file "secret_template.py")
                if clean_pat in path_segments:
                    return True
        else:
            if _pattern_matches_segments(clean_pat, path_segments):
                return True

    return False


def compute_max_line_chars(max_chunk_tokens: int) -> int:
    """Canonical char budget per line before splitting into chunk-sized slices.

    Shared by scanner.py and diff_parser.py so both apply identical oversized
    single-line protection against the model's context window.
    """
    return max(100, (max_chunk_tokens - 10) * 4)
