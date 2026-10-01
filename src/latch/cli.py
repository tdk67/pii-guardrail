"""Command-Line Interface for Latch.

Entry point for pre-commit checks, model downloads, hook installation,
daemon management, and evaluation benchmarks.
"""

from __future__ import annotations
import argparse
import os
import sys
from typing import Any, Optional, Sequence
from latch.client import Client
from latch.config import ConfigError, LatchConfig, get_config
from latch.daemon import DaemonManager
from latch.diff_parser import DiffParser, DiffParserError, ParserStats
from latch.dissection import Dissector
from latch.engine import JuliaEngine, JuliaEngineError
from latch.hook import HookInstallError, install_pre_commit_hook, uninstall_pre_commit_hook
from latch.presenter import Presenter
from latch.prompt import StateBuilder


def run_check(
    config: Optional[LatchConfig] = None,
    parser: Optional[DiffParser] = None,
    engine: Optional[JuliaEngine] = None,
    presenter: Optional[Presenter] = None,
    client: Optional[Client] = None,
) -> int:
    """Core pre-commit check command. Returns exit code (0 = clean, 1 = blocked/error)."""
    cfg = config or get_config()
    pres = presenter or Presenter()
    pars = parser or DiffParser(
        max_chunk_tokens=cfg.max_chunk_tokens,
        allowlist_paths=cfg.allowlist_paths,
    )

    try:
        # Pre-flight check & staged diff extraction
        added_lines = pars.get_staged_added_lines()
        raw_stats = getattr(pars, "last_stats", None)
        stats = raw_stats if isinstance(raw_stats, ParserStats) else ParserStats()

        if not added_lines:
            # Pure deletions, binary files, allowlisted, or pragma-ignored diffs
            if stats.total_exempted > 0:
                clean_msg = pres.format_clean(
                    latency_ms=0,
                    mode="diff",
                    exempted_allowlist=stats.exempted_allowlist_lines,
                    exempted_pragma=stats.exempted_pragma_lines,
                )
                print(clean_msg)
            return 0

        # Pack into buffers
        batches = pars.pack_into_batches(added_lines)
        if not batches:
            if stats.total_exempted > 0:
                clean_msg = pres.format_clean(
                    latency_ms=0,
                    mode="diff",
                    exempted_allowlist=stats.exempted_allowlist_lines,
                    exempted_pragma=stats.exempted_pragma_lines,
                )
                print(clean_msg)
            return 0

        # Two-tier runner: routes to warm daemon (~1-2s warm inference) or falls back in-process
        if client is not None:
            active_client = client
        elif engine is not None:
            # Caller passed explicit engine (e.g. test mock); bypass external daemon
            active_client = Client(cfg, in_process_engine=engine, prefer_daemon=False)
        else:
            active_client = Client(cfg)

        state_builder = StateBuilder(config=cfg)
        total_latency_ms = 0

        # Evaluate each batch
        for batch in batches:
            prompt_state = state_builder.build(batch.formatted_text())
            eval_result = active_client.evaluate(prompt_state, request_id=batch.batch_id)
            total_latency_ms += eval_result.latency_ms

            if eval_result.error is not None:
                error_msg = pres.format_error(
                    title="Evaluation Engine Error",
                    error_detail=eval_result.error,
                    action="Check model weights or run 'python -m latch.cli check' after restarting daemon.",
                )
                print(error_msg, file=sys.stderr)
                return 1

            if not eval_result.is_clean(cfg.pii_threshold):
                # PII or credentials detected: run binary dissection localization
                dissector = Dissector(
                    threshold=cfg.pii_threshold,
                    window_limit=cfg.localization_window_lines,
                    max_depth=cfg.max_dissection_depth,
                )
                dissect_res = dissector.dissect(
                    batch,
                    evaluate_fn=lambda txt: active_client.evaluate(state_builder.build(txt), request_id=batch.batch_id),
                    initial_probability=eval_result.probability,
                )

                if dissect_res.probability >= cfg.pii_threshold:
                    alert = pres.format_blocked(
                        file_path=dissect_res.offending_file,
                        start_line=dissect_res.start_line,
                        end_line=dissect_res.end_line,
                        probability=dissect_res.probability,
                        threshold=cfg.pii_threshold,
                        snippet=dissect_res.snippet,
                    )
                    print(alert, file=sys.stderr)
                    return 1

        # All batches approved
        clean_msg = pres.format_clean(
            latency_ms=total_latency_ms,
            mode=active_client.last_mode,
            exempted_allowlist=stats.exempted_allowlist_lines,
            exempted_pragma=stats.exempted_pragma_lines,
        )
        print(clean_msg)
        return 0

    except DiffParserError as err:
        error_msg = pres.format_error(
            title="Git Environment Error",
            error_detail=str(err),
            action="Ensure you are running inside a git repository with Git 2.25+ installed.",
        )
        print(error_msg, file=sys.stderr)
        return 1
    except JuliaEngineError as err:
        error_msg = pres.format_error(
            title="Julia-1 Engine Failure",
            error_detail=str(err),
            action="Run 'python -m latch.cli download-model' or check config.json 'model_path'.",
        )
        print(error_msg, file=sys.stderr)
        return 1
    except ConfigError as err:
        error_msg = pres.format_error(
            title="Configuration Error",
            error_detail=str(err),
            action="Verify config.json operational parameters and schema.",
        )
        print(error_msg, file=sys.stderr)
        return 1
    except Exception as err:
        error_msg = pres.format_error(
            title="Unexpected System Error",
            error_detail=str(err),
            action="Check logs or run with verbose logging.",
        )
        print(error_msg, file=sys.stderr)
        return 1


