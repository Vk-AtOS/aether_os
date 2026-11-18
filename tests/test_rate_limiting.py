import asyncio
import sys
import os
from unittest.mock import AsyncMock, patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from aether_os.core.rate_limiter import RateLimiter
import aether_os.core.rate_limiter as _rl_mod


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fresh_rl():
    """Reset in-memory store and return a new RateLimiter backed by in-memory only."""
    _rl_mod._mem = _rl_mod._MemoryStore()
    _rl_mod._redis_available = None
    _rl_mod._async_redis_client = None
    return RateLimiter()


def test_concurrent_runs_limit():
    with patch("aether_os.core.rate_limiter._get_async_redis", new_callable=AsyncMock, return_value=None):
        rl = _fresh_rl()
        org_id = "test-org-conc"
        for _ in range(5):
            _run(rl.record_run_start(org_id))
        assert _run(rl.check_concurrent_runs(org_id)) is False
        _run(rl.record_run_end(org_id))
        assert _run(rl.check_concurrent_runs(org_id)) is True


def test_login_attempts_limit():
    with patch("aether_os.core.rate_limiter._get_async_redis", new_callable=AsyncMock, return_value=None):
        rl = _fresh_rl()
        ip = "10.0.0.1"
        for _ in range(20):
            _run(rl.record_login_attempt(ip))
        assert _run(rl.check_login_attempts(ip)) is False


def test_hourly_starts_limit():
    with patch("aether_os.core.rate_limiter._get_async_redis", new_callable=AsyncMock, return_value=None):
        rl = _fresh_rl()
        org_id = "org-hourly-1"
        for _ in range(20):
            _run(rl.record_run_start(org_id))
        assert _run(rl.check_hourly_starts(org_id)) is False


def test_registration_attempts_limit():
    with patch("aether_os.core.rate_limiter._get_async_redis", new_callable=AsyncMock, return_value=None):
        rl = _fresh_rl()
        ip = "1.1.1.1"
        for _ in range(5):
            _run(rl.record_registration_attempt(ip))
        assert _run(rl.check_registration_attempts(ip)) is False
