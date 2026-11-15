"""KAN-67/110: per-user and per-org limits shared by every worker, fail closed in production."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from aether_os.core import api_rate_limit as arl
from aether_os.tests.fake_redis import FakeRedis


def _run(coro):
    return asyncio.run(coro)


def _use(redis):
    return patch.object(arl, "_get_async_redis", new=AsyncMock(return_value=redis))


def test_two_workers_share_one_window_per_user_and_per_org(monkeypatch):
    monkeypatch.setenv("API_RATE_PER_USER_PER_MIN", "3")
    monkeypatch.setenv("API_RATE_PER_ORG_PER_MIN", "5")
    shared = FakeRedis()
    with _use(shared):  # "worker 1" and "worker 2" are two calls into the same store
        for _ in range(2):
            _run(arl.enforce_api_rate("u1", "o1"))        # worker 1
        _run(arl.enforce_api_rate("u1", "o1"))             # worker 2: third hit of u1, allowed (limit 3)
        with pytest.raises(HTTPException) as e:
            _run(arl.enforce_api_rate("u1", "o1"))         # 4th user hit, whichever worker
        assert e.value.status_code == 429 and e.value.headers["Retry-After"]
        _run(arl.enforce_api_rate("u2", "o1"))             # other user, org count now 5
        with pytest.raises(HTTPException) as e:
            _run(arl.enforce_api_rate("u3", "o1"))         # org window exhausted: 6th org hit
        assert e.value.status_code == 429
        _run(arl.enforce_api_rate("u9", "other-org"))      # another org is untouched


def test_hits_in_the_same_millisecond_all_count(monkeypatch):
    monkeypatch.setenv("API_RATE_PER_USER_PER_MIN", "2")
    with _use(FakeRedis()), patch("aether_os.core.rate_limiter.time.time", return_value=1000.0):
        _run(arl.enforce_api_rate("u", None))
        _run(arl.enforce_api_rate("u", None))
        with pytest.raises(HTTPException):
            _run(arl.enforce_api_rate("u", None))


def test_redis_outage_fails_closed_in_production_and_degrades_in_dev(monkeypatch):
    redis = FakeRedis()
    redis.down = True
    with _use(redis):
        with pytest.raises(HTTPException) as e:
            _run(arl.enforce_api_rate("u", "o"))
        assert e.value.status_code == 503
    monkeypatch.setenv("ENVIRONMENT", "production")
    with _use(None):
        with pytest.raises(HTTPException) as e:
            _run(arl.enforce_api_rate("u", "o"))
        assert e.value.status_code == 503
    monkeypatch.setenv("ENVIRONMENT", "development")
    arl._mem.clear()
    with _use(None):
        _run(arl.enforce_api_rate("dev-u", "dev-o"))   # no Redis on a laptop: per-process window, no error


def test_login_limit_denies_when_redis_is_missing_in_production(monkeypatch):
    from aether_os.core.rate_limiter import RateLimiter
    monkeypatch.setenv("ENVIRONMENT", "production")
    with patch("aether_os.core.rate_limiter._get_async_redis", new=AsyncMock(return_value=None)):
        rl = RateLimiter()
        assert _run(rl.check_login_attempts("203.0.113.9")) is False
        assert _run(rl.check_registration_attempts("203.0.113.9")) is False
        assert _run(rl.check_password_reset_attempts("203.0.113.9")) is False
    monkeypatch.setenv("ENVIRONMENT", "development")
    with patch("aether_os.core.rate_limiter._get_async_redis", new=AsyncMock(return_value=None)):
        assert _run(RateLimiter().check_login_attempts("203.0.113.9")) is True


def test_redis_is_retried_after_an_outage_at_first_use(monkeypatch):
    import aether_os.core.rate_limiter as rl
    monkeypatch.setattr(rl, "_redis_available", False)
    monkeypatch.setattr(rl, "_async_redis_client", None)
    monkeypatch.setattr(rl, "_redis_retry_at", rl.time.monotonic() - 1)  # the failed connect is due for a retry
    with patch("redis.asyncio.Redis.from_url", return_value=AsyncMock()) as made:
        assert _run(rl._get_async_redis()) is not None
    assert made.called


def test_every_authenticated_request_is_counted(gw, monkeypatch):
    monkeypatch.setenv("API_RATE_PER_USER_PER_MIN", "3")
    arl._mem.clear()
    user = gw.register("ratey")
    codes = [gw.client.get("/auth/my-orgs", headers=user.auth).status_code for _ in range(5)]
    assert 429 in codes and codes[0] == 200
