"""Tests for src.patch_reuse.fingerprint."""

from src.dfle.log_parser import parse_log
from src.dfle.localizer import localize
from src.dfle.call_graph import CallGraph
from src.patch_reuse.fingerprint import FailureFingerprint, build_fingerprint


def test_build_fingerprint() -> None:
    log = """
Traceback (most recent call last):
  File "tests/test_a.py", line 1, in test_foo
    a()
  File "src/a.py", line 5, in a
    raise ValueError("bad")
ValueError: bad
FAILED tests/test_a.py::test_foo
"""
    parsed = parse_log(log)
    cg = CallGraph()
    candidates = localize(parsed, cg)
    fp = build_fingerprint(candidates[0], parsed)

    assert fp.error_type == "ValueError"
    assert "src/a.py:5:a" in fp.stack_trace_pattern
    assert "tests/test_a" in fp.failing_test
    assert "src/a.py" in fp.target_module
    assert len(fp.fingerprint_hash) == 64
    assert all(c in "0123456789abcdef" for c in fp.fingerprint_hash)


def test_fingerprint_deterministic() -> None:
    log = "Traceback (most recent call last):\n  File \"x.py\", line 1, in f\n    x\nValueError: x"
    parsed = parse_log(log)
    cg = CallGraph()
    candidates = localize(parsed, cg)
    fp1 = build_fingerprint(candidates[0], parsed)
    fp2 = build_fingerprint(candidates[0], parsed)
    assert fp1.fingerprint_hash == fp2.fingerprint_hash


def test_to_dict_from_dict() -> None:
    fp = FailureFingerprint(
        error_type="TypeError",
        stack_trace_pattern="a:1:b",
        failing_test="tests/test_x.py",
        target_module="src/x.py:10:foo",
        fingerprint_hash="a" * 64,
    )
    d = fp.to_dict()
    restored = FailureFingerprint.from_dict(d)
    assert restored.error_type == fp.error_type
    assert restored.fingerprint_hash == fp.fingerprint_hash
