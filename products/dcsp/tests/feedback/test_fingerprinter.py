"""
Tests for error fingerprinter.
"""

from __future__ import annotations

import pytest
from src.feedback.fingerprinter import fingerprint


def test_same_error_same_fingerprint():
    """Two logs with same error but different line numbers/paths should have same FP."""
    log1 = """
Traceback (most recent call last):
  File "/home/user/app/logic.py", line 42, in process
    raise ValueError("invalid input")
ValueError: invalid input
"""
    log2 = """
Traceback (most recent call last):
  File "/opt/dcsp/src/utils.py", line 105, in validate
    raise ValueError("invalid input")
ValueError: invalid input
"""
    assert fingerprint(log1) == fingerprint(log2)


def test_different_errors_different_fingerprint():
    """ValueError vs KeyError should have different FPs."""
    log1 = "ValueError: bad value"
    log2 = "KeyError: 'missing_key'"
    assert fingerprint(log1) != fingerprint(log2)


def test_fingerprint_length():
    """FP should be 16 chars."""
    log = "Traceback: Error at line 1"
    result = fingerprint(log)
    assert len(result) == 16


def test_address_stripped():
    """Memory addresses should be normalized."""
    log1 = "Exception at 0x7f3a4b5c: crash"
    log2 = "Exception at 0xDEADBEEF: crash"
    assert fingerprint(log1) == fingerprint(log2)
