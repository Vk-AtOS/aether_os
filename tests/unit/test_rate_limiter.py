"""
Unit tests for core/rate_limiter.py

Tests rate limit logic using a mock Redis client. The in-memory fallback is
also tested to ensure correctness without any external dependencies.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch
import pytest

import aether_os.core.rate_limiter as rl_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_limiter():
    return rl_mod.RateLimiter()


def _reset_memory():
    """Clear in-memory store state between tests."""
    rl_mod._mem.active_runs.clear()
    rl_mod._mem.hourly_starts.clear()
    rl_mod._mem.login_attempts.clear()
    rl_mod._mem.registrations.clear()


# ---------------------------------------------------------------------------
# Key construction / IP normalisation
# ---------------------------------------------------------------------------

class TestIpNormalisation:
    def test_empty_ip_returns_unknown_bucket(self):
        limiter = _fresh_limiter()
        assert limiter._normalize_ip("") == "unknown_ip"

    def test_unknown_string_returns_unknown_bucket(self):
        limiter = _fresh_limiter()
        assert limiter._normalize_ip("unknown") == "unknown_ip"

    def test_real_ip_is_returned_unchanged(self):
        limiter = _fresh_limiter()
        assert limiter._normalize_ip("1.2.3.4") == "1.2.3.4"

    def test_localhost_exempt_in_dev_mode(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        limiter = _fresh_limiter()
        assert limiter._is_exempt_ip("127.0.0.1") is True
        assert limiter._is_exempt_ip("::1") is True

    def test_localhost_not_exempt_in_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        limiter = _fresh_limiter()
        assert limiter._is_exempt_ip("127.0.0.1") is False

    def test_unknown_never_exempt(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        limiter = _fresh_limiter()
        assert limiter._is_exempt_ip("unknown") is False


# ---------------------------------------------------------------------------
# check_concurrent_runs — in-memory path
# ---------------------------------------------------------------------------

class TestConcurrentRunsInMemory:
    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self, monkeypatch):
        _reset_memory()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=None))
        limiter = _fresh_limiter()
        limiter.max_concurrent_runs = 3
        rl_mod._mem.active_runs["org1"] = 2
        assert await limiter.check_concurrent_runs("org1") is True

    @pytest.mark.asyncio
    async def test_blocks_when_at_limit(self, monkeypatch):
        _reset_memory()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=None))
        limiter = _fresh_limiter()
        limiter.max_concurrent_runs = 3
        rl_mod._mem.active_runs["org1"] = 3
        assert await limiter.check_concurrent_runs("org1") is False

    @pytest.mark.asyncio
    async def test_record_run_start_increments_counter(self, monkeypatch):
        _reset_memory()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=None))
        limiter = _fresh_limiter()
        await limiter.record_run_start("orgX")
        assert rl_mod._mem.active_runs["orgX"] == 1

    @pytest.mark.asyncio
    async def test_record_run_end_decrements_counter(self, monkeypatch):
        _reset_memory()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=None))
        limiter = _fresh_limiter()
        rl_mod._mem.active_runs["orgX"] = 2
        await limiter.record_run_end("orgX")
        assert rl_mod._mem.active_runs["orgX"] == 1

    @pytest.mark.asyncio
    async def test_record_run_end_does_not_go_negative(self, monkeypatch):
        _reset_memory()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=None))
        limiter = _fresh_limiter()
        rl_mod._mem.active_runs["orgX"] = 0
        await limiter.record_run_end("orgX")
        assert rl_mod._mem.active_runs["orgX"] == 0


# ---------------------------------------------------------------------------
# check_login_attempts — in-memory path
# ---------------------------------------------------------------------------

class TestLoginAttemptsInMemory:
    @pytest.mark.asyncio
    async def test_allows_first_attempt(self, monkeypatch):
        _reset_memory()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=None))
        monkeypatch.setenv("ENVIRONMENT", "production")
        limiter = _fresh_limiter()
        limiter.max_login_attempts = 5
        result = await limiter.check_login_attempts("10.0.0.1", strict_mode=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_blocks_after_limit(self, monkeypatch):
        _reset_memory()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=None))
        monkeypatch.setenv("ENVIRONMENT", "production")
        limiter = _fresh_limiter()
        limiter.max_login_attempts = 3
        # Simulate 3 previous attempts within the last 15 minutes
        now = time.time()
        rl_mod._mem.login_attempts["10.0.0.2"] = [now - 5, now - 4, now - 3]
        result = await limiter.check_login_attempts("10.0.0.2", strict_mode=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_expired_attempts_are_pruned(self, monkeypatch):
        _reset_memory()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=None))
        monkeypatch.setenv("ENVIRONMENT", "production")
        limiter = _fresh_limiter()
        limiter.max_login_attempts = 3
        # All timestamps are older than 15-minute window
        old_time = time.time() - 1000
        rl_mod._mem.login_attempts["10.0.0.3"] = [old_time, old_time, old_time]
        result = await limiter.check_login_attempts("10.0.0.3", strict_mode=False)
        assert result is True


# ---------------------------------------------------------------------------
# check_login_attempts — Redis path
# ---------------------------------------------------------------------------

class TestLoginAttemptsRedis:
    @pytest.mark.asyncio
    async def test_uses_redis_count_when_available(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        mock_redis = AsyncMock()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=mock_redis))
        # Patch _redis_get_count to return 2 (under limit of 5)
        with patch.object(rl_mod, "_redis_get_count", AsyncMock(return_value=2)):
            limiter = _fresh_limiter()
            limiter.max_login_attempts = 5
            result = await limiter.check_login_attempts("1.2.3.4")
        assert result is True

    @pytest.mark.asyncio
    async def test_redis_failure_in_strict_mode_denies(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        mock_redis = AsyncMock()
        monkeypatch.setattr(rl_mod, "_get_async_redis", AsyncMock(return_value=mock_redis))
        with patch.object(rl_mod, "_redis_get_count", AsyncMock(side_effect=Exception("Redis down"))):
            limiter = _fresh_limiter()
            result = await limiter.check_login_attempts("1.2.3.4", strict_mode=True)
        assert result is False


# ---------------------------------------------------------------------------
# get_rate_limiter — singleton
# ---------------------------------------------------------------------------

class TestGetRateLimiter:
    def test_returns_singleton(self):
        rl_mod._instance = None
        limiter1 = rl_mod.get_rate_limiter()
        limiter2 = rl_mod.get_rate_limiter()
        assert limiter1 is limiter2

    def test_returns_rate_limiter_instance(self):
        rl_mod._instance = None
        limiter = rl_mod.get_rate_limiter()
        assert isinstance(limiter, rl_mod.RateLimiter)


# SSE token store: moved to gateway/auth_refresh.py (Redis only, 503 when down);
# tested in tests/test_backend_lane_fixes.py.
