"""
Tests for GitHubActionsAdapter.
"""

from __future__ import annotations

import pytest
from src.adapters.github_actions import GitHubActionsAdapter


def test_detects_workflow_run_payload():
    """Test that workflow_run payload is detected and parsed."""
    adapter = GitHubActionsAdapter()
    payload = {
        "repository": {"full_name": "owner/repo"},
        "workflow_run": {
            "head_branch": "main",
            "head_sha": "abc1234"
        },
        "log_output": "failure log"
    }
    event = adapter.parse(payload)
    assert event is not None
    assert event.repo_name == "owner/repo"
    assert event.branch == "main"
    assert event.commit_sha == "abc1234"
    assert event.log_output == "failure log"
    assert event.ci_system == "github_actions"


def test_detects_check_run_payload():
    """Test that check_run payload is detected and parsed."""
    adapter = GitHubActionsAdapter()
    payload = {
        "repository": {"full_name": "owner/repo2"},
        "check_run": {
            "head_sha": "def5678",
            "check_suite": {"head_branch": "dev"}
        }
    }
    event = adapter.parse(payload)
    assert event is not None
    assert event.repo_name == "owner/repo2"
    assert event.branch == "dev"
    assert event.commit_sha == "def5678"


def test_returns_none_for_unknown_payload():
    """Test that unknown payloads return None."""
    adapter = GitHubActionsAdapter()
    payload = {"foo": "bar"}
    assert adapter.parse(payload) is None


def test_extracts_repo_and_branch():
    """Test repo and branch extraction."""
    adapter = GitHubActionsAdapter()
    payload = {
        "repository": {"full_name": "acme/web"},
        "workflow_run": {
            "head_branch": "feature-x",
            "head_sha": "112233"
        }
    }
    event = adapter.parse(payload)
    assert event.repo_name == "acme/web"
    assert event.branch == "feature-x"
