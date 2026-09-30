"""Local HTTP IPC daemon for Latch.

Keeps Julia-1 loaded warm in RAM to deliver sub-50ms git pre-commit evaluations.
Uses standard library http.server.ThreadingHTTPServer to avoid external dependencies.
Bound strictly to 127.0.0.1 for zero-trust local execution.
"""

from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from latch.config import LatchConfig, get_config
from latch.engine import EvaluationResult, JuliaEngine


def resolve_token_file(pid_file: Optional[str] = None) -> str:
    """Resolve daemon authentication token filepath."""
    if pid_file:
        return os.path.join(os.path.dirname(os.path.abspath(pid_file)), "daemon.token")
    return os.path.join(".latch", "daemon.token")


class DaemonRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for daemon IPC endpoints with Host and Token verification."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP server access logging to keep console clean."""
        pass

    def _validate_host(self) -> bool:
        """Reject non-loopback Host headers to protect against DNS rebinding and CSRF (S2)."""
        host = self.headers.get("Host", "").split(":")[0].strip().lower()
        return host in ("127.0.0.1", "localhost", "")

    def _validate_token(self) -> bool:
        """Validate ephemeral authentication token (S1)."""
        expected = getattr(self.server, "token", None)
        if not expected:
            return True
        auth = self.headers.get("X-Latch-Token", "").strip()
        return secrets.compare_digest(auth, expected)

    def do_GET(self) -> None:
        """Handle GET requests (e.g. /v1/health)."""
        if not self._validate_host():
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Forbidden: invalid Host header"}')
            return

        if self.path == "/v1/health":
            try:
                is_auth = self._validate_token()
                challenge_resp = None
                nonce = self.headers.get("X-Latch-Nonce", "").strip()
                server_token = getattr(self.server, "token", None)
                if is_auth and server_token and nonce:
                    challenge_resp = hmac.new(
                        server_token.encode("utf-8"),
                        nonce.encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {
                    "status": "ready",
                    "model": "Julia-1",
                    "authenticated": is_auth,
                    "challenge_response": challenge_resp,
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass
        else:
            try:
                self.send_response(404)
                self.end_headers()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass

    def do_POST(self) -> None:
        """Handle POST requests (/v1/evaluate, /v1/shutdown)."""
        if not self._validate_host():
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Forbidden: invalid Host header"}')
            return

        if not self._validate_token():
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Unauthorized: invalid or missing X-Latch-Token"}')
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if self.path == "/v1/evaluate":
            try:
                data = json.loads(body.decode("utf-8"))
                state = data.get("state", "")
                request_id = data.get("request_id", "")
                
                engine: JuliaEngine = self.server.engine  # type: ignore
                result: EvaluationResult = engine.evaluate(state, request_id=request_id)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {
                    "request_id": result.request_id,
                    "probability": result.probability,
                    "latency_ms": result.latency_ms,
                    "error": None,
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))
            except Exception as err:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {
                    "request_id": data.get("request_id", "") if "data" in locals() else "",
                    "probability": 1.0,  # Fail-closed on error
                    "latency_ms": 0,
                    "error": str(err),
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))

        elif self.path == "/v1/shutdown":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "shutting_down"}).encode("utf-8"))
            
            # Asynchronously stop server in separate thread
            import threading
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()


