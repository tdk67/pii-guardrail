import os
import json
import pytest
from latch.config import ConfigManager, LatchConfig, ConfigError


def test_load_default_config(tmp_path):
    config_file = tmp_path / "config.json"
    data = {
        "config_version": "1.0",
        "model": "SupersonicLabs/Julia-1",
        "model_path": "./models/julia-1",
        "model_max_context_tokens": 8192,
        "pii_threshold": 0.65,
        "max_chunk_tokens": 750,
        "max_dissection_depth": 15,
        "localization_window_lines": 25,
        "daemon_port": 5138,
        "daemon_probe_timeout_ms": 50,
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    mgr = ConfigManager(str(config_file))
    cfg = mgr.load()
    assert cfg.model == "SupersonicLabs/Julia-1"
    assert cfg.pii_threshold == 0.65
    assert cfg.max_chunk_tokens == 750
    assert cfg.daemon_port == 5138


def test_config_missing_file_raises_error():
    mgr = ConfigManager("/nonexistent/path/config.json")
    with pytest.raises(ConfigError) as excinfo:
        mgr.load()
    assert "not found" in str(excinfo.value).lower()


def test_config_invalid_threshold_rejected(tmp_path):
    config_file = tmp_path / "config.json"
    data = {
        "config_version": "1.0",
        "pii_threshold": 1.5,  # Invalid: must be between 0.0 and 1.0
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    mgr = ConfigManager(str(config_file))
    with pytest.raises(ConfigError) as excinfo:
        mgr.load()
    assert "threshold" in str(excinfo.value).lower()


def test_config_max_chunk_exceeds_context_rejected(tmp_path):
    config_file = tmp_path / "config.json"
    data = {
        "config_version": "1.0",
        "model_max_context_tokens": 1000,
        "max_chunk_tokens": 2000,  # Invalid: cannot exceed context
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    mgr = ConfigManager(str(config_file))
    with pytest.raises(ConfigError) as excinfo:
        mgr.load()
    assert "max_chunk_tokens" in str(excinfo.value).lower()


def test_config_unknown_key_rejected(tmp_path):
    config_file = tmp_path / "config.json"
    data = {
        "config_version": "1.0",
        "unrecognized_custom_field": "exploit",
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    mgr = ConfigManager(str(config_file))
    with pytest.raises(ConfigError) as excinfo:
        mgr.load()
    assert "unknown configuration parameter" in str(excinfo.value).lower()


def test_config_invalid_port_rejected(tmp_path):
    config_file = tmp_path / "config.json"
    data = {
        "config_version": "1.0",
        "daemon_port": 80,  # Invalid: privileged port < 1024
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    mgr = ConfigManager(str(config_file))
    with pytest.raises(ConfigError) as excinfo:
        mgr.load()
    assert "daemon_port" in str(excinfo.value).lower()
