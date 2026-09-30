"""Command-Line Interface for Latch.

Entry point for pre-commit checks, model downloads, hook installation,
daemon management, and evaluation benchmarks.
"""

from __future__ import annotations
import argparse
import os
import sys
from latch.client import Client
from latch.config import ConfigError, LatchConfig, get_config
from latch.daemon import DaemonManager
from latch.diff_parser import DiffParser, DiffParserError
from latch.dissection import Dissector
from latch.engine import EvaluationResult, JuliaEngine, JuliaEngineError
from latch.hook import HookInstallError, install_pre_commit_hook
from latch.presenter import Presenter


def run_check(
    config: Optional[LatchConfig] = None,
    parser: Optional[DiffParser] = None,
    engine: Optional[JuliaEngine] = None,
    presenter: Optional[Presenter] = None,
) -> int:
    """Core pre-commit check command. Returns exit code (0 = clean, 1 = blocked/error)."""
    cfg = config or get_config()
    pres = presenter or Presenter()
    pars = parser or DiffParser(max_chunk_tokens=cfg.max_chunk_tokens)

    try:
        # Pre-flight check & staged diff extraction
        added_lines = pars.get_staged_added_lines()
        if not added_lines:
            # Pure deletions, binary files, or empty diffs bypass inspection instantly
            return 0

        # Pack into buffers
        batches = pars.pack_into_batches(added_lines)
        if not batches:
            return 0

        # Two-tier runner: routes to warm daemon (sub-50ms) or falls back in-process
        client = Client(cfg, in_process_engine=engine)

        # Evaluate each batch
        for batch in batches:
            state_text = batch.formatted_text()
            eval_result = client.evaluate(state_text, request_id=batch.batch_id)

            if not eval_result.is_clean(cfg.pii_threshold):
                # PII or credentials detected: run binary dissection localization
                dissector = Dissector(
                    threshold=cfg.pii_threshold,
                    window_limit=cfg.localization_window_lines,
                    max_depth=cfg.max_dissection_depth,
                )
                dissect_res = dissector.dissect(
                    batch,
                    evaluate_fn=lambda txt: client.evaluate(txt, request_id=batch.batch_id),
                )

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
        clean_msg = pres.format_clean(latency_ms=eval_result.latency_ms if 'eval_result' in locals() else 0)
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
            local_dir_use_symlinks=False,
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


def run_benchmark(config: Optional[LatchConfig] = None) -> int:
    """Run benchmark evaluation suite across test fixtures."""
    cfg = config or get_config()
    from latch.benchmark import BenchmarkRunner
    print("Executing Latch Benchmark Evaluation Suite...")
    runner = BenchmarkRunner(config=cfg)
    report = runner.run()
    print("\n" + report.formatted_summary())
    return 0 if report.metrics.fnr == 0.0 else 1


def main(args: Optional[list[str]] = None) -> None:
    """CLI argument entry point."""
    parser = argparse.ArgumentParser(
        prog="latch",
        description="Latch: Ultra-fast, 100% local git pre-commit guardrail powered by Julia-1.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: check
    subparsers.add_parser("check", help="Inspect staged changes for PII and leaked credentials")

    # Command: download-model
    subparsers.add_parser("download-model", help="Download open Julia-1 model weights from Hugging Face")

    # Command: install
    subparsers.add_parser("install", help="Install Latch as a git pre-commit hook")

    # Command: daemon
    daemon_parser = subparsers.add_parser("daemon", help="Manage background warm Julia-1 daemon")
    daemon_parser.add_argument("action", choices=["start", "stop", "status"], help="Daemon action")

    # Command: benchmark
    subparsers.add_parser("benchmark", help="Run benchmark evaluation suite across test fixtures")

    parsed = parser.parse_args(args)

    if parsed.command == "check" or parsed.command is None:
        exit_code = run_check()
        sys.exit(exit_code)
    elif parsed.command == "download-model":
        exit_code = download_model()
        sys.exit(exit_code)
    elif parsed.command == "install":
        exit_code = run_install()
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