def download_model(config: Optional[LatchConfig] = None) -> int:
    """Download Julia-1 model weights from Hugging Face."""
    cfg = config or get_config()
    print(f"Downloading Julia-1 model '{cfg.model}' to '{cfg.model_path}'...")
    try:
        from huggingface_hub import snapshot_download
        os.makedirs(cfg.model_path, exist_ok=True)
        snapshot_download(
            repo_id=cfg.model,
            local_dir=cfg.model_path,
            ignore_patterns=["*.msgpack", "*.h5"],
        )
        print(f"[OK] Model successfully downloaded to '{cfg.model_path}'.")
        return 0
    except Exception as err:
        print(f"[ERROR] Failed to download model weights: {err}", file=sys.stderr)
        return 1


def run_install(repo_root: Optional[str] = None, presenter: Optional[Presenter] = None) -> int:
    """Install Latch as a git pre-commit hook."""
    pres = presenter or Presenter()
    try:
        hook_path = install_pre_commit_hook(repo_root=repo_root)
        print("[OK] Latch pre-commit hook successfully installed at:")
        print(f"     {hook_path}")
        print(f"     Executable interpreter: {sys.executable}")
        return 0
    except HookInstallError as err:
        err_msg = pres.format_error(
            title="Hook Installation Failed",
            error_detail=str(err),
            action="Initialize a git repository ('git init') or run from within your git workspace.",
        )
        print(err_msg, file=sys.stderr)
        return 1
    except Exception as err:
        err_msg = pres.format_error(
            title="Hook Installation Error",
            error_detail=str(err),
            action="Check write permissions for .git/hooks directory.",
        )
        print(err_msg, file=sys.stderr)
        return 1


def run_uninstall(repo_root: Optional[str] = None) -> int:
    """Uninstall Latch git pre-commit hook and restore any previous backup."""
    success = uninstall_pre_commit_hook(repo_root=repo_root)
    if success:
        print("[OK] Latch pre-commit hook successfully uninstalled.")
        return 0
    else:
        print("[INFO] No active Latch pre-commit hook found to uninstall.")
        return 0


def run_benchmark(config: Optional[LatchConfig] = None) -> int:
    """Run benchmark evaluation suite across test fixtures."""
    cfg = config or get_config()
    pres = Presenter()
    from latch.benchmark import BenchmarkError, BenchmarkRunner
    print("Executing Latch Benchmark Evaluation Suite...")
    try:
        runner = BenchmarkRunner(config=cfg)
        report = runner.run()
        print("\n" + report.formatted_summary())
        return 0 if (report.metrics.fnr == 0.0 and report.metrics.total_samples > 0) else 1
    except JuliaEngineError as err:
        err_msg = pres.format_error(
            title="Benchmark Failed - Model Engine Unavailable",
            error_detail=str(err),
            action="Run 'python -m latch.cli download-model' or ensure 'julia' runtime is installed.",
            context="Benchmark evaluation",
        )
        print(err_msg, file=sys.stderr)
        return 1
    except BenchmarkError as err:
        err_msg = pres.format_error(
            title="Benchmark Failed - Fixture Error",
            error_detail=str(err),
            action="Ensure benchmark fixtures exist in config.json 'benchmark_fixtures_dir'.",
            context="Benchmark evaluation",
        )
        print(err_msg, file=sys.stderr)
        return 1
    except Exception as err:
        err_msg = pres.format_error(
            title="Benchmark Failed - Unexpected Error",
            error_detail=str(err),
            action="Check benchmark fixtures and environment configuration.",
            context="Benchmark evaluation",
        )
        print(err_msg, file=sys.stderr)
        return 1


