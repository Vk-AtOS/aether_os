"""
Tests for HMAC and token verifiers.
"""

from __future__ import annotations

import hashlib
import hmac
import pytest
from src.security.hmac_verifier import (
    verify_github_signature,
    verify_gitlab_token,
    verify_jenkins_token
)


def test_valid_github_signature():
    """Test verification with a valid GitHub signature."""
    secret = "test-secret"
    payload = b'{"action": "opened"}'
    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    assert verify_github_signature(payload, signature, secret) is True


def test_invalid_github_signature():
    """Test verification with an invalid GitHub signature."""
    assert verify_github_signature(b"payload", "sha256=wrong", "secret") is False


def test_empty_secret_returns_false_github():
    """Empty secret should fail verification."""
    assert verify_github_signature(b"payload", "sha256=abc", "") is False


def test_gitlab_token_match():
    """Test GitLab token matching."""
    assert verify_gitlab_token("my-token", "my-token") is True


def test_gitlab_token_mismatch():
    """Test GitLab token mismatch."""
    assert verify_gitlab_token("token1", "token2") is False


def test_jenkins_token_match():
    """Test Jenkins token matching."""
    assert verify_jenkins_token("j-token", "j-token") is True


def test_jenkins_token_mismatch():
    """Test Jenkins token mismatch."""
    assert verify_jenkins_token("t1", "t2") is False


def test_empty_signature_header_returns_false():
    """Missing header should fail."""
    assert verify_github_signature(b"p", "", "s") is False
