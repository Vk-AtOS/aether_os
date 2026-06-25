from __future__ import annotations
import pytest
from src.pipeline import run_repair, RepairResult
from src.sandbox.docker_sandbox import DOCKER_AVAILABLE

def test_repair_result_has_sandbox_fields():
    """RepairResult has sandbox fields."""
    r = RepairResult(
        success=True,
        confidence=0.9,
        patch_diff="diff",
        explanation="fixed",
        escalated=False,
        detected_language="python",
        fingerprint="fp",
        slm_generated=False,
        source="memory",
        error_type=None
    )
    assert hasattr(r, "sandbox_validated")
    assert hasattr(r, "sandbox_result")
    assert r.sandbox_validated is False
    assert r.sandbox_result is None

def test_pipeline_sandbox_result_skipped():
    """When Docker unavailable, pipeline sets sandbox_result to skipped."""
    result = run_repair(
        log_content=(
            "AttributeError: 'NoneType' "
            "object has no attribute 'get'"),
        root_dir=".",
        historical_records=[],
        ast_index={}
    )
    assert hasattr(result, "sandbox_result")
    if not DOCKER_AVAILABLE:
        assert result.sandbox_result in ["skipped", None]

def test_sandbox_result_valid_values():
    """sandbox_result is one of valid values."""
    valid = {"passed", "failed", "skipped", None}
    result = run_repair(
        log_content=(
            "ImportError: No module named 'requests'"),
        root_dir=".",
        historical_records=[],
        ast_index={}
    )
    assert result.sandbox_result in valid

def test_repair_result_dataclass_defaults():
    """sandbox fields default correctly."""
    r = RepairResult(
        success=False,
        confidence=0.0,
        patch_diff="",
        explanation="none",
        escalated=True,
        detected_language="python",
        fingerprint="fp",
        slm_generated=False,
        source="memory",
        error_type=None
    )
    assert r.sandbox_validated is False
    assert r.sandbox_result is None
