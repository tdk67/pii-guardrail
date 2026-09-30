import pytest
from unittest.mock import MagicMock, patch
from latch.cli import run_check
from latch.config import LatchConfig
from latch.diff_parser import AddedLine, DiffBatch
from latch.engine import EvaluationResult, JuliaEngineError


def test_run_check_no_additions():
    parser_mock = MagicMock()
    parser_mock.get_staged_added_lines.return_value = []
    
    code = run_check(parser=parser_mock)
    assert code == 0


def test_run_check_clean_staged():
    parser_mock = MagicMock()
    line = AddedLine(file_path="src/math.py", line_number=1, content="def add(a, b): return a + b")
    parser_mock.get_staged_added_lines.return_value = [line]
    parser_mock.pack_into_batches.return_value = [
        DiffBatch(batch_id="test-1", lines=[line], estimated_tokens=15)
    ]
    
    engine_mock = MagicMock()
    engine_mock.evaluate.return_value = EvaluationResult(probability=0.05, latency_ms=20)
    
    code = run_check(parser=parser_mock, engine=engine_mock)
    assert code == 0


def test_run_check_pii_blocked():
    parser_mock = MagicMock()
    line = AddedLine(file_path="src/user.py", line_number=42, content='phone = "+1-555-0199"')
    parser_mock.get_staged_added_lines.return_value = [line]
    parser_mock.pack_into_batches.return_value = [
        DiffBatch(batch_id="test-2", lines=[line], estimated_tokens=15)
    ]
    
    engine_mock = MagicMock()
    engine_mock.evaluate.return_value = EvaluationResult(probability=0.92, latency_ms=25)
    
    code = run_check(parser=parser_mock, engine=engine_mock)
    assert code == 1


def test_run_check_fail_closed_on_engine_error():
    parser_mock = MagicMock()
    line = AddedLine(file_path="src/user.py", line_number=1, content="x = 1")
    parser_mock.get_staged_added_lines.return_value = [line]
    parser_mock.pack_into_batches.return_value = [
        DiffBatch(batch_id="test-3", lines=[line], estimated_tokens=5)
    ]
    
    engine_mock = MagicMock()
    engine_mock.evaluate.side_effect = JuliaEngineError("Weights not found")
    
    code = run_check(parser=parser_mock, engine=engine_mock)
    assert code == 1
