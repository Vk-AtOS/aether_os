"""
Tests for JavaScriptAdapter.
"""

from __future__ import annotations

import pytest
from src.lang.javascript_adapter import JavaScriptAdapter


def test_detects_jest_failure():
    """Test detection of Jest failure."""
    adapter = JavaScriptAdapter()
    log = """
FAIL src/utils/math.test.js
 ● math functions › divide() › should throw on zero

    TypeError: Cannot divide by zero

      at Object.divide (src/utils/math.js:10:15)
"""
    failure = adapter.parse(log)
    assert failure is not None
    assert failure.language == "javascript"
    assert failure.error_type == "TypeError"
    assert failure.failing_file == "src/utils/math.js"
    assert failure.line_number == 10


def test_detects_node_stack_trace():
    """Test detection of standard Node.js stack trace."""
    adapter = JavaScriptAdapter()
    log = """
ReferenceError: x is not defined
    at Object.<anonymous> (/app/index.js:5:1)
    at Module._compile (internal/modules/cjs/loader.js:778:30)
"""
    failure = adapter.parse(log)
    assert failure is not None
    assert failure.error_type == "ReferenceError"
    assert failure.failing_file == "/app/index.js"
    assert failure.line_number == 5


def test_returns_none_for_non_javascript():
    """Test that non-JavaScript logs return None."""
    adapter = JavaScriptAdapter()
    log = "Traceback (most recent call last):\n  File \"a.py\", line 1"
    assert adapter.parse(log) is None
