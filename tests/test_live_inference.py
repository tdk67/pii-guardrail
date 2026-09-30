import pytest
from latch.config import get_config
from latch.engine import JuliaEngine
from latch.prompt import StateBuilder


@pytest.mark.slow
def test_live_julia_engine_inference():
    cfg = get_config()
    engine = JuliaEngine(cfg)
    engine.load()
    state_builder = StateBuilder(cfg)

    # Integrity verification: model must be genuine Julia runtime, NEVER a dict or mock fallback
    assert engine._model is not None, "Model was not loaded"
    assert not isinstance(engine._model, dict), "Model cannot be a fallback dictionary"
    assert hasattr(engine._model, "predict"), "Model must implement .predict()"
    assert "julia" in type(engine._model).__module__.lower(), (
        f"Expected real julia package, got {type(engine._model).__module__}"
    )
    
    # 1. Clean code diff: computational algorithm
    clean_diff = """=== File: src/numerical.py ===
+ def binary_search(arr: list[int], target: int) -> int:
+     low, high = 0, len(arr) - 1
+     while low <= high:
+         mid = (low + high) // 2
+         if arr[mid] == target:
+             return mid
+         elif arr[mid] < target:
+             low = mid + 1
+         else:
+             high = mid - 1
+     return -1
"""
    clean_state = state_builder.build(clean_diff)
    clean_result = engine.evaluate(clean_state)
    print(f"\n[EVAL] Clean diff: P={clean_result.probability:.4f} Latency={clean_result.latency_ms}ms")
    assert clean_result.probability < cfg.pii_threshold
    assert clean_result.is_clean(cfg.pii_threshold) is True

    # 2. Leaked credentials: live Stripe secret token and production database password
    leak_diff = """=== File: src/config.py ===
+ DB_USER = "prod_admin"
+ DB_PASS = "Sup3rS3cr3tP@ssw0rd!2026"
+ STRIPE_SECRET_KEY = "sk-live-99283819284729104"
"""
    leak_state = state_builder.build(leak_diff)
    leak_result = engine.evaluate(leak_state)
    print(f"[EVAL] Leak diff: P={leak_result.probability:.4f} Latency={leak_result.latency_ms}ms")
    assert leak_result.probability >= cfg.pii_threshold
    assert leak_result.is_clean(cfg.pii_threshold) is False
