import pytest
from latch.presenter import Presenter


def test_format_clean():
    presenter = Presenter()
    out = presenter.format_clean(latency_ms=32)
    assert "✓ Latch: Clean" in out
    assert "32ms" in out


def test_format_blocked():
    presenter = Presenter()
    snippet = '42 | def leak():\n43 |     token = "sk-live-12345"'
    out = presenter.format_blocked(
        file_path="src/auth.py",
        start_line=42,
        end_line=43,
        probability=0.941,
        threshold=0.65,
        snippet=snippet,
    )
    assert "[LATCH BLOCKED]" in out
    assert "src/auth.py" in out
    assert "Lines:  42-43" in out
    assert "0.94" in out
    assert "sk-live-12345" in out


def test_format_error():
    presenter = Presenter()
    out = presenter.format_error(
        title="Model weights not found",
        error_detail="Weights missing at ./models/julia-1",
        action="Run 'latch download-model'",
    )
    assert "[LATCH SYSTEM ERROR]" in out
    assert "Fail-Closed" in out
    assert "Weights missing" in out
    assert "latch download-model" in out
