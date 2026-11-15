"""A minimal in-memory stand-in for the redis.asyncio calls the rate limiter makes, shareable between
two 'instances' (workers) and switchable to an outage, for tests that must not need a real Redis."""
from __future__ import annotations


class _Pipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __getattr__(self, name):
        async def queue(*args, **kw):
            self.ops.append((name, args))
        return queue

    async def execute(self):
        return [await getattr(self.r, name)(*args) for name, args in self.ops]


class FakeRedis:
    def __init__(self):
        self.z: dict[str, dict[str, float]] = {}
        self.down = False

    def _check(self):
        if self.down:
            raise ConnectionError("redis is down")

    def pipeline(self, transaction=False):
        self._check()
        return _Pipe(self)

    async def zremrangebyscore(self, key, lo, hi):
        self._check()
        z = self.z.setdefault(key, {})
        for m in [m for m, sc in z.items() if lo <= sc <= hi]:
            del z[m]

    async def zadd(self, key, mapping):
        self._check()
        self.z.setdefault(key, {}).update(mapping)

    async def zcard(self, key):
        self._check()
        return len(self.z.get(key, {}))

    async def expire(self, key, seconds):
        self._check()
