"""Fast client and two-tier fallback orchestrator for Latch.

Coordinates evaluation between the warm background daemon (sub-50ms IPC)
and in-process evaluation (cold-start fallback).
"""

from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.request
from typing import Optional
from latch.config import LatchConfig, get_config
from latch.daemon import probe_daemon, resolve_token_file
from latch.engine import EvaluationResult, JuliaEngine


class Client:
    """Orchestrates evaluation requests through daemon or in-process fallback."""

    def __init__(
        self,
        config: Optional[LatchConfig] = None,
        in_process_engine: Optional[JuliaEngine] = None,
        token_file: Optional[str] = None,
    ) -> None:
        self.config = config or get_config()
        self._in_process_engine = in_process_engine
        self.token_file = token_file or resolve_token_file()
        self.last_mode: str = "in_process"
        self.last_daemon_error: Optional[str] = None

    def _get_in_process_engine(self) -> JuliaEngine:
        if self._in_process_engine is None:
            self._in_process_engine = JuliaEngine(self.config)
        return self._in_process_engine

    def _get_daemon_token(self) -> Optional[str]:
        if not os.path.exists(self.token_file):
            return None
        try:
            with open(self.token_file, "r", encoding="utf-8") as f:
                token = f.read().strip()
                return token if token else None
        except OSError:
            return None

    def is_daemon_alive(self) -> bool:
        """Fast HTTP probe to check if the daemon is warm, listening, and mutually authenticated."""
        return probe_daemon(
            port=self.config.daemon_port,
            token=self._get_daemon_token(),  # latch:ignore
            timeout_ms=self.config.daemon_probe_timeout_ms,
        )

    def evaluate(self, state: str, request_id: str = "") -> EvaluationResult:
        """Evaluates state string via daemon IPC if available, otherwise in-process."""
        if self.is_daemon_alive():
            try:
                result = self._evaluate_via_daemon(state, request_id=request_id)
                self.last_mode = "daemon"
                self.last_daemon_error = None
                return result
            except Exception as err:
                # Daemon failed mid-request: capture diagnostic and fall back in-process
                self.last_daemon_error = str(err)

        # Cold-start in-process fallback
        self.last_mode = "in_process"
        engine = self._get_in_process_engine()
        return engine.evaluate(state, request_id=request_id)

    def _evaluate_via_daemon(self, state: str, request_id: str = "") -> EvaluationResult:
        """Send POST request to daemon IPC endpoint with authentication."""
        url = f"http://127.0.0.1:{self.config.daemon_port}/v1/evaluate"
        payload = json.dumps({"state": state, "request_id": request_id}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        token = self._get_daemon_token()
        if token:
            headers["X-Latch-Token"] = token

        req = urllib.request.Request(
            url,
            data=payload,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.config.daemon_eval_timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return EvaluationResult(
            probability=float(data.get("probability", 1.0)),
            latency_ms=int(data.get("latency_ms", 0)),
            request_id=str(data.get("request_id", "")),
            error=data.get("error"),
        )

