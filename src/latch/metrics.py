"""Observability, fine-grained phase profiling, and Prometheus metrics for Latch.

Tracks request latencies broken down into distinct pipeline stages:
- Tokenization
- Tensor collation and packing
- Neural model forward pass (PyTorch CPU execution)
- Scoring and softmax post-processing
- IPC serialization and transport

Exposes both Prometheus /metrics format and JSON /v1/stats.
"""

from __future__ import annotations
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


@dataclass
class PhaseTimings:
    """Latency breakdown of an evaluation request in milliseconds."""
    request_id: str
    tokens: int
    read_ms: float = 0.0
    tokenize_ms: float = 0.0
    prep_ms: float = 0.0
    forward_ms: float = 0.0
    scoring_ms: float = 0.0
    write_ms: float = 0.0
    total_ms: float = 0.0
    probability: float = 0.0
    status_code: int = 200
    timestamp: float = field(default_factory=time.time)


class DaemonMetricsTracker:
    """Thread-safe sliding-window metrics aggregator and Prometheus exporter."""

    def __init__(self, window_size: int = 1000) -> None:
        self.window_size = window_size
        self._lock = threading.Lock()
        self._history: Deque[PhaseTimings] = deque(maxlen=window_size)
        self.total_requests = 0
        self.total_tokens = 0
        self.total_errors = 0
        self.start_time = time.time()

        # Cache hit/miss counters
        self.token_cache_hits = 0
        self.token_cache_misses = 0
        self.encoding_cache_hits = 0
        self.encoding_cache_misses = 0

    def record(self, timing: PhaseTimings) -> None:
        """Record a completed request's phase timings."""
        with self._lock:
            self._history.append(timing)
            self.total_requests += 1
            self.total_tokens += timing.tokens
            if timing.status_code >= 400:
                self.total_errors += 1

    def record_cache_event(self, cache_name: str, hit: bool) -> None:
        """Increment cache hit/miss statistics."""
        with self._lock:
            if cache_name == "token":
                if hit:
                    self.token_cache_hits += 1
                else:
                    self.token_cache_misses += 1
            elif cache_name == "encoding":
                if hit:
                    self.encoding_cache_hits += 1
                else:
                    self.encoding_cache_misses += 1

    def get_summary(self) -> Dict[str, Any]:
        """Compute rolling percentiles (p50, p90, p99, min, max, avg) across tracked phases."""
        with self._lock:
            history = list(self._history)
            uptime = max(0.001, time.time() - self.start_time)
            total_reqs = self.total_requests
            total_tokens = self.total_tokens
            errors = self.total_errors

        if not history:
            return {
                "uptime_seconds": round(uptime, 1),
                "total_requests": total_reqs,
                "total_tokens": total_tokens,
                "total_errors": errors,
                "throughput_reqs_per_sec": round(total_reqs / uptime, 2),
                "throughput_tokens_per_sec": round(total_tokens / uptime, 1),
                "sample_count": 0,
                "phases": {},
            }

        def _stats(values: List[float]) -> Dict[str, float]:
            if not values:
                return {"min": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0, "max": 0.0, "avg": 0.0}
            s = sorted(values)
            n = len(s)
            return {
                "min": round(s[0], 2),
                "p50": round(s[int(n * 0.50)], 2),
                "p90": round(s[min(n - 1, int(n * 0.90))], 2),
                "p99": round(s[min(n - 1, int(n * 0.99))], 2),
                "max": round(s[-1], 2),
                "avg": round(sum(s) / n, 2),
            }

        return {
            "uptime_seconds": round(uptime, 1),
            "total_requests": total_reqs,
            "total_tokens": total_tokens,
            "total_errors": errors,
            "throughput_reqs_per_sec": round(total_reqs / uptime, 2),
            "throughput_tokens_per_sec": round(total_tokens / uptime, 1),
            "sample_count": len(history),
            "phases": {
                "read_ms": _stats([h.read_ms for h in history]),
                "tokenize_ms": _stats([h.tokenize_ms for h in history]),
                "prep_ms": _stats([h.prep_ms for h in history]),
                "forward_ms": _stats([h.forward_ms for h in history]),
                "scoring_ms": _stats([h.scoring_ms for h in history]),
                "write_ms": _stats([h.write_ms for h in history]),
                "total_ms": _stats([h.total_ms for h in history]),
            },
            "recent_requests": [
                {
                    "request_id": h.request_id,
                    "tokens": h.tokens,
                    "forward_ms": round(h.forward_ms, 1),
                    "total_ms": round(h.total_ms, 1),
                    "probability": round(h.probability, 4),
                    "timestamp": round(h.timestamp, 2),
                }
                for h in history[-10:]
            ],
        }

    def to_prometheus(self) -> str:
        """Export metrics formatted for Prometheus scraping."""
        summary = self.get_summary()
        phases = summary.get("phases", {})

        lines = [
            "# HELP latch_daemon_uptime_seconds Daemon process uptime in seconds",
            "# TYPE latch_daemon_uptime_seconds gauge",
            f"latch_daemon_uptime_seconds {summary['uptime_seconds']}",
            "",
            "# HELP latch_daemon_requests_total Total evaluation requests received",
            "# TYPE latch_daemon_requests_total counter",
            f'latch_daemon_requests_total{{status="success"}} {summary["total_requests"] - summary["total_errors"]}',
            f'latch_daemon_requests_total{{status="error"}} {summary["total_errors"]}',
            "",
            "# HELP latch_daemon_tokens_processed_total Total tokens evaluated across all requests",
            "# TYPE latch_daemon_tokens_processed_total counter",
            f"latch_daemon_tokens_processed_total {summary['total_tokens']}",
            "",
            "# HELP latch_daemon_throughput_requests_per_second Current requests per second",
            "# TYPE latch_daemon_throughput_requests_per_second gauge",
            f"latch_daemon_throughput_requests_per_second {summary['throughput_reqs_per_sec']}",
            "",
            "# HELP latch_daemon_throughput_tokens_per_second Current tokens per second",
            "# TYPE latch_daemon_throughput_tokens_per_second gauge",
            f"latch_daemon_throughput_tokens_per_second {summary['throughput_tokens_per_sec']}",
            "",
            "# HELP latch_daemon_cache_events_total Token and encoding cache hit and miss counters",
            "# TYPE latch_daemon_cache_events_total counter",
            f'latch_daemon_cache_events_total{{cache="token",result="hit"}} {self.token_cache_hits}',
            f'latch_daemon_cache_events_total{{cache="token",result="miss"}} {self.token_cache_misses}',
            f'latch_daemon_cache_events_total{{cache="encoding",result="hit"}} {self.encoding_cache_hits}',
            f'latch_daemon_cache_events_total{{cache="encoding",result="miss"}} {self.encoding_cache_misses}',
            "",
            "# HELP latch_daemon_phase_duration_milliseconds Latency percentiles by evaluation phase",
            "# TYPE latch_daemon_phase_duration_milliseconds gauge",
        ]

        for phase_name, stats in phases.items():
            for p_name in ("p50", "p90", "p99", "avg", "max", "min"):
                lines.append(f'latch_daemon_phase_duration_milliseconds{{phase="{phase_name}",stat="{p_name}"}} {stats[p_name]}')

        # Add process memory if psutil is available
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info()
            lines.extend([
                "",
                "# HELP latch_daemon_memory_bytes Resident and virtual memory in bytes",
                "# TYPE latch_daemon_memory_bytes gauge",
                f'latch_daemon_memory_bytes{{type="rss"}} {mem.rss}',
                f'latch_daemon_memory_bytes{{type="vms"}} {mem.vms}',
                "",
                "# HELP latch_daemon_cpu_percent Process CPU utilization percentage",
                "# TYPE latch_daemon_cpu_percent gauge",
                f"latch_daemon_cpu_percent {proc.cpu_percent(interval=None)}",
            ])
        except ImportError:
            pass

        return "\n".join(lines) + "\n"
