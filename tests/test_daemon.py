import json
import threading
import time
import urllib.error
import urllib.request
import pytest
from latch.config import LatchConfig
from latch.daemon import DaemonServer, DaemonManager
from latch.engine import EvaluationResult


class MockEngine:
    def __init__(self):
        self.call_count = 0

    def evaluate(self, state: str, request_id: str = "") -> EvaluationResult:
        self.call_count += 1
        if "leak" in state.lower():
            return EvaluationResult(probability=0.91, latency_ms=12, request_id=request_id)
        return EvaluationResult(probability=0.08, latency_ms=10, request_id=request_id)


@pytest.fixture
def test_server(tmp_path):
    token_file = str(tmp_path / "daemon.token")
    cfg = LatchConfig(daemon_port=5149)  # Use distinct test port
    mock_engine = MockEngine()
    server = DaemonServer(cfg, engine=mock_engine, token_file=token_file)
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


def test_daemon_metrics_and_stats_endpoints(test_server):
    cfg, _, server = test_server

    # 1. Unauthenticated requests must receive 401
    for path in ("/metrics", "/v1/stats", "/dashboard"):
        url = f"http://127.0.0.1:{cfg.daemon_port}{path}"
        req_unauth = urllib.request.Request(url, method="GET")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req_unauth, timeout=1.0)
        assert excinfo.value.code == 401
        assert "Content-Length" in excinfo.value.headers

    # 2. Prometheus /metrics with token header
    metrics_url = f"http://127.0.0.1:{cfg.daemon_port}/metrics"
    req_m = urllib.request.Request(metrics_url, headers={"X-Latch-Token": server.token}, method="GET")
    with urllib.request.urlopen(req_m, timeout=1.0) as resp:
        text = resp.read().decode("utf-8")
    assert "latch_daemon_uptime_seconds" in text
    assert "latch_daemon_requests_total" in text

    # 3. JSON /v1/stats with query param token
    stats_url = f"http://127.0.0.1:{cfg.daemon_port}/v1/stats?token={server.token}"
    req_s = urllib.request.Request(stats_url, method="GET")
    with urllib.request.urlopen(req_s, timeout=1.0) as resp:
        stats = json.loads(resp.read().decode("utf-8"))
    assert "uptime_seconds" in stats
    assert "total_requests" in stats

    # 4. HTML /dashboard with query param token
    dash_url = f"http://127.0.0.1:{cfg.daemon_port}/dashboard?token={server.token}"
    req_d = urllib.request.Request(dash_url, method="GET")
    with urllib.request.urlopen(req_d, timeout=1.0) as resp:
        html = resp.read().decode("utf-8")
    assert "<title>Latch Daemon" in html


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
