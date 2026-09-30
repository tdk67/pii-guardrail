import json
import os
import threading
import time
import urllib.request
import pytest
from latch.config import LatchConfig
from latch.daemon import DaemonServer, DaemonManager
from latch.engine import EvaluationResult, JuliaEngine


class MockEngine:
    def __init__(self):
        self.call_count = 0

    def evaluate(self, state: str, request_id: str = "") -> EvaluationResult:
        self.call_count += 1
        if "leak" in state.lower():
            return EvaluationResult(probability=0.91, latency_ms=12, request_id=request_id)
        return EvaluationResult(probability=0.08, latency_ms=10, request_id=request_id)


@pytest.fixture
def test_server():
    cfg = LatchConfig(daemon_port=5149)  # Use distinct test port
    mock_engine = MockEngine()
    server = DaemonServer(cfg, engine=mock_engine)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    
    # Wait for server ready
    time.sleep(0.1)
    yield cfg, mock_engine, server
    server.shutdown()
    server.server_close()


def test_daemon_health_endpoint(test_server):
    cfg, _, _ = test_server
    url = f"http://127.0.0.1:{cfg.daemon_port}/v1/health"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=1.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assert data["status"] == "ready"
    assert "Julia-1" in data["model"]


def test_daemon_evaluate_endpoint(test_server):
    cfg, mock_engine, server = test_server
    url = f"http://127.0.0.1:{cfg.daemon_port}/v1/evaluate"
    payload = json.dumps({
        "state": "=== File: src/auth.py ===\n+ const key = 'leak_secret_123';",
        "request_id": "req-123",
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Latch-Token": server.token,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=1.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    
    assert data["request_id"] == "req-123"
    assert data["probability"] == 0.91
    assert data["latency_ms"] == 12
    assert data["error"] is None
    assert mock_engine.call_count == 1


def test_daemon_rejects_missing_or_invalid_token(test_server):
    cfg, _, _ = test_server
    url = f"http://127.0.0.1:{cfg.daemon_port}/v1/evaluate"
    payload = json.dumps({"state": "test", "request_id": "r"}).encode("utf-8")

    # Missing token
    req_missing = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req_missing, timeout=1.0)
    assert excinfo.value.code == 403

    # Invalid token
    req_invalid = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "X-Latch-Token": "bad_token"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req_invalid, timeout=1.0)
    assert excinfo.value.code == 403


def test_daemon_rejects_invalid_host_header(test_server):
    cfg, _, server = test_server
    url = f"http://127.0.0.1:{cfg.daemon_port}/v1/evaluate"
    payload = json.dumps({"state": "test"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Latch-Token": server.token,
            "Host": "evil-attacker.site",
        },
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req, timeout=1.0)
    assert excinfo.value.code == 403


def test_daemon_pid_lifecycle(tmp_path):
    pid_dir = tmp_path / ".latch"
    pid_file = pid_dir / "daemon.pid"
    mgr = DaemonManager(pid_file=str(pid_file))

    assert mgr.is_running() is False
    mgr.save_pid(12345)
    assert mgr.get_pid() == 12345
    mgr.remove_pid()
    assert mgr.get_pid() is None
