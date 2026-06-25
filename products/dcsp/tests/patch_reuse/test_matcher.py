"""Tests for src.patch_reuse.matcher."""

from src.patch_reuse.fingerprint import FailureFingerprint
from src.patch_reuse.matcher import MatchResult, match


def test_exact_match() -> None:
    fp = FailureFingerprint(
        error_type="ValueError",
        stack_trace_pattern="a:1:x|b:2:y",
        failing_test="tests/test_a.py",
        target_module="a.py:1:x",
        fingerprint_hash="h1",
    )
    recs = [
        {
            "fingerprint_hash": "h1",
            "error_type": "ValueError",
            "stack_trace_pattern": "a:1:x|b:2:y",
            "target_module": "a.py:1:x",
            "patch_diff": "--- patch content",
            "success_rate": 1.0,
        }
    ]
    r = match(fp, recs)
    assert r.matched
    assert r.confidence == 1.0
    assert r.match_type == "exact"
    assert "patch" in r.patch_diff


def test_fuzzy_match_above_threshold() -> None:
    fp = FailureFingerprint(
        error_type="ValueError",
        stack_trace_pattern="a:1:x|b:2:y",
        failing_test="t",
        target_module="a.py:1:x",
        fingerprint_hash="nonexistent",
    )
    recs = [
        {
            "fingerprint_hash": "other",
            "error_type": "ValueError",
            "stack_trace_pattern": "a:1:x|b:2:y",
            "target_module": "a.py:1:x",
            "patch_diff": "fuzzy",
            "success_rate": 0.9,
        }
    ]
    r = match(fp, recs)
    assert r.matched
    assert r.match_type == "fuzzy"
    assert r.confidence > 0.85


def test_no_fuzzy_match_below_threshold() -> None:
    fp = FailureFingerprint(
        error_type="TypeError",
        stack_trace_pattern="x:1:a|y:2:b",
        failing_test="t",
        target_module="z.py:10:c",
        fingerprint_hash="x",
    )
    recs = [
        {
            "fingerprint_hash": "other",
            "error_type": "ValueError",
            "stack_trace_pattern": "p:1:q",
            "target_module": "r.py:5:s",
            "patch_diff": "diff",
            "success_rate": 0.5,
        }
    ]
    r = match(fp, recs)
    assert not r.matched
    assert r.match_type == "none"
    assert r.confidence == 0.0


def test_no_match_empty_records() -> None:
    fp = FailureFingerprint(
        error_type="X", stack_trace_pattern="", failing_test="", target_module="", fingerprint_hash="h"
    )
    r = match(fp, [])
    assert not r.matched
    assert r.match_type == "none"
    assert r.patch_diff == ""
