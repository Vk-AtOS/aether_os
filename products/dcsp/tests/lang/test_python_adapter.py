"""
Tests for PythonAdapter.
"""

from __future__ import annotations

import pytest
from src.lang.python_adapter import PythonAdapter


def test_detects_python_traceback():
    """Test that Python traceback is detected."""
    adapter = PythonAdapter()
    log = """
Traceback (most recent call last):
  File "app.py", line 10, in main
    result = divide(1, 0)
  File "app.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero
"""
    failure = adapter.parse(log)
    assert failure is not None
    assert failure.language == "python"
    assert failure.error_type == "ZeroDivisionError"


def test_extracts_error_type():
    """Test extraction of error type."""
    adapter = PythonAdapter()
    log = "Traceback (most recent call last):\n  File \"a.py\", line 1\nValueError: invalid value"
    failure = adapter.parse(log)
    assert failure.error_type == "ValueError"
    assert failure.error_message == "invalid value"


def test_extracts_file_and_line():
    """Test extraction of file, line, and function."""
    adapter = PythonAdapter()
    log = """
Traceback (most recent call last):
  File "src/logic.py", line 42, in process_data
    raise TypeError("bad type")
TypeError: bad type
"""
    failure = adapter.parse(log)
    assert failure.failing_file == "src/logic.py"
    assert failure.line_number == 42
    assert failure.failing_function == "process_data"


def test_returns_none_for_non_python():
    """Test that non-Python logs return None."""
    adapter = PythonAdapter()
    log = "Just some random text without traceback"
    assert adapter.parse(log) is None
