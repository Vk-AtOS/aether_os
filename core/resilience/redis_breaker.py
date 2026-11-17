"""Circuit breaker for Redis, same pattern as the PostgreSQL one in core/db.py (KAN-49).

A connection class for redis.asyncio: a refused/timed-out connect, or a connection that drops mid-command, counts as a
failure; after `failure_threshold` in a row new connects are refused at once (RedisCircuitOpen, a redis ConnectionError,
so every caller that already treats "Redis is down" keeps working) until `reset_after_s` passes and one probe goes
through. Connections already open keep working. State is per process, like the other breakers; /readyz lists it.
"""
from __future__ import annotations

import functools
import os
from typing import Any

from aether_os.core.resilience.breaker import CircuitBreaker, CircuitOpen, get_breaker


def redis_breaker() -> CircuitBreaker:
    return get_breaker("redis", failure_threshold=int(os.environ.get("REDIS_BREAKER_FAILURES", "5")),
                       reset_after_s=float(os.environ.get("REDIS_BREAKER_RESET_S", "10")))


@functools.lru_cache(maxsize=1)
def breaker_connection_class() -> type:
    """redis.asyncio.Connection that reports to the "redis" breaker. Imported lazily: redis is an optional dependency."""
    from redis.asyncio import Connection
    from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

    class RedisCircuitOpen(CircuitOpen, RedisConnectionError):
        """Raised instead of connecting while the breaker is open."""

    _DOWN = (RedisConnectionError, RedisTimeoutError, OSError)

    class BreakerConnection(Connection):
        async def connect(self) -> Any:
            br = redis_breaker()
            try:
                br.before_call()
            except CircuitOpen as e:
                raise RedisCircuitOpen(e.name, e.retry_in) from None
            try:
                out = await super().connect()
            except BaseException as e:  # a cancelled probe must free the half-open slot too
                if isinstance(e, _DOWN):
                    br.record_failure(e)
                else:
                    br.release_probe()
                raise
            br.record_success()
            return out

        async def read_response(self, *args: Any, **kwargs: Any) -> Any:
            br = redis_breaker()
            try:
                out = await super().read_response(*args, **kwargs)
            except _DOWN as e:
                br.record_failure(e)
                raise
            if br._failures:                 # cheap unlocked check; a success clears the streak
                br.record_success()
            return out

    return BreakerConnection
