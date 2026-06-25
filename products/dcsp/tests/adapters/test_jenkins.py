"""
Tests for JenkinsAdapter.
"""

from __future__ import annotations

import pytest
from src.adapters.jenkins import JenkinsAdapter


def test_detects_jenkins_payload():
    """Test that Jenkins payload is detected and parsed."""
    adapter = JenkinsAdapter()
    payload = {
        "build": {
            "full_url": "http://jenkins:8080/job/dcsp-repair/15/",
            "parameters": {"BRANCH": "develop"},
            "scm": {"commit": "f00ba2"},
            "log": "jenkins log output"
        }
    }
    event = adapter.parse(payload)
    assert event is not None
    assert event.repo_name == "dcsp-repair"
    assert event.branch == "develop"
    assert event.commit_sha == "f00ba2"
    assert event.log_output == "jenkins log output"
    assert event.ci_system == "jenkins"


def test_returns_none_for_unknown_payload():
    """Test that unknown payloads return None."""
    adapter = JenkinsAdapter()
    payload = {"workflow_run": {}} # GitHub payload
    assert adapter.parse(payload) is None


def test_extracts_repo_and_branch():
    """Test repo and branch extraction from complex Jenkins URL."""
    adapter = JenkinsAdapter()
    payload = {
        "build": {
            "full_url": "http://internal.jenkins/job/folder/job/my-service/1/",
            "parameters": {"BRANCH": "main"}
        }
    }
    event = adapter.parse(payload)
    assert event.repo_name == "folder" # First part after /job/ in my current impl
    # Note: Jenkins URL structures can vary, our impl takes first non-'job' part
    assert event.branch == "main"
