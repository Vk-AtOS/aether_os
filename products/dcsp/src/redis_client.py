"""
Redis singleton client for DCSP.

Reads REDIS_URL from environment, falls back to redis://localhost:6379/0.
If Redis is unavailable at startup, all methods fall back gracefully.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_client = None
_available = False


def _init_client():
    global _client, _available
    if _client is not None:
        return
    try:
        import redis as _redis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _client = _redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        _client.ping()
        _available = True
        logger.info("Redis connected at %s", url)
    except Exception as e:
        logger.warning("Redis unavailable — sessions will use in-memory fallback: %s", e)
        _client = None
        _available = False


def get_client():
    """Return the Redis client, or None if unavailable."""
    _init_client()
    return _client if _available else None


def setex(key: str, seconds: int, value: str) -> bool:
    """Set a key with TTL. Returns True on success, False on error."""
    c = get_client()
    if c is None:
        return False
    try:
        c.setex(key, seconds, value)
        return True
    except Exception as e:
        logger.warning("Redis setex failed for key %s: %s", key, e)
        return False


def get(key: str) -> Optional[str]:
    """Get a key value. Returns None if missing or on error."""
    c = get_client()
    if c is None:
        return None
    try:
        return c.get(key)
    except Exception as e:
        logger.warning("Redis get failed for key %s: %s", key, e)
        return None


def delete(key: str) -> bool:
    """Delete a key. Returns True on success."""
    c = get_client()
    if c is None:
        return False
    try:
        c.delete(key)
        return True
    except Exception as e:
        logger.warning("Redis delete failed for key %s: %s", key, e)
        return False
