"""
Tests for PR/MR creator.
"""

from __future__ import annotations

import pytest
from src.repo.pr_creator import PRCreator, PRResult


def test_pr_result_fields():
    """Verify PRResult dataclass structure."""
    res = PRResult(success=True, url="http://pr", number=42, error="")
    assert res.success is True
    assert res.url == "http://pr"
    assert res.number == 42
    assert res.error == ""


def test_create_github_pr_no_token():
    """Test GitHub PR creation attempt without token."""
    # We don't want to hit real network in tests, but if we call without token
    # it should fail gracefully.
    creator = PRCreator("acme/repo", token="")
    result = creator.create_github_pr("branch", "title", "body")
    
    # It should fail because no token provided
    assert result.success is False
    assert result.error != ""


def test_create_gitlab_mr_no_token():
    """Test GitLab MR creation attempt without token."""
    creator = PRCreator("acme/repo")
    # Manually clear token if env var was set
    creator.gitlab_token = ""
    
    result = creator.create_gitlab_mr("branch", "title", "body")
    
    assert result.success is False
    assert result.error != ""
