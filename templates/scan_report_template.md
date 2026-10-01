# 🛡️ Latch Codebase Scan Report

**Target Directory:** `{target_dir}`  
**Generated:** `{timestamp}`  
**Status:** **{status}**

---

## 📊 Executive Summary

| Metric | Value |
| :--- | :--- |
| **Files Inspected** | {total_files} |
| **Total Lines Scanned** | {total_lines} |
| **Context Chunks Evaluated** | {total_chunks} |
| **Sensitive Findings** | **{leaks_count}** |
| **Pragma Exemptions (`# latch:ignore`)** | {exempted_pragma_lines} |
| **Allowlisted File Exemptions** | {exempted_allowlist_files} |
| **Gitignore File Exemptions** | {exempted_gitignore_files} |
| **Ignored Directories** | {ignored_dirs} |
| **Total Scan Latency** | {total_latency_ms} ms ({latency_sec}s) |
| **Inference Mode** | `{mode}` |

---

## 🔍 Isolated Findings

{findings_section}

---

## 💡 Allowlist & Whitelist Recommendations

To exempt false positives or mock fixtures in future scans, consider adding the following patterns:

```json
"allowlist_paths": [
{suggested_patterns_json}
]
```

### Alternative Exemption Mechanisms:
1. **Directory Exclusion Flag**: Rerun the scan with `--ignore-dir <directory_name>`
2. **Path Allowlist Flag**: Rerun the scan with `--allowlist "<glob_pattern>"`
3. **Inline Line Pragma**: Append `# latch:ignore` (Python/JS/Shell) or `<!-- latch:ignore -->` (HTML/XML) to offending lines.
