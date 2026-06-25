"""
Tests for prompt_template.
"""

from __future__ import annotations

import pytest
from src.slm.prompt_template import build_patch_prompt
from src.slm.context_builder import ParsedFailure
from src.dfle.log_parser import StackTrace


def test_prompt_contains_diff_instruction():
    """Verify prompt asks for a unified diff."""
    failure = ParsedFailure(raw_content="...", stack_traces=[StackTrace(exception_type="E", exception_message="M", raw_text="Traceback...")])
    prompt = build_patch_prompt("some context", failure)
    assert "unified diff" in prompt.lower()
    assert "ONLY a unified diff patch" in prompt


def test_prompt_contains_failure_info():
    """Verify prompt includes traceback."""
    failure = ParsedFailure(raw_content="...", stack_traces=[StackTrace(exception_type="ValueError", exception_message="bad", raw_text="Traceback (most recent call last):\n  File \"a.py\", line 1\nValueError: bad")])
    prompt = build_patch_prompt("some context", failure)
    assert "ValueError: bad" in prompt


def test_prompt_within_reasonable_length():
    """Verify prompt isn't ridiculously long."""
    failure = ParsedFailure(raw_content="...", stack_traces=[StackTrace(exception_type="E", exception_message="M", raw_text="Traceback...")])
    prompt = build_patch_prompt("context", failure)
    assert 100 < len(prompt) < 1000
