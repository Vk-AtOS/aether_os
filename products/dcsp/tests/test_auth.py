"""
Tests for authentication logic.
"""

from __future__ import annotations

import pytest
from src.api.auth import verify_credentials, create_session_token, verify_session_token, invalidate_session, ACTIVE_SESSIONS

def test_verify_valid_credentials():
    """Test verification with correct credentials."""
    assert verify_credentials("admin", "dcsp2024") is True
    assert verify_credentials("demo", "demo123") is True

def test_verify_invalid_credentials():
    """Test verification with incorrect credentials."""
    assert verify_credentials("admin", "wrongpass") is False
    assert verify_credentials("unknown", "demo123") is False
    assert verify_credentials("", "") is False

def test_create_and_verify_session_token():
    """Test session token lifecycle."""
    token = create_session_token("admin")
    assert token is not None
    assert len(token) == 64 # token_hex(32) is 64 chars
    
    username = verify_session_token(token)
    assert username == "admin"

def test_invalidate_session_removes_token():
    """Test session invalidation."""
    token = create_session_token("demo")
    assert verify_session_token(token) == "demo"
    
    invalidate_session(token)
    assert verify_session_token(token) is None

def test_unknown_token_returns_none():
    """Test verification with non-existent token."""
    assert verify_session_token("invalid-token") is None
