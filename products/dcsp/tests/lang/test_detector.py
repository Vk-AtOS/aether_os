"""
Tests for Language detector.
"""

from __future__ import annotations

import pytest
from src.lang.detector import detect_language_adapter


def test_detects_python():
    """Test detection of Python adapter."""
    log = "Traceback (most recent call last):\n  File \"a.py\", line 1\nError"
    adapter = detect_language_adapter(log)
    assert adapter is not None
    assert adapter.language_name == "python"


def test_detects_javascript():
    """Test detection of JavaScript adapter."""
    log = "at Object.<anonymous> (/app/index.js:5:1)"
    adapter = detect_language_adapter(log)
    assert adapter is not None
    assert adapter.language_name == "javascript"


def test_detects_java():
    """Test detection of Java adapter."""
    log = "at com.example.Main.main(Main.java:10)"
    adapter = detect_language_adapter(log)
    assert adapter is not None
    assert adapter.language_name == "java"


def test_returns_none_for_unknown():
    """Test returns None for unrecognized log."""
    log = "Some random build log without failures"
    adapter = detect_language_adapter(log)
    assert adapter is None
