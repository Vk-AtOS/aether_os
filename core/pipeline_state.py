"""
AetherOS — Redis-backed Pipeline State (B3)

Replaces per-process PIPELINE_EVENTS dict and PIPELINE_CONTROL dict.
All workers share state via Redis pub/sub and key-value store.

Falls back gracefully: if Redis is unavailable, operations use local in-memory
queues so SSE streaming still delivers events in single-process mode.
"""
from __future__ import annotations
import json
import logging
import os
from collections import defaultdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_redis = None
_redis_available = False
# Log Redis unavailability only once to avoid log spam
_redis_warned: bool = False

# ── Local in-memory fallbacks (used when Redis is unavailable) ────────────────
# Maps run_id → list of serialised event payloads
_local_history: Dict[str, List[str]] = defaultdict(list)
# Maps run_id → control command ("run" | "pause" | "cancel")
_local_control: Dict[str, str] = {}


def set_control_local(run_id: str, command: str) -> None:
    """Set a control command in the local (non-Redis) control dict."""
    _local_control[run_id] = command


async def get_redis():
    global _redis, _redis_available, _redis_warned
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
        if not _redis_warned:
            _redis_warned = True
            logger.warning(
                "Pipeline state: Redis unavailable (%s). "
                "Falling back to local in-memory event buffer — "
                "SSE and pause/cancel will work in single-process mode only.",
                exc,
            )
    return _redis if _redis_available else None


async def publish_event(run_id: str, event: dict) -> None:
    r = await get_redis()
    payload = json.dumps(event)
    if r is None:
        # Local in-memory fallback: buffer events so SSE consumers can poll
        _local_history[run_id].append(payload)
    else:
        try:
            await r.publish(f"pipeline:events:{run_id}", payload)
            await r.rpush(f"pipeline:history:{run_id}", payload)
            await r.expire(f"pipeline:history:{run_id}", 86400)
        except Exception as exc:
            logger.debug("publish_event failed for run %s (buffering locally): %s", run_id, exc)
            _local_history[run_id].append(payload)
    # Fix 24: async write to pipeline_events PG table
    try:
        from aether_os.core.db import get_session_factory as _gsf_pe
        from aether_os.core.models import PipelineEvent as _PE
        async with _gsf_pe()() as _s_pe:
            _s_pe.add(_PE(
                run_id=run_id,
                event_type=event.get("type", "unknown"),
                payload=event,
            ))
            await _s_pe.commit()
    except Exception as _pe_exc:
        logger.debug("pipeline_events PG write failed (non-fatal): %s", _pe_exc)


async def get_event_history(run_id: str) -> List[dict]:
    r = await get_redis()
    if r is None:
        return [json.loads(i) for i in _local_history.get(run_id, [])]
    try:
        items = await r.lrange(f"pipeline:history:{run_id}", 0, -1)
        return [json.loads(i) for i in items]
    except Exception:
        return [json.loads(i) for i in _local_history.get(run_id, [])]


async def set_control(run_id: str, command: str) -> None:
    # Always update local dict so get_control works without Redis
    _local_control[run_id] = command
    r = await get_redis()
    if r is None:
        return
    try:
        await r.set(f"pipeline:control:{run_id}", command, ex=3600)
    except Exception as exc:
        logger.debug("set_control failed for run %s (local dict updated): %s", run_id, exc)


async def get_control(run_id: str) -> str:
    r = await get_redis()
    if r is None:
        # Check local dict first — this is how pause/cancel work without Redis
        return _local_control.get(run_id, "run")
    try:
        val = await r.get(f"pipeline:control:{run_id}")
        return val or _local_control.get(run_id, "run")
    except Exception:
        return _local_control.get(run_id, "run")


async def clear_run(run_id: str) -> None:
    # Clear local state regardless of Redis
    _local_history.pop(run_id, None)
    _local_control.pop(run_id, None)
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
