"""Fast client and two-tier fallback orchestrator for Latch.

Coordinates evaluation between the warm background daemon (<15ms IPC overhead)
and in-process evaluation (cold-start fallback).
"""

from __future__ import annotations
import http.client
import json
import os
from typing import Any, Optional
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
        prefer_daemon: bool = True,
    ) -> None:
        self.config = config or get_config()
        self._in_process_engine = in_process_engine
        self.token_file = token_file or resolve_token_file()
        self.prefer_daemon = prefer_daemon
        self.last_mode: str = "in_process"
        self.last_daemon_error: Optional[str] = None
        self._http_conn: Optional[http.client.HTTPConnection] = None

    def _get_http_connection(self) -> http.client.HTTPConnection:
        """Obtain or initialize a persistent HTTP connection to the local daemon."""
        if self._http_conn is None:
            self._http_conn = http.client.HTTPConnection(
                "127.0.0.1",
                self.config.daemon_port,
                timeout=self.config.daemon_eval_timeout_sec,
            )
        return self._http_conn

    def _close_http_connection(self) -> None:
        """Close persistent HTTP connection socket if open."""
        if self._http_conn is not None:
            try:
                self._http_conn.close()
            except Exception:
                pass
            self._http_conn = None

    def close(self) -> None:
        """Clean up active sockets and connections."""
        self._close_http_connection()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

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
        if not self.prefer_daemon:
            return False
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
                self._close_http_connection()

        # Cold-start in-process fallback
        self.last_mode = "in_process"
        engine = self._get_in_process_engine()
        return engine.evaluate(state, request_id=request_id)

    def _evaluate_via_daemon(self, state: str, request_id: str = "") -> EvaluationResult:
        """Send POST request to daemon IPC endpoint with authentication and connection reuse."""
        import http.client
        payload = json.dumps({"state": state, "request_id": request_id}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "Connection": "keep-alive",
        }
        token = self._get_daemon_token()  # latch:ignore
        if token:
            headers["X-Latch-Token"] = token  # latch:ignore

        def _do_request(conn: http.client.HTTPConnection) -> dict:  # latch:ignore
            conn.request("POST", "/v1/evaluate", body=payload, headers=headers)  # latch:ignore
            resp = conn.getresponse()  # latch:ignore
            raw = resp.read()  # latch:ignore
            return json.loads(raw.decode("utf-8"))  # latch:ignore

        conn = self._get_http_connection()  # latch:ignore
        try:  # latch:ignore
            data = _do_request(conn)  # latch:ignore
        except (http.client.HTTPException, ConnectionResetError, BrokenPipeError, OSError):  # latch:ignore
            # Stale connection on idle socket: reconnect once and retry
            self._close_http_connection()  # latch:ignore
            conn = self._get_http_connection()  # latch:ignore
            data = _do_request(conn)  # latch:ignore

        return EvaluationResult(
            probability=float(data.get("probability", 1.0)),
            latency_ms=int(data.get("latency_ms", 0)),
            request_id=str(data.get("request_id", "")),
            error=data.get("error"),
        )

