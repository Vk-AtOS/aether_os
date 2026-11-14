"""KAN-110: a quiet Redis channel times out; a failed Redis connect is retried."""
import asyncio
import time

import pytest

from aether_os.core import pipeline_state as ps
from aether_os.core.decisions.decision_engine import Decision, DecisionEngine


class QuietPubSub:
    async def subscribe(self, ch): pass
    async def unsubscribe(self, ch): pass
    async def aclose(self): pass
    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        await asyncio.sleep(timeout)   # nothing is ever published
        return None
    def listen(self):                   # the old code path: blocks forever
        async def forever():
            await asyncio.sleep(3600)
            yield {}
        return forever()


class FakeRedis:
    def pubsub(self): return QuietPubSub()


def test_wait_on_a_quiet_channel_times_out():
    eng = DecisionEngine()
    saved = []

    async def db_get(_id): return Decision(id="d1", status="pending")
    async def db_save(d): saved.append(d.status)
    eng._db_get, eng._db_save = db_get, db_save
    d = Decision(id="d1", status="pending")
    t0 = time.monotonic()
    out = asyncio.run(asyncio.wait_for(eng._wait_redis(d, "ch", 0.3, FakeRedis()), timeout=5))
    assert out.status == "timeout" and saved == ["timeout"] and time.monotonic() - t0 < 3


def test_get_redis_retries_after_a_failed_connect(monkeypatch):
    import redis.asyncio as aioredis
    calls = []

    class Down:
        async def ping(self):
            calls.append(1)
            raise ConnectionError("down")

    class Up:
        async def ping(self): calls.append(2)

    clients = [Down(), Up()]
    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: clients.pop(0))
    monkeypatch.setattr(ps, "_redis", None)
    monkeypatch.setattr(ps, "_redis_available", False)
    monkeypatch.setattr(ps, "_redis_retry_at", 0.0)
    assert asyncio.run(ps.get_redis()) is None
    monkeypatch.setattr(ps, "_redis_retry_at", 0.0)   # the backoff window has passed
    assert asyncio.run(ps.get_redis()) is not None and calls == [1, 2]
