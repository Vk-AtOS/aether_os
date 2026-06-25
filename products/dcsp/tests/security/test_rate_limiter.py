"""
Tests for rate limiter.
"""

from __future__ import annotations

import time
import pytest
from src.security.rate_limiter import RateLimiter


def test_allows_under_limit():
    """Test that requests within limit are allowed."""
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    for _ in range(5):
        assert limiter.is_allowed("user1") is True


def test_blocks_over_limit():
    """Test that requests over limit are blocked."""
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    assert limiter.is_allowed("user1") is True
    assert limiter.is_allowed("user1") is True
    assert limiter.is_allowed("user1") is True
    assert limiter.is_allowed("user1") is False


def test_different_identifiers_independent():
    """Test that limits are tracked separately for different users."""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.is_allowed("userA") is True
    assert limiter.is_allowed("userB") is True
    assert limiter.is_allowed("userA") is False


def test_get_stats_returns_correct_count():
    """Test stats reporting."""
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    limiter.is_allowed("user1")
    limiter.is_allowed("user1")
    
    stats = limiter.get_stats("user1")
    assert stats["count"] == 2
    assert stats["allowed"] is True
    assert stats["identifier"] == "user1"