def run_scan(
    path: str = ".",
    threshold: Optional[float] = None,
    ext: Optional[str] = None,
    max_chunk_tokens: Optional[int] = None,
    config: Optional[LatchConfig] = None,
    client: Optional[Any] = None,
    scanner: Optional[Any] = None,
    report_path: Optional[str] = None,
    allowlist_paths: Optional[Sequence[str]] = None,
    ignored_dirs: Optional[Sequence[str]] = None,
) -> int:
    """Scan an entire codebase directory for PII and leaked credentials."""
    cfg = config or get_config()
    pres = Presenter()
    extensions = [e.strip() if e.strip().startswith(".") else f".{e.strip()}" for e in ext.split(",")] if ext else None

    target_abs = os.path.abspath(path)
    print(f"Scanning codebase at '{target_abs}' with Julia-1...")
    try:
        from latch.scanner import Scanner
        scan_engine = scanner or Scanner(
            config=cfg,
            client=client,
            allowlist_paths=allowlist_paths,
            ignored_dirs=ignored_dirs,
        )

        is_daemon = scan_engine.client.is_daemon_alive()
        if is_daemon:
            print(f"[LATCH SCAN] Engine: Warm Daemon (127.0.0.1:{cfg.daemon_port}) [High Throughput]")
        else:
            print("[LATCH SCAN] Engine: In-Process Fallback (Cold Model, ~2s/chunk)")
            print("             Tip: Start the daemon with 'python -m latch.cli daemon start' for up to 10x faster scans.")

        def on_progress(curr: int, tot: int) -> None:
            if sys.stdout.isatty():
                mode_tag = "daemon" if scan_engine.client.last_mode == "daemon" else "in-process"
                print(f"\r  Evaluating chunk {curr}/{tot} [{mode_tag}]...", end="", flush=True)

        report = scan_engine.scan(
            target_dir=path,
            extensions=extensions,
            threshold=threshold,
            max_chunk_tokens=max_chunk_tokens,
            progress_callback=on_progress,
            allowlist_paths=allowlist_paths,
            ignored_dirs=ignored_dirs,
        )

        if sys.stdout.isatty() and report.total_chunks > 0:
            print("\r" + " " * 50 + "\r", end="")

        for leak in report.leaks:
            alert = pres.format_blocked(  # latch:ignore
                file_path=leak.offending_file,
                start_line=leak.start_line,
                end_line=leak.end_line,
                probability=leak.probability,
                threshold=threshold or cfg.pii_threshold,
                snippet=leak.snippet,
                context="Scan",
            )
            print(alert, file=sys.stderr)

        summary = pres.format_scan_summary(
            total_files=report.total_files,
            total_lines=report.total_lines,
            total_chunks=report.total_chunks,
            leaks_count=len(report.leaks),
            latency_ms=report.total_latency_ms,
            mode=report.mode,
            target_dir=report.target_dir,
            errored_chunks=report.errored_chunks,
        )
        print(summary)

        if report.errored_chunks > 0:
            print(
                f"[FAIL-CLOSED] {report.errored_chunks} chunk(s) encountered evaluation or read errors. Failing closed.",
                file=sys.stderr,
            )

        # Save persistent scan reports (markdown and json)
        saved_banner = ""
        try:
            md_path, json_path = report.save_reports(report_path)
            saved_banner = pres.format_report_saved(str(md_path), str(json_path))
        except Exception as err:
            print(f"[WARN] Failed to save scan report: {err}", file=sys.stderr)

        # Output allowlist suggestions if leaks detected
        if not report.is_clean:
            suggestions = report.get_suggested_allowlists()
            if suggestions:
                print(pres.format_whitelist_suggestions(suggestions))

        # Always print the saved report destination as the final output on display
        if saved_banner:
            print(saved_banner)

        return 0 if report.is_clean else 1
    except JuliaEngineError as err:
        err_msg = pres.format_error(  # latch:ignore
            title="Scan Failed - Model Engine Unavailable",
            error_detail=str(err),
            action="Run 'python -m latch.cli download-model' or ensure 'julia' runtime is installed.",
            context="Scan",
        )
        print(err_msg, file=sys.stderr)
        return 1
    except Exception as err:
        err_msg = pres.format_error(  # latch:ignore
            title="Scan Failed - Unexpected Error",
            error_detail=str(err),
            action="Check target path and directory permissions.",
            context="Scan",
        )
        print(err_msg, file=sys.stderr)
        return 1
    finally:
        if "scan_engine" in locals() and hasattr(scan_engine, "client") and hasattr(scan_engine.client, "close"):
            scan_engine.client.close()


