"""
Tests for ContextBuilder.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
from src.slm.context_builder import ContextBuilder, ParsedFailure
from src.dfle.log_parser import StackTrace, StackFrame


def test_context_respects_token_budget():
    """Verify context never exceeds MAX_TOKENS."""
    # Mock index and failure with two functions
    index = {
        "file1.py": {
            "functions": [
                {"name": "func1", "line": 1},
                {"name": "func2", "line": 50}
            ],
            "classes": []
        }
    }
    
    failure = ParsedFailure(
        raw_content="...",
        stack_traces=[
            StackTrace(
                exception_type="Error",
                exception_message="msg",
                frames=[
                    StackFrame(filename="file1.py", line=1, function="func1"),
                    StackFrame(filename="file1.py", line=50, function="func2")
                ]
            )
        ]
    )
    
    # Each function is 40 lines * 20 chars = 800 chars
    source = ("print('1234567890123')\n" * 39 + "print('last')\n") * 2 # 80 lines total
    
    with patch("src.slm.context_builder.Path") as MockPath:
        builder = ContextBuilder()
        builder.MAX_TOKENS = 300  # 1200 chars
        builder.CHARS_PER_TOKEN = 4
        
        mock_file = MockPath.return_value
        MockPath.return_value.__truediv__.return_value = mock_file
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = source
        
        context = builder.build(failure, index)
        
        # Each part is approx 800 (source) + 50 (header) = 850 chars
        # Two parts = 1700 chars > 1200 limit.
        # So only one part should be in context.
        assert len(context) <= 1200
        assert "func1" in context
        assert "func2" not in context


def test_context_includes_relevant_files():
    """Verify failure file appears in context."""
    index = {
        "src/utils.py": {
            "functions": [{"name": "calculate", "line": 2}],
            "classes": []
        }
    }
    
    failure = ParsedFailure(
        raw_content="...",
        stack_traces=[
            StackTrace(
                exception_type="ValueError",
                exception_message="bad value",
                frames=[StackFrame(filename="src/utils.py", line=2, function="calculate")]
            )
        ]
    )
    
    source = "import os\ndef calculate(x):\n    return x / 0"
    
    with patch("src.slm.context_builder.Path") as MockPath:
        builder = ContextBuilder()
        mock_file = MockPath.return_value
        MockPath.return_value.__truediv__.return_value = mock_file
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = source
        
        context = builder.build(failure, index)
        assert "src/utils.py" in context
        assert "calculate" in context
        assert "return x / 0" in context


def test_empty_index_returns_minimal_context():
    """Graceful handling when index is empty."""
    builder = ContextBuilder()
    failure = ParsedFailure(
        raw_content="...",
        stack_traces=[
            StackTrace(
                exception_type="Error",
                exception_message="msg",
                frames=[StackFrame(filename="unknown.py", line=1, function="main")]
            )
        ]
    )
    
    context = builder.build(failure, {})
    assert "No relevant code found" in context
