import pytest
from latch.config import get_config
from latch.engine import JuliaEngine


@pytest.mark.slow
def test_live_julia_engine_inference():
    cfg = get_config()
    engine = JuliaEngine(cfg)
    
    # 1. Clean code diff
    clean_diff = """=== File: src/math.py ===
+ def add(a, b):
+     return a + b
"""
    clean_result = engine.evaluate(clean_diff)
    print(f"\n[EVAL] Clean diff: P={clean_result.probability:.4f} Latency={clean_result.latency_ms}ms")
    assert clean_result.probability < cfg.pii_threshold
    assert clean_result.is_clean(cfg.pii_threshold) is True

    # 2. Leaked credentials / PII diff
    leak_diff = """=== File: src/auth.py ===
+ customer_name = "Jane Doe"
+ customer_phone = "+1-555-0199"
+ customer_ssn = "000-12-3456"
"""
    leak_result = engine.evaluate(leak_diff)
    print(f"[EVAL] Leak diff: P={leak_result.probability:.4f} Latency={leak_result.latency_ms}ms")
    assert leak_result.probability >= cfg.pii_threshold
    assert leak_result.is_clean(cfg.pii_threshold) is False
