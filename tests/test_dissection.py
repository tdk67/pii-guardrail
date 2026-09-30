import pytest
from latch.diff_parser import AddedLine, DiffBatch, DiffParser, bisect_buffer
from latch.dissection import Dissector, DissectionResult
from latch.engine import EvaluationResult


def create_mock_lines(file_path: str, count: int, start_line: int = 1, pii_line: int = -1) -> list[AddedLine]:
    lines = []
    for i in range(count):
        cur_line = start_line + i
        if cur_line == pii_line:
            content = 'customer_phone = "+1-555-0199"'
        else:
            content = f"value_{cur_line} = {cur_line}"
        lines.append(AddedLine(file_path=file_path, line_number=cur_line, content=content))
    return lines


def test_bisect_buffer_multi_file():
    lines1 = create_mock_lines("src/file_a.py", 10)
    lines2 = create_mock_lines("src/file_b.py", 10)
    batch = DiffBatch(batch_id="test", lines=lines1 + lines2, estimated_tokens=100)

    left, right = bisect_buffer(batch)
    assert len(left.lines) == 10
    assert len(right.lines) == 10
    assert left.lines[-1].file_path == "src/file_a.py"
    assert right.lines[0].file_path == "src/file_b.py"


def test_bisect_buffer_single_file():
    lines = create_mock_lines("src/file_a.py", 50)
    batch = DiffBatch(batch_id="test", lines=lines, estimated_tokens=250)

    left, right = bisect_buffer(batch)
    assert len(left.lines) == 25
    assert len(right.lines) == 25
    assert left.lines[0].line_number == 1
    assert left.lines[-1].line_number == 25
    assert right.lines[0].line_number == 26
    assert right.lines[-1].line_number == 50


def test_dissection_isolates_pii_needle():
    # 100 lines total across two files:
    # file_a has 50 clean lines
    # file_b has 50 lines with a PII phone number at line 75
    lines_a = create_mock_lines("src/file_a.py", 50, start_line=1)
    lines_b = create_mock_lines("src/file_b.py", 50, start_line=51, pii_line=75)
    batch = DiffBatch(batch_id="test", lines=lines_a + lines_b, estimated_tokens=500)

    # Mock evaluate function that flags any buffer containing the phone number
    def mock_eval_fn(text: str) -> EvaluationResult:
        if "+1-555-0199" in text:
            return EvaluationResult(probability=0.92, latency_ms=10)
        return EvaluationResult(probability=0.05, latency_ms=10)

    dissector = Dissector(threshold=0.65, window_limit=25, max_depth=10)
    result = dissector.dissect(batch, evaluate_fn=mock_eval_fn)

    assert isinstance(result, DissectionResult)
    assert result.offending_file == "src/file_b.py"
    # The isolated window must be <= 25 lines
    line_span = result.end_line - result.start_line + 1
    assert line_span <= 25
    # The window must contain line 75
    assert result.start_line <= 75 <= result.end_line
    assert "+1-555-0199" in result.snippet
    assert result.probability >= 0.65


def test_dissection_conservative_fallback_on_split_boundary():
    # If splitting a buffer creates two halves where NEITHER triggers threshold
    # (e.g. multi-line address or key split right at midpoint),
    # the dissector must conservatively return the parent window.
    lines = create_mock_lines("src/split_secret.py", 40)
    batch = DiffBatch(batch_id="test", lines=lines, estimated_tokens=200)

    eval_calls = []

    def mock_boundary_eval_fn(text: str) -> EvaluationResult:
        eval_calls.append(text)
        # Root buffer triggers
        if len(eval_calls) == 1:
            return EvaluationResult(probability=0.88, latency_ms=10)
        # Both child halves appear clean (simulating boundary split loss)
        return EvaluationResult(probability=0.40, latency_ms=10)

    dissector = Dissector(threshold=0.65, window_limit=25, max_depth=10)
    result = dissector.dissect(batch, evaluate_fn=mock_boundary_eval_fn)

    # Conservative fallback must return parent window rather than none
    assert result.offending_file == "src/split_secret.py"
    assert result.start_line == 1
    assert result.end_line == 40
    assert result.probability == 0.88


def test_dissection_bypasses_initial_eval_when_probability_provided():
    lines = create_mock_lines("src/single.py", 10)
    batch = DiffBatch(batch_id="test", lines=lines, estimated_tokens=50)

    call_count = 0

    def mock_eval_fn(text: str) -> EvaluationResult:
        nonlocal call_count
        call_count += 1
        return EvaluationResult(probability=0.85, latency_ms=5)

    dissector = Dissector(threshold=0.35, window_limit=25)
    result = dissector.dissect(batch, evaluate_fn=mock_eval_fn, initial_probability=0.85)

    # Since lines count (10) <= window_limit (25), it should not bisect,
    # and since initial_probability was provided, mock_eval_fn should NEVER be called!
    assert call_count == 0
    assert result.probability == 0.85


def test_dissection_multi_file_fallback_labeling():
    # If dissection halts on a multi-file window, all offending files must be listed
    lines_a = create_mock_lines("src/file_a.py", 10)
    lines_b = create_mock_lines("src/file_b.py", 10)
    batch = DiffBatch(batch_id="test", lines=lines_a + lines_b, estimated_tokens=100)

    # Force immediate conservative fallback (children score below threshold)
    def mock_eval(text: str) -> EvaluationResult:
        return EvaluationResult(probability=0.10, latency_ms=5)

    dissector = Dissector(threshold=0.35, window_limit=5, max_depth=1)
    result = dissector.dissect(batch, evaluate_fn=mock_eval, initial_probability=0.90)

    # Both files must be accurately represented in offending_file
    assert "src/file_a.py" in result.offending_file
    assert "src/file_b.py" in result.offending_file
    assert "--- File:" in result.snippet

