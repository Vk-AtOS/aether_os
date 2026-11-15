"""Kill switches and per-org policy lookups for LLM calls (KAN-116, D6).

* Global kill switch: env LLM_KILL_SWITCH=1, or the Redis flag an admin sets at runtime
  (POST /admin/llm/kill-switch) so every worker stops within seconds without a restart.
  If Redis cannot be read, the last known value is kept (the env switch always applies).
* Per-org: Organisation.llm_disabled (durable, in the database).
* org_policy(): plan, USD cap override and flags for an org, cached briefly so the guard adds
  no database round trip to most calls.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation
from aether_os.core.rate_limiter import _get_async_redis

logger = logging.getLogger(__name__)
GLOBAL_KEY = "llm:kill:global"
_FLAG_TTL = 5.0
_ORG_TTL = 30.0

_flag: Tuple[float, bool] = (0.0, False)
_orgs: Dict[str, Tuple[float, "OrgPolicy"]] = {}


@dataclass(frozen=True)
class OrgPolicy:
    plan: str
    cap_usd: Optional[float]
    disabled: bool
    deleted: bool


def env_kill_switch() -> bool:
    return os.environ.get("LLM_KILL_SWITCH", "").strip().lower() in ("1", "true", "yes", "on")


async def global_kill_active() -> bool:
    global _flag
    if env_kill_switch():
        return True
    at, value = _flag
    if time.monotonic() - at < _FLAG_TTL:
        return value
    try:
        redis = await _get_async_redis()
        if redis is not None:
            value = bool(await redis.get(GLOBAL_KEY))
    except Exception as exc:
        logger.warning("LLM kill switch: Redis unreadable, keeping last known value (%s): %s", value, exc)
    _flag = (time.monotonic(), value)
    return value


async def set_global_kill(on: bool) -> None:
    """Raises if Redis cannot take the change: an admin must know the switch did not move."""
    global _flag
    redis = await _get_async_redis()
    if redis is None:
        raise RuntimeError("shared store unavailable; set LLM_KILL_SWITCH=1 and restart instead")
    if on:
        await redis.set(GLOBAL_KEY, "1")
    else:
        await redis.delete(GLOBAL_KEY)
    _flag = (time.monotonic(), on)


async def org_policy(org_id: str) -> Optional[OrgPolicy]:
    """None when the organisation does not exist (the call must be refused)."""
    hit = _orgs.get(org_id)
    if hit and time.monotonic() - hit[0] < _ORG_TTL:
        return hit[1]
    async with get_session_factory()() as session:
        row = (await session.execute(
            select(Organisation.plan, Organisation.llm_monthly_cap_usd, Organisation.llm_disabled,
                   Organisation.is_deleted).where(Organisation.id == org_id)
        )).first()
    if row is None:
        return None
    policy = OrgPolicy(plan=row[0] or "", cap_usd=row[1], disabled=bool(row[2]), deleted=bool(row[3]))
    if len(_orgs) > 5000:
        _orgs.clear()
    _orgs[org_id] = (time.monotonic(), policy)
    return policy


def forget_org(org_id: str) -> None:
    _orgs.pop(org_id, None)
