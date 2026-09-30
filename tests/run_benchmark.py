"""Benchmark entry script for model evaluation.

Runs the complete Latch accuracy, resilience, and latency evaluation suite.
"""

from __future__ import annotations
import sys
from latch.benchmark import BenchmarkRunner
from latch.config import get_config


def main() -> int:
    config = get_config()
    print("Initializing Latch Benchmark Evaluation Suite...")
    runner = BenchmarkRunner(config=config)
    report = runner.run()
    print("\n" + report.formatted_summary())

    # Strict acceptance criteria: FNR must be 0.0% (no leaked secrets missed)
    if report.metrics.fnr > 0.0:
        print(f"\n[ALERT] Benchmark failed safety gate: FNR is {report.metrics.fnr * 100:.1f}% (must be 0.0%)", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
