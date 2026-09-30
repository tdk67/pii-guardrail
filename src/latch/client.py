"""Fast client and two-tier fallback orchestrator for Latch.

Coordinates evaluation between the warm background daemon (sub-50ms IPC)
and in-process evaluation (cold-start fallback).
"""

from __future__ import annotations
import json
import socket
import urllib.error
import urllib.request
from typing import Optional
from latch.config import LatchConfig, get_config
from latch.engine import EvaluationResult, JuliaEngine


class Client:
    """Orchestrates evaluation requests through daemon or in-process fallback."""

    def __init__(
        self,
        config: Optional[LatchConfig] = None,
        in_process_engine: Optional[JuliaEngine] = None,
    ) -> None:
        self.config = config or get_config()
        self._in_process_engine = in_process_engine
        self.last_mode: str = "in_process"

    def _get_in_process_engine(self) -> JuliaEngine:
        if self._in_process_engine is None:
            self._in_process_engine = JuliaEngine(self.config)
        return self._in_process_engine

    def is_daemon_alive(self) -> bool:
        """Fast HTTP probe to check if the daemon is warm and listening."""
        timeout_sec = self.config.daemon_probe_timeout_ms / 1000.0
        url = f"http://127.0.0.1:{self.config.daemon_port}/v1/health"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("status") == "ready"
        except (urllib.error.URLError, TimeoutError, OSError, ConnectionResetError):
            return False

        return False

    def evaluate(self, state: str, request_id: str = "") -> EvaluationResult:
        """Evaluates state string via daemon IPC if available, otherwise in-process."""
        if self.is_daemon_alive():
            try:
                result = self._evaluate_via_daemon(state, request_id=request_id)
                self.last_mode = "daemon"
                return result
            except Exception:
                # If daemon fails mid-request, gracefully fall back in-process
                pass

        # Cold-start in-process fallback
        self.last_mode = "in_process"
        engine = self._get_in_process_engine()
        return engine.evaluate(state, request_id=request_id)

    def _evaluate_via_daemon(self, state: str, request_id: str = "") -> EvaluationResult:
        """Send POST request to daemon IPC endpoint."""
        url = f"http://127.0.0.1:{self.config.daemon_port}/v1/evaluate"
        payload = json.dumps({"state": state, "request_id": request_id}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return EvaluationResult(
            probability=float(data.get("probability", 1.0)),
            latency_ms=int(data.get("latency_ms", 0)),
            request_id=str(data.get("request_id", "")),
            error=data.get("error"),
        )
