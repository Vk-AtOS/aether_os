"""
Tests for CI adapter detection logic.
"""

from __future__ import annotations

import pytest
from src.adapters.detector import detect_adapter


def test_detects_github_actions():
    """Test detection of GitHub Actions adapter."""
    payload = {
        "repository": {"full_name": "owner/repo"},
        "workflow_run": {"head_branch": "main", "head_sha": "abc"}
    }
    adapter = detect_adapter(payload)
    assert adapter is not None
    assert adapter.name == "github_actions"


def test_detects_jenkins():
    """Test detection of Jenkins adapter."""
    payload = {
        "build": {"full_url": "http://jenkins/job/test/1/"}
    }
    adapter = detect_adapter(payload)
    assert adapter is not None
    assert adapter.name == "jenkins"


def test_detects_gitlab():
    """Test detection of GitLab CI adapter."""
    payload = {
        "object_kind": "pipeline",
        "project": {"path_with_namespace": "group/project"},
        "object_attributes": {"ref": "main", "sha": "123"}
    }
    adapter = detect_adapter(payload)
    assert adapter is not None
    assert adapter.name == "gitlab_ci"


def test_returns_none_for_unknown():
    """Test detection returns None for unknown payload."""
    payload = {"unknown_key": "unknown_value"}
    adapter = detect_adapter(payload)
    assert adapter is None
