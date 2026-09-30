"""Local HTTP IPC daemon for Latch.

Keeps Julia-1 loaded warm in RAM to deliver sub-50ms git pre-commit evaluations.
Uses standard library http.server.ThreadingHTTPServer to avoid external dependencies.
Bound strictly to 127.0.0.1 for zero-trust local execution.
"""

from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from latch.config import LatchConfig, get_config
from latch.engine import EvaluationResult, JuliaEngine, JuliaEngineError


class DaemonRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for daemon IPC endpoints."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP server access logging to keep console clean."""
        pass

    def do_GET(self) -> None:
        """Handle GET requests (e.g. /v1/health)."""
        if self.path == "/v1/health":
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {"status": "ready", "model": "Julia-1"}
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
    """Threading HTTP server instance hosting the warm Julia-1 engine."""

    def __init__(
        self,
        config: LatchConfig,
        engine: Optional[Any] = None,
        bind_host: str = "127.0.0.1",
    ) -> None:
        self.config = config
        self.engine = engine or JuliaEngine(config)
        server_address = (bind_host, config.daemon_port)
        super().__init__(server_address, DaemonRequestHandler)


class DaemonManager:
    """Manages daemon process lifecycle (start, stop, status)."""

    def __init__(
        self,
        config: Optional[LatchConfig] = None,
        pid_file: Optional[str] = None,
    ) -> None:
        self.config = config or get_config()
        self.pid_file = pid_file or os.path.join(".latch", "daemon.pid")

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

    def is_running(self) -> bool:
        """Probe the daemon health endpoint to verify it is responsive."""
        url = f"http://127.0.0.1:{self.config.daemon_port}/v1/health"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=0.08) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("status") == "ready"
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        return False

    def start_background(self) -> bool:
        """Start daemon in detached background process."""
        if self.is_running():
            print(f"[OK] Latch daemon is already running on port {self.config.daemon_port}.")
            return True

        print(f"Starting Latch daemon on 127.0.0.1:{self.config.daemon_port}...")
        
        # Prefer virtual environment python interpreter if available
        venv_py = os.path.abspath(os.path.join(".venv", "Scripts", "python.exe"))
        python_exe = venv_py if os.path.exists(venv_py) else sys.executable

        # Spawn detached background process
        cmd = [python_exe, "-m", "latch.daemon", "--run-server"]
        
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
        url = f"http://127.0.0.1:{self.config.daemon_port}/v1/shutdown"
        req = urllib.request.Request(url, data=b"{}", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                pass
        except Exception:
            # Fallback to terminating PID directly
            pid = self.get_pid()
            if pid:
                try:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                    else:
                        os.kill(pid, signal.SIGTERM)
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
