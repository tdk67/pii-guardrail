import os
import pytest
from latch.config import LatchConfig
from latch.engine import JuliaEngine, JuliaEngineError, EvaluationResult


def test_engine_missing_weights_raises_fail_closed(tmp_path):
    cfg = LatchConfig(
        model_path=str(tmp_path / "nonexistent_model"),
        pii_threshold=0.65,
    )
    engine = JuliaEngine(cfg)
    with pytest.raises(JuliaEngineError) as excinfo:
        engine.evaluate("=== File: test.py ===\n+ const x = 1;")
    assert "not found" in str(excinfo.value).lower() or "missing" in str(excinfo.value).lower()


def test_engine_evaluates_state_structure():
    # Test EvaluationResult dataclass structure
    res = EvaluationResult(probability=0.12, latency_ms=25)
    assert res.probability == 0.12
    assert res.latency_ms == 25
    assert res.is_clean(threshold=0.65) is True

    res_blocked = EvaluationResult(probability=0.88, latency_ms=30)
    assert res_blocked.is_clean(threshold=0.65) is False


def test_engine_fails_loudly_when_julia_import_fails(tmp_path, monkeypatch):
    # Create fake model weights file
    weights_dir = tmp_path / "fake_julia"
    weights_dir.mkdir()
    (weights_dir / "model.safetensors").write_text("fake", encoding="utf-8")

    cfg = LatchConfig(model_path=str(weights_dir))
    engine = JuliaEngine(cfg)

    # Monkeypatch import to simulate julia package missing
    orig_import = __import__

    def mock_import(name, *args, **kwargs):
        if name == "julia":
            raise ImportError("No module named 'julia'")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)

    with pytest.raises(JuliaEngineError) as excinfo:
        engine.load()

    assert "not installed or importable" in str(excinfo.value).lower()
    assert engine._model is None

