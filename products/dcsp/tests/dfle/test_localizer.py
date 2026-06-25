"""Tests for src.dfle.localizer."""

from src.dfle.call_graph import CallGraph
from src.dfle.localizer import RootCauseCandidate, localize
from src.dfle.log_parser import parse_log


def test_localize_ranks_by_stack_depth() -> None:
    log = """
Traceback (most recent call last):
  File "tests/test_a.py", line 1, in test_foo
    a()
  File "src/a.py", line 5, in a
    b()
  File "src/b.py", line 10, in b
    raise ValueError("bad")
ValueError: bad
"""
    parsed = parse_log(log)
    # Empty call graph - no AST proximity, scoring is stack-depth driven
    cg = CallGraph()
    candidates = localize(parsed, cg)
    assert len(candidates) == 3
    # Deepest frame (b) should rank first
    assert candidates[0].target_function == "b"
    assert candidates[0].line_number == 10
    assert candidates[0].target_file == "src/b.py"
    assert candidates[0].confidence_score >= candidates[1].confidence_score
    assert candidates[1].confidence_score >= candidates[2].confidence_score


def test_localize_empty_trace_returns_empty() -> None:
    parsed = parse_log("No traceback here")
    cg = CallGraph()
    assert localize(parsed, cg) == []


def test_root_cause_candidate_fields() -> None:
    c = RootCauseCandidate(
        target_file="src/x.py",
        target_function="foo",
        line_number=42,
        confidence_score=0.8,
        dependency_radius=3,
        affected_tests=["tests/test_x.py"],
    )
    assert c.target_file == "src/x.py"
    assert c.target_function == "foo"
    assert c.line_number == 42
    assert c.confidence_score == 0.8
    assert c.dependency_radius == 3
    assert c.affected_tests == ["tests/test_x.py"]
