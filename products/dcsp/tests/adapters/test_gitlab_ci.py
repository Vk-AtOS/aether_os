"""
Tests for GitLabCIAdapter.
"""

from __future__ import annotations

import pytest
from src.adapters.gitlab_ci import GitLabCIAdapter


def test_detects_gitlab_pipeline_payload():
    """Test that GitLab pipeline payload is detected and parsed."""
    adapter = GitLabCIAdapter()
    payload = {
        "object_kind": "pipeline",
        "project": {"path_with_namespace": "gitlab-org/gitlab"},
        "object_attributes": {
            "ref": "master",
            "sha": "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        },
        "log_output": "gitlab runner log"
    }
    event = adapter.parse(payload)
    assert event is not None
    assert event.repo_name == "gitlab-org/gitlab"
    assert event.branch == "master"
    assert event.commit_sha == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    assert event.log_output == "gitlab runner log"
    assert event.ci_system == "gitlab_ci"


def test_returns_none_for_unknown_payload():
    """Test that unknown payloads return None."""
    adapter = GitLabCIAdapter()
    payload = {"object_kind": "push"} # GitLab push event, not pipeline
    assert adapter.parse(payload) is None


def test_extracts_repo_and_branch():
    """Test repo and branch extraction."""
    adapter = GitLabCIAdapter()
    payload = {
        "object_kind": "pipeline",
        "project": {"path_with_namespace": "my-group/my-project"},
        "object_attributes": {
            "ref": "feature/fix-bug",
            "sha": "123456"
        }
    }
    event = adapter.parse(payload)
    assert event.repo_name == "my-group/my-project"
    assert event.branch == "feature/fix-bug"
