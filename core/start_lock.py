"""Per-organisation lock around "check quota/concurrency, then insert the run".

Root cause it fixes: policy checks the number of active runs, then the run row is inserted a few
awaits later; N parallel starts from one org (or one org spread over several workers) all saw
`active < limit` and all started. Redis SET NX serialises the section across workers; without Redis
a per-process asyncio lock is the best available (single-process dev).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from fastapi import HTTPException

from aether_os.core.rate_limiter import _get_async_redis

logger = logging.getLogger(__name__)

LOCK_TTL_S = 20
WAIT_S = 10.0
_local: dict[str, asyncio.Lock] = {}

_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


@contextlib.asynccontextmanager
async def org_start_lock(org_id: str):
    """Hold the org's start lock; 503 (retry) if it cannot be had within WAIT_S."""
    r = await _get_async_redis()
    if r is not None:
        key, token = f"startlock:{org_id}", uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        deadline = loop.time() + WAIT_S
        try:
            while not await r.set(key, token, nx=True, ex=LOCK_TTL_S):
                if loop.time() >= deadline:
                    raise HTTPException(status_code=503, detail="Another run start is in progress for this organisation; retry.")
                await asyncio.sleep(0.05)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("start lock Redis error, using in-process lock: %s", exc)
            r = None
    if r is not None:
        try:
            yield
        finally:
            try:
                await r.eval(_RELEASE, 1, key, token)
            except Exception as exc:
                logger.warning("start lock release failed (expires in %ss): %s", LOCK_TTL_S, exc)
        return
    lock = _local.setdefault(org_id, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), WAIT_S)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Another run start is in progress for this organisation; retry.")
    try:
        yield
    finally:
        lock.release()
