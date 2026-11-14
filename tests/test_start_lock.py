"""N parallel run starts from one org must not all pass the concurrency check (KAN-136)."""
import asyncio

import pytest
from fastapi import HTTPException

import aether_os.core.start_lock as sl


async def _no_redis():
    return None


def test_lock_serialises_check_then_insert(monkeypatch):
    monkeypatch.setattr(sl, "_get_async_redis", _no_redis)
    sl._local.clear()
    active, limit, started = [0], 2, []

    async def start(i, locked):
        async def body():
            if active[0] < limit:           # policy check
                await asyncio.sleep(0.01)   # the awaits between check and insert
                active[0] += 1              # run row inserted
                started.append(i)
        if locked:
            async with sl.org_start_lock("org"):
                await body()
        else:
            await body()

    async def go(locked):
        active[0] = 0
        started.clear()
        await asyncio.gather(*(start(i, locked) for i in range(10)))
        return len(started)

    assert asyncio.run(go(False)) == 10   # the race, without the lock
    assert asyncio.run(go(True)) == limit


def test_lock_times_out_with_503(monkeypatch):
    monkeypatch.setattr(sl, "_get_async_redis", _no_redis)
    monkeypatch.setattr(sl, "WAIT_S", 0.05)
    sl._local.clear()

    async def go():
        async with sl.org_start_lock("o"):
            with pytest.raises(HTTPException) as e:
                async with sl.org_start_lock("o"):
                    pass
            return e.value.status_code

    assert asyncio.run(go()) == 503


def test_redis_lock_is_exclusive_and_released(monkeypatch):
    class R:
        def __init__(self):
            self.d = {}

        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.d:
                return None
            self.d[k] = v
            return True

        async def eval(self, script, n, k, tok):
            if self.d.get(k) == tok:
                del self.d[k]

    r = R()

    async def get():
        return r

    monkeypatch.setattr(sl, "_get_async_redis", get)
    monkeypatch.setattr(sl, "WAIT_S", 0.05)

    async def go():
        async with sl.org_start_lock("o"):
            assert "startlock:o" in r.d
            with pytest.raises(HTTPException):
                async with sl.org_start_lock("o"):
                    pass
        assert not r.d

    asyncio.run(go())
