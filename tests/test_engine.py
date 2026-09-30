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
