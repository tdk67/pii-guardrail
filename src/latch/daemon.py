"""Local HTTP IPC daemon for Latch.
 
Keeps Julia-1 loaded warm in RAM to deliver fast warm git pre-commit evaluations (~1-2s vs cold start).
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
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from latch.config import PACKAGE_ROOT, LatchConfig, get_config
from latch.engine import EvaluationResult, JuliaEngine
from latch.metrics import DaemonMetricsTracker, PhaseTimings


def find_latch_dir() -> str:
    """Resolve .latch directory anchored to current directory or git root."""
    if os.path.isdir(".latch"):
        return os.path.abspath(".latch")
    try:
        import subprocess
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1.0,
        ).strip()
        candidate = os.path.join(git_root, ".latch")
        if os.path.isdir(candidate):
            return candidate
    except Exception:
        pass
    return os.path.abspath(".latch")


def resolve_token_file(pid_file: Optional[str] = None) -> str:
    """Resolve daemon authentication token filepath."""
    if pid_file:
        return os.path.join(os.path.dirname(os.path.abspath(pid_file)), "daemon.token")
    return os.path.join(find_latch_dir(), "daemon.token")


class DaemonRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for daemon IPC endpoints with Host and Token verification."""
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP server access logging to keep console clean."""
        pass

    def _validate_host(self) -> bool:
        """Reject non-loopback Host headers to protect against DNS rebinding and CSRF (S2)."""
        host = self.headers.get("Host", "").split(":")[0].strip().lower()
        return host in ("127.0.0.1", "localhost", "")

    def _validate_token(self) -> bool:
        """Validate ephemeral authentication token (S1). Supports header and ?token= query param."""
        expected = getattr(self.server, "token", None)
        if not expected:
            return True
        auth = self.headers.get("X-Latch-Token", "").strip()
        if not auth and "?" in self.path:
            parsed = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed.query)
            tokens = query_params.get("token", [])
            if tokens:
                auth = tokens[0].strip()
        return secrets.compare_digest(auth, expected)

    def _send_error_500(self, err: Exception) -> None:
        try:
            body = json.dumps({"error": f"Internal Server Error: {err}"}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def do_GET(self) -> None:
        """Handle GET requests (e.g. /v1/health)."""
        if not self._validate_host():
            body = b'{"error": "Forbidden: invalid Host header"}'
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        req_path = urllib.parse.urlparse(self.path).path

        if req_path in ("/metrics", "/v1/stats", "/dashboard"):
            if not self._validate_token():
                body = b'{"error": "Unauthorized: invalid or missing token"}'
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

        if req_path == "/metrics":
            try:
                metrics_tracker = getattr(self.server, "metrics_tracker", None)
                output = metrics_tracker.to_prometheus().encode("utf-8") if metrics_tracker else b"# No metrics tracker\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)
            except Exception as err:
                self._send_error_500(err)
            return

        if req_path == "/v1/stats":
            try:
                metrics_tracker = getattr(self.server, "metrics_tracker", None)
                stats = metrics_tracker.get_summary() if metrics_tracker else {}
                output = json.dumps(stats).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)
            except Exception as err:
                self._send_error_500(err)
            return

        if req_path == "/dashboard":
            try:
                tpl_path = os.path.join(PACKAGE_ROOT, "templates", "dashboard.html")
                if not os.path.exists(tpl_path):
                    tpl_path = os.path.join("templates", "dashboard.html")
                with open(tpl_path, "rb") as f:
                    output = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)
            except Exception as err:
                self._send_error_500(err)
            return

        if req_path == "/v1/health":
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

                response = {
                    "status": "ready",
                    "model": "Julia-1",
                    "authenticated": is_auth,
                    "challenge_response": challenge_resp,
                }
                body = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass
        else:
            try:
                body = b'{"error": "Not Found"}'
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass

    def do_POST(self) -> None:
        """Handle POST requests (/v1/evaluate, /v1/shutdown)."""
        if not self._validate_host():
            body = b'{"error": "Forbidden: invalid Host header"}'
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not self._validate_token():
            body = b'{"error": "Unauthorized: invalid or missing X-Latch-Token"}'
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        t_req_start = time.perf_counter()
        content_length = int(self.headers.get("Content-Length", 0))
        t_read_start = time.perf_counter()
        body = self.rfile.read(content_length)
        t_read_ms = (time.perf_counter() - t_read_start) * 1000

        if self.path == "/v1/evaluate":
            metrics_tracker = getattr(self.server, "metrics_tracker", None)
            if metrics_tracker:
                metrics_tracker.start_request()
            try:
                data = json.loads(body.decode("utf-8"))
                state = data.get("state", "")
                request_id = data.get("request_id", "")
                
                engine: JuliaEngine = self.server.engine  # type: ignore
                result: EvaluationResult = engine.evaluate(state, request_id=request_id)

                response = {
                    "request_id": result.request_id,
                    "probability": result.probability,
                    "latency_ms": result.latency_ms,
                    "timings": getattr(result, "timings", {}),
                    "error": None,
                }
                resp_bytes = json.dumps(response).encode("utf-8")
                t_write_start = time.perf_counter()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
                t_write_ms = (time.perf_counter() - t_write_start) * 1000

                if metrics_tracker:
                    timings = getattr(result, "timings", {})
                    metrics_tracker.record(PhaseTimings(
                        request_id=result.request_id,
                        tokens=timings.get("tokens", len(state.split())),
                        read_ms=round(t_read_ms, 2),
                        tokenize_ms=round(timings.get("tokenize_ms", 0.0), 2),
                        prep_ms=round(timings.get("prep_ms", 0.0), 2),
                        forward_ms=round(timings.get("forward_ms", result.latency_ms), 2),
                        scoring_ms=round(timings.get("scoring_ms", 0.0), 2),
                        write_ms=round(t_write_ms, 2),
                        total_ms=round((time.perf_counter() - t_req_start) * 1000, 2),
                        probability=result.probability,
                        status_code=200,
                    ))
            except Exception as err:
                response = {
                    "request_id": data.get("request_id", "") if "data" in locals() else "",
                    "probability": 1.0,  # Fail-closed on error
                    "latency_ms": 0,
                    "error": str(err),
                }
                resp_bytes = json.dumps(response).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            finally:
                if metrics_tracker:
                    metrics_tracker.end_request()

        elif self.path == "/v1/shutdown":
            body = json.dumps({"status": "shutting_down"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            
            # Asynchronously stop server in separate thread
            import threading
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            body = b'{"error": "Not Found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class DaemonServer(ThreadingHTTPServer):
    """Threading HTTP server instance hosting the warm Julia-1 engine with authentication."""
    daemon_threads = True
    allow_reuse_address = True

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
        self.metrics_tracker = DaemonMetricsTracker()
        server_address = (bind_host, config.daemon_port)
        super().__init__(server_address, DaemonRequestHandler)
        self._save_token()

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
        """Remove daemon token file on shutdown only if it matches our active token."""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r", encoding="utf-8") as f:
                    disk_token = f.read().strip()
                if secrets.compare_digest(disk_token, self.token):
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
        self.pid_file = pid_file or os.path.join(find_latch_dir(), "daemon.pid")
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
            token = self.get_token() or ""
            dash_url = f"http://127.0.0.1:{self.config.daemon_port}/dashboard?token={token}" if token else f"http://127.0.0.1:{self.config.daemon_port}/dashboard"
            print(f"[OK] Latch daemon is already running on port {self.config.daemon_port}.")
            print(f"[INFO] Observability Dashboard: {dash_url}")
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
                token = self.get_token() or ""
                dash_url = f"http://127.0.0.1:{self.config.daemon_port}/dashboard?token={token}" if token else f"http://127.0.0.1:{self.config.daemon_port}/dashboard"
                print(f"[OK] Latch daemon warm and ready on port {self.config.daemon_port} (PID: {proc.pid}).")
                print(f"[INFO] Observability Dashboard: {dash_url}")
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
            with urllib.request.urlopen(req, timeout=1.0):
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
            port_open = False
            try:
                import socket
                with socket.create_connection(("127.0.0.1", self.config.daemon_port), timeout=0.1):
                    port_open = True
            except (OSError, ConnectionRefusedError):
                pass
            if port_open:
                print(f"[WARN] Port {self.config.daemon_port} is listening, but daemon authentication token is missing or invalid.")
                print("       Restart daemon with 'python -m latch.cli daemon stop' and 'start'.")
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
        DaemonManager(cfg).save_pid(os.getpid())
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

