"""
AetherOS — Redis-backed Pipeline State (B3)

Replaces per-process PIPELINE_EVENTS dict and PIPELINE_CONTROL dict.
All workers share state via Redis pub/sub and key-value store.

Falls back gracefully: if Redis is unavailable, operations are no-ops
(pipeline still runs, SSE streaming is degraded to non-working but doesn't crash).
"""
from __future__ import annotations
import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_redis = None
_redis_available = False


async def get_redis():
    global _redis, _redis_available
    if _redis is not None:
        return _redis if _redis_available else None
    try:
        import redis.asyncio as aioredis  # type: ignore
        _redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        _redis_available = True
        logger.info("Pipeline state: Redis connected at %s", REDIS_URL.split("@")[-1])
    except Exception as exc:
        _redis_available = False
        logger.warning(
            "Pipeline state: Redis unavailable (%s). "
            "SSE streaming and pause/cancel will not work across workers.",
            exc,
        )
    return _redis if _redis_available else None


async def publish_event(run_id: str, event: dict) -> None:
    r = await get_redis()
    if r is None:
        return
    try:
        payload = json.dumps(event)
        await r.publish(f"pipeline:events:{run_id}", payload)
        await r.rpush(f"pipeline:history:{run_id}", payload)
        await r.expire(f"pipeline:history:{run_id}", 86400)
    except Exception as exc:
        logger.debug("publish_event failed for run %s: %s", run_id, exc)


async def get_event_history(run_id: str) -> List[dict]:
    r = await get_redis()
    if r is None:
        return []
    try:
        items = await r.lrange(f"pipeline:history:{run_id}", 0, -1)
        return [json.loads(i) for i in items]
    except Exception:
        return []


async def set_control(run_id: str, command: str) -> None:
    r = await get_redis()
    if r is None:
        return
    try:
        await r.set(f"pipeline:control:{run_id}", command, ex=3600)
    except Exception as exc:
        logger.debug("set_control failed for run %s: %s", run_id, exc)


async def get_control(run_id: str) -> str:
    r = await get_redis()
    if r is None:
        return "run"
    try:
        val = await r.get(f"pipeline:control:{run_id}")
        return val or "run"
    except Exception:
        return "run"


async def clear_run(run_id: str) -> None:
    r = await get_redis()
    if r is None:
        return
    try:
        await r.delete(
            f"pipeline:events:{run_id}",
            f"pipeline:history:{run_id}",
            f"pipeline:control:{run_id}",
        )
    except Exception as exc:
        logger.debug("clear_run failed for run %s: %s", run_id, exc)
