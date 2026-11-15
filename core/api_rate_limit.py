"""Per-user and per-organisation request limits for every authenticated API call (KAN-67, D5).

Shared sliding windows in Redis, so the limit holds across workers and hosts. One org (or one
runaway script) cannot starve the others. Numbers are env-configurable DEFAULTS that need the
owner's review: they are sized for one org of ~1000 engineers (about 100 req/s) and a single
user at about 10 req/s.

Failure rule: when the shared store cannot answer in production the request is refused with 503
(fail closed, same as token revocation, which needs Redis too); in development a per-process
window is used so a laptop without Redis still works.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException

from aether_os.core.rate_limiter import _get_async_redis, _redis_incr_window, redis_required

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 60

_mem: Dict[str, Deque[float]] = defaultdict(deque)  # development fallback only


def limits() -> Dict[str, int]:
    return {
        "user": int(os.environ.get("API_RATE_PER_USER_PER_MIN", 600)),
        "org": int(os.environ.get("API_RATE_PER_ORG_PER_MIN", 6000)),
    }


def _mem_hit(key: str) -> int:
    now = time.monotonic()
    q = _mem[key]
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    q.append(now)
    return len(q)


async def _hit(key: str, redis) -> int:
    return await _redis_incr_window(redis, key, WINDOW_SECONDS) if redis else _mem_hit(key)


async def enforce_api_rate(user_id: Optional[str], org_id: Optional[str]) -> None:
    """Count this request against the user's and the org's window; 429 (Retry-After) when over."""
    lim = limits()
    try:
        redis = await _get_async_redis()
        if redis is None and redis_required():
            raise ConnectionError("shared rate-limit store unavailable")
        counts = {}
        if org_id:
            counts["org"] = await _hit(f"api_rate:org:{org_id}", redis)
        if user_id:
            counts["user"] = await _hit(f"api_rate:user:{user_id}", redis)
    except Exception as exc:
        logger.warning("API rate limiter unavailable, refusing request: %s", exc)
        raise HTTPException(status_code=503, detail="Rate limiter unavailable, retry shortly",
                            headers={"Retry-After": "5"}) from exc
    for scope, count in counts.items():
        if count > lim[scope]:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded ({scope})",
                                headers={"Retry-After": str(WINDOW_SECONDS)})
