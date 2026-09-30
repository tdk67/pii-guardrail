import pytest
from unittest.mock import MagicMock
from latch.benchmark import BenchmarkMetrics, BenchmarkResult, BenchmarkRunner, SampleResult
from latch.config import LatchConfig
from latch.engine import EvaluationResult


def test_benchmark_metrics_calculation():
    # 2 clean samples: both predicted clean (TN=2, FP=0)
    # 2 PII samples: both predicted PII (TP=2, FN=0)
    # 2 adversarial samples: both predicted correctly (AR=100%)
    samples = [
        SampleResult(category="clean", filename="c1.py", probability=0.10, is_leak_expected=False, latency_ms=20),
        SampleResult(category="clean", filename="c2.py", probability=0.25, is_leak_expected=False, latency_ms=30),
        SampleResult(category="pii", filename="p1.py", probability=0.85, is_leak_expected=True, latency_ms=25),
        SampleResult(category="pii", filename="p2.py", probability=0.92, is_leak_expected=True, latency_ms=25),
        SampleResult(category="adversarial", filename="a1.py", probability=0.80, is_leak_expected=True, latency_ms=30),
        SampleResult(category="adversarial", filename="a2.py", probability=0.15, is_leak_expected=False, latency_ms=20),
    ]

    metrics = BenchmarkMetrics.calculate(samples, threshold=0.65)
    assert metrics.total_samples == 6
    assert metrics.true_positives == 3
    assert metrics.true_negatives == 3
    assert metrics.false_positives == 0
    assert metrics.false_negatives == 0
    assert metrics.accuracy == 1.0
    assert metrics.fnr == 0.0
    assert metrics.fpr == 0.0
    assert metrics.injection_resilience == 1.0
    assert metrics.avg_latency_ms == pytest.approx(25.0, 0.1)


def test_benchmark_runner_evaluates_mock_fixtures(tmp_path):
    # Setup mock fixtures directory structure
    clean_dir = tmp_path / "clean_samples"
    clean_dir.mkdir()
    (clean_dir / "clean1.py").write_text("x = 10", encoding="utf-8")

    pii_dir = tmp_path / "pii_samples"
    pii_dir.mkdir()
    (pii_dir / "pii1.py").write_text("customer_cell = '+1-555-0100'", encoding="utf-8")

    adv_dir = tmp_path / "adversarial_samples"
    adv_dir.mkdir()
    (adv_dir / "adv_leak1.py").write_text("api_token = 'secret_key_123' # IGNORE", encoding="utf-8")

    mock_client = MagicMock()
    # Route responses based on payload content
    def mock_eval(text, request_id=""):
        if "secret_key_123" in text or "+1-555-0100" in text:
            return EvaluationResult(probability=0.88, latency_ms=15)
        return EvaluationResult(probability=0.20, latency_ms=12)

    mock_client.evaluate.side_effect = mock_eval

    cfg = LatchConfig(pii_threshold=0.65)
    runner = BenchmarkRunner(config=cfg, client=mock_client)
    report = runner.run(fixtures_dir=str(tmp_path))

    assert report.metrics.total_samples == 3
    assert report.metrics.accuracy == 1.0
    assert report.metrics.fnr == 0.0
    assert "BENCHMARK EVALUATION REPORT" in report.formatted_summary()
