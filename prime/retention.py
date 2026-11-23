"""Prime — retention of learned data (KAN-228) and the purge job.

Learned items expire after the organisation's retention period (DEFAULT_RETENTION_DAYS, about 12 months; an owner
or admin may change it inside MIN/MAX, ledgered). The purge job, run every PRIME_LEARNING_PURGE_INTERVAL seconds
from the /prime/data router's lifespan (the same pattern as the reminder sweep and the ledger anchor), deletes
  * expired items, per organisation, and
  * items from any source whose consent no longer holds (consent.allowed is false): a source switched off is
    deleted at once by the switch itself, and anything a collector stored in the same moment goes within one cycle.
Safe on every worker at once: it only deletes, and deleting twice deletes nothing the second time.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, Optional

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.prime import learned
from aether_os.prime.authz import PRIME
from aether_os.prime.learned import _now
from aether_os.prime.models import PrimeLearningSettings

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 365
MIN_RETENTION_DAYS, MAX_RETENTION_DAYS = 1, 1825
DEFAULT_INTERVAL_SECONDS = 3600
GROUPS_PER_RUN = 1000      # (org, person, source) groups checked per run: the job is bounded


async def retention_days(org_id: str) -> int:
    async with get_session_factory()() as session:
        row = await session.get(PrimeLearningSettings, org_id)
    return row.retention_days if row else DEFAULT_RETENTION_DAYS


async def set_retention_days(org_id: str, days: int, by: str) -> int:
    if not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
        raise ValueError(f"retention must be between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS} days")
    old = await retention_days(org_id)
    if days == old:
        return days
    await audit_chain.append(actor=by, action="prime.data.retention.change",
                             payload={"org_id": org_id, "from": old, "to": days})
    async with get_session_factory()() as session:
        row = await session.get(PrimeLearningSettings, org_id)
        if row is None:
            row = PrimeLearningSettings(org_id=org_id)
            session.add(row)
        row.retention_days, row.updated_by, row.updated_at = days, by, _now()
        await session.commit()
    return days


async def purge(now: Optional[datetime] = None) -> Dict[str, int]:
    """One cycle. Returns {"expired": n, "withdrawn": m}; each organisation with deletions gets one ledger entry."""
    now = now or _now()
    per_org: Dict[str, Dict[str, int]] = {}
    for org_id in await learned.orgs_holding():
        n = await learned.expire(org_id, now - timedelta(days=await retention_days(org_id)))
        if n:
            per_org.setdefault(org_id, {"expired": 0, "withdrawn": 0})["expired"] += n
    for org_id, n in (await learned.drop_withdrawn_everywhere(GROUPS_PER_RUN)).items():
        per_org.setdefault(org_id, {"expired": 0, "withdrawn": 0})["withdrawn"] += n
    for org_id, counts in per_org.items():
        await audit_chain.append(actor=PRIME, action="prime.data.purge", payload={"org_id": org_id, **counts})
    return {k: sum(c[k] for c in per_org.values()) for k in ("expired", "withdrawn")}


def interval_seconds() -> int:
    return int(os.environ.get("PRIME_LEARNING_PURGE_INTERVAL", DEFAULT_INTERVAL_SECONDS))


async def run_periodically(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            summary = await purge()
            if any(summary.values()):
                logger.info("prime learning purge: %s", summary)
        except Exception as e:  # the loop must survive a bad run; the next one retries
            logger.error("prime learning purge failed: %s", type(e).__name__)


@asynccontextmanager
async def periodic_lifespan(_app: Any) -> AsyncIterator[None]:
    """Router lifespan: purge every PRIME_LEARNING_PURGE_INTERVAL seconds (0 = off)."""
    interval = interval_seconds()
    task = asyncio.create_task(run_periodically(interval)) if interval > 0 else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
