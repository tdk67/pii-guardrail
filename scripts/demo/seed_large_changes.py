"""Demo Scenario: Seed large clean code changes (multi-chunk, 100+ lines).

Creates demo/stream_accumulator.py with clean, non-sensitive data structures
and metric aggregation algorithms (80+ lines).
Demonstrates that large clean additions pass through Latch without false positives.
"""

from pathlib import Path
import subprocess
import sys


def seed_large_clean_changes() -> None:
    demo_dir = Path("demo")
    demo_dir.mkdir(exist_ok=True)

    target_file = demo_dir / "stream_accumulator.py"
    code = '''"""Data stream transformer and ring buffer accumulator."""
from typing import Any, Callable, Dict, List, Optional


class RingBuffer:
    """Fixed-size circular buffer for high-throughput stream processing."""

    def __init__(self, capacity: int = 500):
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        self.capacity = capacity
        self._buffer: List[Optional[Any]] = [None] * capacity
        self._head = 0
        self._tail = 0
        self._size = 0

    def append(self, item: Any) -> None:
        self._buffer[self._tail] = item
        self._tail = (self._tail + 1) % self.capacity
        if self._size < self.capacity:
            self._size += 1
        else:
            self._head = (self._head + 1) % self.capacity

    def to_list(self) -> List[Any]:
        items: List[Any] = []
        idx = self._head
        for _ in range(self._size):
            val = self._buffer[idx]
            if val is not None:
                items.append(val)
            idx = (idx + 1) % self.capacity
        return items

    @property
    def is_full(self) -> bool:
        return self._size == self.capacity


class MetricAggregator:
    """Computes summary statistics over numeric sequences."""

    @staticmethod
    def moving_average(window_size: int, values: List[float]) -> List[float]:
        if window_size <= 0 or not values:
            return []
        result: List[float] = []
        running_sum = 0.0
        for i, val in enumerate(values):
            running_sum += val
            if i >= window_size:
                running_sum -= values[i - window_size]
                result.append(round(running_sum / window_size, 4))
            elif i == window_size - 1:
                result.append(round(running_sum / window_size, 4))
        return result

    @staticmethod
    def percentile(values: List[float], p: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * (p / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_vals) - 1)
        d0 = sorted_vals[f] * (c - k)
        d1 = sorted_vals[c] * (k - f)
        return round(d0 + d1, 4)
'''

    target_file.write_text(code, encoding="utf-8")
    line_count = len(code.splitlines())
    print(f"[DEMO] Created large clean file: {target_file} ({line_count} lines)")

    res = subprocess.run(["git", "add", str(target_file)], capture_output=True, text=True)
    if res.returncode == 0:
        print("[DEMO] Staged in git: git add demo/stream_accumulator.py")
    else:
        print(f"[DEMO ERROR] Failed to git add: {res.stderr}", file=sys.stderr)


if __name__ == "__main__":
    seed_large_clean_changes()