class DaemonServer(ThreadingHTTPServer):
    """Threading HTTP server instance hosting the warm Julia-1 engine with authentication."""

    def __init__(
        self,
        config: LatchConfig,
        engine: Optional[Any] = None,
        bind_host: str = "127.0.0.1",
        token: Optional[str] = None,
        token_file: Optional[str] = None,
    ) -> None:
        self.config = config
        self.engine = engine or JuliaEngine(config)
        self.token = token or secrets.token_hex(32)
        self.token_file = token_file or resolve_token_file()
        self._save_token()
        server_address = (bind_host, config.daemon_port)
        super().__init__(server_address, DaemonRequestHandler)

    def _save_token(self) -> None:
        """Write secret token to token_file with restricted permissions."""
        token_dir = os.path.dirname(os.path.abspath(self.token_file))
        os.makedirs(token_dir, exist_ok=True)
        try:
            fd = os.open(self.token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with open(fd, "w", encoding="utf-8") as f:
                f.write(self.token)
        except Exception:
            with open(self.token_file, "w", encoding="utf-8") as f:
                f.write(self.token)

    def server_close(self) -> None:
        """Remove daemon token file on shutdown."""
        try:
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
        except OSError:
            pass
        super().server_close()

def probe_daemon(port: int, token: Optional[str], timeout_ms: int) -> bool:
    """Fast loopback HTTP probe validating daemon readiness and mutual HMAC authentication."""
    if not token:
        # Authentic running daemons always possess an active token.
        return False

    timeout_sec = timeout_ms / 1000.0
    url = f"http://127.0.0.1:{port}/v1/health"
    nonce = secrets.token_hex(16)
    headers = {
        "X-Latch-Token": token,  # latch:ignore
        "X-Latch-Nonce": nonce,
    }

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") != "ready" or data.get("authenticated") is not True:
                    return False

                expected_challenge = hmac.new(  # latch:ignore
                    token.encode("utf-8"),  # latch:ignore
                    nonce.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                challenge_resp = data.get("challenge_response", "")
                return secrets.compare_digest(challenge_resp, expected_challenge)
    except (urllib.error.URLError, TimeoutError, OSError, ConnectionResetError):
        return False

    return False


class DaemonManager:
    """Controls the background daemon lifecycle: start, stop, status."""

    def __init__(
        self,
        config: Optional[LatchConfig] = None,
        pid_file: Optional[str] = None,
    ) -> None:
        self.config = config or get_config()
        self.pid_file = pid_file or os.path.join(".latch", "daemon.pid")
        self.token_file = resolve_token_file(self.pid_file)

    def save_pid(self, pid: int) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.pid_file)), exist_ok=True)
        with open(self.pid_file, "w", encoding="utf-8") as f:
            f.write(str(pid))

    def get_pid(self) -> Optional[int]:
        if not os.path.exists(self.pid_file):
            return None
        try:
            with open(self.pid_file, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (ValueError, OSError):
            return None

    def remove_pid(self) -> None:
        if os.path.exists(self.pid_file):
            try:
                os.remove(self.pid_file)
            except OSError:
                pass
        if os.path.exists(self.token_file):
            try:
                os.remove(self.token_file)
            except OSError:
                pass

    def get_token(self) -> Optional[str]:
        if not os.path.exists(self.token_file):
            return None
        try:
            with open(self.token_file, "r", encoding="utf-8") as f:
                token = f.read().strip()
                return token if token else None
        except OSError:
            return None

    def is_running(self) -> bool:
        """Probe the daemon health endpoint to verify it is responsive and authenticated."""
        return probe_daemon(
            port=self.config.daemon_port,
            token=self.get_token(),
            timeout_ms=self.config.daemon_probe_timeout_ms,
        )

    def start_background(self) -> bool:
        """Start daemon in detached background process."""
        if self.is_running():
            print(f"[OK] Latch daemon is already running on port {self.config.daemon_port}.")
            return True

        print(f"Starting Latch daemon on 127.0.0.1:{self.config.daemon_port}...")
        
        # Cross-platform virtual environment python interpreter discovery
        if sys.platform == "win32":
            venv_py = os.path.abspath(os.path.join(".venv", "Scripts", "python.exe"))
        else:
            venv_py = os.path.abspath(os.path.join(".venv", "bin", "python"))
        python_exe = venv_py if os.path.exists(venv_py) else sys.executable

        # Spawn detached background process
        cmd = [python_exe, "-m", "latch.daemon"]
        
        # Cross-platform detached process flags
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=os.path.abspath("."),
            creationflags=creationflags,
            close_fds=True,
        )
        self.save_pid(proc.pid)

        # Wait up to 30s for the daemon to cold-load weights and become ready
        for _ in range(60):
            time.sleep(0.5)
            if self.is_running():
                print(f"[OK] Latch daemon warm and ready on port {self.config.daemon_port} (PID: {proc.pid}).")
                return True

        print("[ERROR] Daemon started but failed health check within 30 seconds.", file=sys.stderr)
        return False

    def stop(self) -> bool:
        """Stop the running daemon cleanly."""
        was_running = self.is_running()
        pid = self.get_pid()
        if not was_running and not pid:
            print(f"[INFO] Latch daemon is not running on port {self.config.daemon_port}.")
            return True

        url = f"http://127.0.0.1:{self.config.daemon_port}/v1/shutdown"
        headers = {}
        token = self.get_token()
        if token:
            headers["X-Latch-Token"] = token

        req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                pass
        except Exception:
            # Fallback to terminating PID directly
            if pid:
                try:
                    if sys.platform == "win32":
                        # Verify process identity before terminating to protect against PID recycling
                        chk = subprocess.run(
                            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if "python" in chk.stdout.lower():
                            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                    else:
                        # POSIX process identity verification before kill  # latch:ignore
                        chk = subprocess.run(  # latch:ignore
                            ["ps", "-p", str(pid), "-o", "comm="],  # latch:ignore
                            capture_output=True,  # latch:ignore
                            text=True,  # latch:ignore
                            check=False,  # latch:ignore
                        )  # latch:ignore
                        if "python" in chk.stdout.lower():  # latch:ignore
                            os.kill(pid, signal.SIGTERM)  # latch:ignore
                except OSError:
                    pass

        self.remove_pid()
        print(f"[OK] Latch daemon stopped on port {self.config.daemon_port}.")
        return True

    def status(self) -> None:
        """Display daemon status report."""
        if self.is_running():
            pid = self.get_pid()
            print(f"[OK] Latch daemon: RUNNING on 127.0.0.1:{self.config.daemon_port} (PID: {pid or 'active'})")
        else:
            print(f"[INFO] Latch daemon: STOPPED (port {self.config.daemon_port} not responding)")


def run_daemon_process() -> None:
    """Internal entry point executed when running as background daemon."""
    log_path = os.path.join(".latch", "daemon.log")
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
    print(f"\n[DAEMON START] PID: {os.getpid()} Time: {time.asctime()}")

    cfg = get_config()
    try:
        server = DaemonServer(cfg)
        server.engine.load()
        # Warm-up inference: pay one-time lazy torch/tokenizer init costs now so the
        # first real request does not exceed the client evaluation timeout (VPS finding).
        try:
            server.engine.evaluate("=== File: warmup ===\n+ warmup = True", request_id="warmup")
        except Exception as warmup_err:
            print(f"[DAEMON WARN] Warm-up inference failed: {warmup_err}")
        print(f"[DAEMON READY] Warm on 127.0.0.1:{cfg.daemon_port}")
        server.serve_forever()
    except KeyboardInterrupt:
        print("[DAEMON SHUTDOWN] Stopped via keyboard interrupt")
    except Exception as err:
        print(f"[DAEMON FATAL] {err}")
        import traceback
        traceback.print_exc(file=log_file)
    finally:
        if "server" in locals():
            server.server_close()


if __name__ == "__main__":
    run_daemon_process()

