"""KAN-49: a Redis that refuses connections opens a breaker (same pattern as the PostgreSQL one), so callers fail fast."""
import asyncio

import pytest

pytest.importorskip("redis")
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError

from aether_os.core.resilience import all_breakers, reset_all
from aether_os.core.resilience.redis_breaker import breaker_connection_class


@pytest.fixture(autouse=True)
def _fresh():
    reset_all()
    yield
    reset_all()


def test_connect_failures_open_the_breaker_and_then_calls_fail_fast(monkeypatch):
    monkeypatch.setenv("REDIS_BREAKER_FAILURES", "3")
    cls = breaker_connection_class()
    attempts = []
    orig = aioredis.Connection.connect

    async def refuse(self):
        attempts.append(1)
        raise RedisConnectionError("refused")
    monkeypatch.setattr(aioredis.Connection, "connect", refuse)

    async def go():
        r = aioredis.Redis.from_url("redis://127.0.0.1:1", connection_class=cls)
        for _ in range(3):
            with pytest.raises(RedisConnectionError):
                await r.ping()
        assert len(attempts) == 3 and all_breakers()["redis"].state == "open"
        with pytest.raises(RedisConnectionError) as e:     # open: refused without touching the network
            await r.ping()
        assert "circuit open" in str(e.value) and len(attempts) == 3
        await r.aclose()
    asyncio.run(go())
    monkeypatch.setattr(aioredis.Connection, "connect", orig)


def test_half_open_probe_success_closes_it(monkeypatch):
    monkeypatch.setenv("REDIS_BREAKER_FAILURES", "1")
    monkeypatch.setenv("REDIS_BREAKER_RESET_S", "0")
    cls = breaker_connection_class()
    ok = {"up": False}

    async def maybe(self):
        if not ok["up"]:
            raise RedisConnectionError("down")
    monkeypatch.setattr(aioredis.Connection, "connect", maybe)

    async def go():
        c = cls()
        with pytest.raises(RedisConnectionError):
            await c.connect()
        ok["up"] = True
        await c.connect()                                   # reset_after 0: this is the probe, and it succeeds
        assert all_breakers()["redis"].state == "closed"
    asyncio.run(go())
