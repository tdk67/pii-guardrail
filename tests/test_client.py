import json
import threading
import time
import pytest
from unittest.mock import MagicMock
from latch.client import Client
from latch.config import LatchConfig
from latch.daemon import DaemonServer
from latch.engine import EvaluationResult


def test_client_fallback_when_daemon_offline():
    # When daemon is not running on port, client must seamlessly fall back in-process
    cfg = LatchConfig(daemon_port=5999, daemon_probe_timeout_ms=30)
    mock_in_process = MagicMock()
    mock_in_process.evaluate.return_value = EvaluationResult(probability=0.15, latency_ms=10)

    client = Client(config=cfg, in_process_engine=mock_in_process)
    assert client.is_daemon_alive() is False

    result = client.evaluate("=== File: test.py ===\n+ const x = 1;")
    assert result.probability == 0.15
    assert mock_in_process.evaluate.called
    assert client.last_mode == "in_process"


def test_client_routes_to_live_daemon():
    cfg = LatchConfig(daemon_port=5159, daemon_probe_timeout_ms=50)
    mock_engine = MagicMock()
    mock_engine.evaluate.return_value = EvaluationResult(probability=0.93, latency_ms=15, request_id="r1")
    
    server = DaemonServer(cfg, engine=mock_engine)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)

    try:
        client = Client(config=cfg)
        assert client.is_daemon_alive() is True

        result = client.evaluate("=== File: leak.py ===\n+ password = 'abc'", request_id="r1")
        assert result.probability == 0.93
        assert result.latency_ms == 15
        assert client.last_mode == "daemon"
    finally:
        server.shutdown()
        server.server_close()


def test_client_fallback_on_daemon_timeout_or_error():
    """If daemon hangs or errors mid-request, client must catch it and fall back in-process."""
    cfg = LatchConfig(daemon_port=5160, daemon_probe_timeout_ms=50, daemon_eval_timeout_sec=0.1)
    
    mock_in_process = MagicMock()
    mock_in_process.evaluate.return_value = EvaluationResult(probability=0.20, latency_ms=5)

    client = Client(config=cfg, in_process_engine=mock_in_process)
    # Simulate daemon reporting alive, but hanging on evaluate
    client.is_daemon_alive = MagicMock(return_value=True)  # type: ignore
    client._evaluate_via_daemon = MagicMock(side_effect=TimeoutError("Request timed out"))  # type: ignore

    result = client.evaluate("=== File: timeout.py ===\n+ code = 1")
    assert result.probability == 0.20
    assert client.last_mode == "in_process"
    assert mock_in_process.evaluate.called