def main(args: Optional[list[str]] = None) -> None:
    """CLI argument entry point."""
    parser = argparse.ArgumentParser(
        prog="latch",
        description="Latch: Ultra-fast, 100% local git pre-commit guardrail powered by Julia-1.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: check
    subparsers.add_parser("check", help="Inspect staged changes for PII and leaked credentials")

    # Command: scan
    scan_parser = subparsers.add_parser("scan", help="Scan an entire codebase directory for PII and leaked credentials")
    scan_parser.add_argument("path", nargs="?", default=".", help="Target directory to scan (default: current directory)")
    scan_parser.add_argument("--threshold", type=float, default=None, help="Custom PII threshold (default from config: 0.65)")
    scan_parser.add_argument("--ext", type=str, default=None, help="Comma-separated file extensions to include (e.g. .py,.ts,.js,.json)")
    scan_parser.add_argument("--max-chunk-tokens", type=int, default=None, help="Maximum tokens per chunk (default from config: 750)")
    scan_parser.add_argument("--ignore-dir", action="append", default=[], help="Directory name or pattern to ignore")
    scan_parser.add_argument("--allowlist", action="append", default=[], help="File or path pattern to allowlist")
    scan_parser.add_argument("--report", type=str, default=None, help="Custom output path for scan report (.md and .json)")

    # Command: download-model
    subparsers.add_parser("download-model", help="Download open Julia-1 model weights from Hugging Face")

    # Command: install
    subparsers.add_parser("install", help="Install Latch as a git pre-commit hook")

    # Command: uninstall
    subparsers.add_parser("uninstall", help="Uninstall Latch git pre-commit hook and restore backup")

    # Command: daemon
    daemon_parser = subparsers.add_parser("daemon", help="Manage background warm Julia-1 daemon")
    daemon_parser.add_argument("action", choices=["start", "stop", "status"], help="Daemon action")

    # Command: benchmark
    subparsers.add_parser("benchmark", help="Run benchmark evaluation suite across test fixtures")

    parsed = parser.parse_args(args)

    if parsed.command == "check" or parsed.command is None:
        exit_code = run_check()
        sys.exit(exit_code)
    elif parsed.command == "scan":
        exit_code = run_scan(
            path=parsed.path,
            threshold=parsed.threshold,
            ext=parsed.ext,
            max_chunk_tokens=parsed.max_chunk_tokens,
            report_path=parsed.report,
            allowlist_paths=parsed.allowlist,
            ignored_dirs=parsed.ignore_dir,
        )
        sys.exit(exit_code)
    elif parsed.command == "download-model":
        exit_code = download_model()
        sys.exit(exit_code)
    elif parsed.command == "install":
        exit_code = run_install()
        sys.exit(exit_code)
    elif parsed.command == "uninstall":
        exit_code = run_uninstall()
        sys.exit(exit_code)
    elif parsed.command == "daemon":
        mgr = DaemonManager()
        if parsed.action == "start":
            success = mgr.start_background()
            sys.exit(0 if success else 1)
        elif parsed.action == "stop":
            mgr.stop()
            sys.exit(0)
        elif parsed.action == "status":
            mgr.status()
            sys.exit(0)
    elif parsed.command == "benchmark":
        exit_code = run_benchmark()
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
