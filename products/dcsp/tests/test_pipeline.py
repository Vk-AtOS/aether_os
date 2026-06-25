"""
Tests for repair pipeline feedback loop.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from src.pipeline import run_repair, RepairResult


def test_pipeline_uses_memory_on_hit():
    """Test that pipeline returns known fix from memory on fingerprint hit."""
    fp = "stable-fp"
    mock_stored = {
        "patch_diff": "known fix",
        "confidence": 0.9,
        "success_count": 2
    }
    
    with patch("src.pipeline.log_fingerprint", return_value=fp), \
         patch("src.pipeline.GLOBAL_REPAIR_MEMORY") as mock_memory:
        
        mock_memory.lookup.return_value = mock_stored
        
        result = run_repair(
            log_content="error log",
            root_dir="repo",
            historical_records=[],
            ast_index={}
        )
        
        assert result.success is True
        assert result.source == "memory"
        assert result.patch_diff == "known fix"
        assert result.fingerprint == fp
        assert "Reused known fix" in result.explanation


def test_pipeline_records_failure_on_slm_fail():
    """Test that pipeline records failure in memory when SLM fails."""
    fp = "failing-fp"
    
    # Mock log parsing to return traces so it doesn't fail there
    mock_parsed_log = MagicMock()
    mock_parsed_log.stack_traces = [MagicMock()]
    
    with patch("src.pipeline.log_fingerprint", return_value=fp), \
         patch("src.pipeline.GLOBAL_REPAIR_MEMORY") as mock_memory, \
         patch("src.pipeline.parse_log", return_value=mock_parsed_log), \
         patch("src.pipeline.detect_language_adapter"), \
         patch("src.pipeline.localize", return_value=[]): # Fail at localization
        
        mock_memory.lookup.return_value = None
        
        result = run_repair(
            log_content="error log",
            root_dir="repo",
            historical_records=[],
            ast_index={}
        )
        
        assert result.success is False
        mock_memory.record_failure.assert_called_with(fp)


def test_pipeline_uses_prompt_templates():
    """Verify that PromptTemplates.build_prompt is called during SLM repair."""
    with patch("src.pipeline.log_fingerprint"), \
         patch("src.pipeline.GLOBAL_REPAIR_MEMORY") as mock_memory, \
         patch("src.pipeline.parse_log") as mock_parse, \
         patch("src.pipeline.detect_language_adapter"), \
         patch("src.pipeline.localize") as mock_localize, \
         patch("src.pipeline.PromptTemplates.build_prompt") as mock_build, \
         patch("src.slm.bedrock_client.BedrockClient.generate_patch") as mock_gen:
        
        mock_memory.lookup.return_value = None
        
        # Configure parsed_log mock with real strings for build_fingerprint
        mock_parsed = MagicMock()
        mock_trace = MagicMock()
        mock_trace.exception_type = "ValueError"
        mock_parsed.stack_traces = [mock_trace]
        mock_parsed.primary_trace = mock_trace
        mock_parsed.test_names = ["test_foo"]
        mock_parse.return_value = mock_parsed
        
        # Configure top_candidate mock
        mock_cand = MagicMock()
        mock_cand.target_file = "test.py"
        mock_cand.line_number = 10
        mock_cand.target_function = "func"
        mock_cand.confidence_score = 0.8
        mock_localize.return_value = [mock_cand]
        
        mock_build.return_value = ("system", "user")
        mock_gen.return_value = None # End here
        
        run_repair("logs", "root", [], {})
        
        assert mock_build.called
        args, _ = mock_build.call_args
        assert args[0] == "ValueError"


def test_pipeline_validates_patch_with_validator():
    """Verify that PatchValidator is used to validate SLM response."""
    with patch("src.pipeline.log_fingerprint"), \
         patch("src.pipeline.GLOBAL_REPAIR_MEMORY") as mock_memory, \
         patch("src.pipeline.parse_log") as mock_parse, \
         patch("src.pipeline.detect_language_adapter"), \
         patch("src.pipeline.localize") as mock_localize, \
         patch("src.pipeline.PromptTemplates.build_prompt") as mock_build, \
         patch("src.slm.bedrock_client.BedrockClient.generate_patch") as mock_gen, \
         patch("src.pipeline.PatchValidator") as mock_val_class:
        
        mock_memory.lookup.return_value = None
        
        mock_parsed = MagicMock()
        mock_trace = MagicMock()
        mock_trace.exception_type = "ValueError"
        mock_parsed.stack_traces = [mock_trace]
        mock_parsed.primary_trace = mock_trace
        mock_parsed.test_names = ["test_foo"]
        mock_parse.return_value = mock_parsed
        
        mock_cand = MagicMock()
        mock_cand.target_file = "test.py"
        mock_cand.line_number = 10
        mock_cand.target_function = "func"
        mock_cand.confidence_score = 0.8
        mock_localize.return_value = [mock_cand]
        
        mock_build.return_value = ("system", "user")
        mock_gen.return_value = "raw diff"
        
        mock_validator = mock_val_class.return_value
        mock_validator.extract_diff.return_value = "extracted diff"
        mock_validator.is_valid_diff.return_value = False # Force failure
        
        result = run_repair("logs", "root", [], {})
        
        assert result.success is False
        assert "invalid patch format" in result.explanation
        assert mock_validator.is_valid_diff.called
