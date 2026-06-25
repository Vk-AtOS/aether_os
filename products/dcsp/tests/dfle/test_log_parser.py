"""Tests for src.dfle.log_parser."""

import pytest

from src.dfle.log_parser import (
    ParsedLog,
    StackFrame,
    StackTrace,
    parse_log,
)


def test_parse_empty() -> None:
    r = parse_log("")
    assert r.raw_content == ""
    assert r.stack_traces == []
    assert r.test_names == []


def test_parse_python_traceback() -> None:
    log = """
Traceback (most recent call last):
  File "src/foo.py", line 10, in process
    result = compute(x)
  File "src/bar.py", line 5, in compute
    return 1 / 0
ZeroDivisionError: division by zero
"""
    r = parse_log(log)
    assert len(r.stack_traces) == 1
    t = r.stack_traces[0]
    assert t.exception_type == "ZeroDivisionError"
    assert t.exception_message == "division by zero"
    assert len(t.frames) == 2
    assert t.frames[0].filename == "src/foo.py"
    assert t.frames[0].line == 10
    assert t.frames[0].function == "process"
    assert t.frames[0].code_snippet == "result = compute(x)"
    assert t.frames[1].filename == "src/bar.py"
    assert t.top_frame == t.frames[0]
    assert t.failure_site == "src/foo.py:10:process"


def test_parse_pytest_failed() -> None:
    log = "FAILED tests/test_service.py::test_create - AssertionError: expected True"
    r = parse_log(log)
    assert r.test_names == ["tests/test_service.py::test_create"]
    assert r.stack_traces
    assert r.stack_traces[0].frames[0].filename == "tests/test_service.py"


def test_parse_pytest_failed_full_id() -> None:
    # Assert full test node ID is extracted even without msg
    log = "FAILED tests/foo.py::test_bar"
    r = parse_log(log)
    assert r.test_names == ["tests/foo.py::test_bar"]


def test_parse_unittest_fail() -> None:
    log = "test_foo ... FAIL\ntest_bar ... ok"
    r = parse_log(log)
    assert "test_foo" in r.test_names


def test_primary_trace() -> None:
    log = """
Traceback (most recent call last):
  File "a.py", line 1, in f
    raise ValueError("bad")
ValueError: bad
"""
    r = parse_log(log)
    assert r.primary_trace is r.stack_traces[0]
    assert r.primary_trace.exception_type == "ValueError"


def test_invalid_input() -> None:
    r = parse_log(None)  # type: ignore[arg-type]
    assert r.errors
    assert r.raw_content == ""
