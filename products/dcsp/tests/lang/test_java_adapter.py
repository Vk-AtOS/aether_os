"""
Tests for JavaAdapter.
"""

from __future__ import annotations

import pytest
from src.lang.java_adapter import JavaAdapter


def test_detects_junit_failure():
    """Test detection of JUnit failure."""
    adapter = JavaAdapter()
    log = """
There was 1 failure:
1) testAdd(com.example.CalculatorTest)
java.lang.AssertionError: expected:<4> but was:<5>
	at org.junit.Assert.fail(Assert.java:88)
	at com.example.Calculator.add(Calculator.java:12)
"""
    failure = adapter.parse(log)
    assert failure is not None
    assert failure.language == "java"
    assert failure.error_type == "java.lang.AssertionError"
    assert failure.failing_file == "Calculator.java"
    assert failure.line_number == 12


def test_detects_exception_in_thread():
    """Test detection of exception in thread."""
    adapter = JavaAdapter()
    log = """
Exception in thread "main" java.lang.NullPointerException: Cannot invoke "String.length()" because "s" is null
	at com.example.Main.main(Main.java:10)
"""
    failure = adapter.parse(log)
    assert failure is not None
    assert failure.error_type == "java.lang.NullPointerException"
    assert failure.failing_file == "Main.java"
    assert failure.line_number == 10


def test_returns_none_for_non_java():
    """Test that non-Java logs return None."""
    adapter = JavaAdapter()
    log = "Traceback (most recent call last):\n  File \"a.py\", line 1"
    assert adapter.parse(log) is None
