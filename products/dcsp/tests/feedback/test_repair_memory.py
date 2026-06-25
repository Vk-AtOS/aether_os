"""
Tests for repair memory.
"""

from __future__ import annotations

import json
import pytest
from src.feedback.repair_memory import RepairMemory


@pytest.fixture
def temp_memory(tmp_path):
    """Provides a RepairMemory instance with a temporary file path."""
    path = tmp_path / "memory.json"
    return RepairMemory(str(path))


def test_lookup_empty(temp_memory):
    """Empty memory should return None."""
    assert temp_memory.lookup("any-fp") is None


def test_record_and_lookup(temp_memory):
    """Recording success should allow subsequent lookup."""
    fp = "abc123"
    temp_memory.record_success(fp, "diff", 0.9, "repo")
    
    entry = temp_memory.lookup(fp)
    assert entry is not None
    assert entry["patch_diff"] == "diff"
    assert entry["success_count"] == 1


def test_success_count_increments(temp_memory):
    """Success count should increment on multiple records."""
    fp = "abc123"
    temp_memory.record_success(fp, "diff1", 0.8, "repo")
    temp_memory.record_success(fp, "diff2", 0.9, "repo")
    
    entry = temp_memory.lookup(fp)
    assert entry["success_count"] == 2
    assert entry["patch_diff"] == "diff2"


def test_record_failure_decrements(temp_memory):
    """Failure should decrement success count."""
    fp = "fail-me"
    temp_memory.record_success(fp, "diff", 0.9, "repo")
    temp_memory.record_success(fp, "diff", 0.9, "repo") # count = 2
    
    temp_memory.record_failure(fp)
    entry = temp_memory.lookup(fp)
    assert entry["success_count"] == 1


def test_record_failure_removes_entry(temp_memory):
    """Entry should be removed if success count reaches 0."""
    fp = "remove-me"
    temp_memory.record_success(fp, "diff", 0.9, "repo")
    temp_memory.record_failure(fp)
    
    assert temp_memory.lookup(fp) is None


def test_persistence(tmp_path):
    """Data should survive reloads."""
    path = str(tmp_path / "persist.json")
    mem1 = RepairMemory(path)
    mem1.record_success("fp1", "diff", 0.95, "repo")
    
    # New instance loading same file
    mem2 = RepairMemory(path)
    assert mem2.lookup("fp1") is not None
    assert mem2.lookup("fp1")["patch_diff"] == "diff"
