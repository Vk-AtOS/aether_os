"""Durable webhook delivery (KAN-102 item 7).

deliver_event() writes a row per webhook into webhook_outbox before anything is sent. An attempt first CLAIMS the
row with one atomic UPDATE (so several workers never send the same attempt twice), sends once, and then marks it
done, schedules the next attempt with backoff, or dead-letters it after _MAX_ATTEMPTS. A sweeper loop picks up rows
that are due: that is what makes a delivery survive a restart (a claim that was never finished simply expires).
The dead rows are what GET /system/dead-letters shows next to the queue's.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select, update

from aether_os.core.db import get_session_factory
from aether_os.core.models import Webhook
from aether_os.core.models_ops import WebhookOutbox
from aether_os.core.webhooks import delivery

logger = logging.getLogger(__name__)

BACKOFF = [5, 30, 120, 600, 1800, 3600]   # seconds before attempt 2, 3, ...
MAX_ATTEMPTS = len(BACKOFF) + 1           # attempt 1 is immediate; the last failure dead-letters
LEASE = 300                               # a claimed attempt that never finished is retried after this long
SWEEP_BATCH = 50
SWEEP_EVERY = 15.0
KEEP_DONE_S = 3 * 86400
KEEP_DEAD_S = 30 * 86400
_MAX_CONCURRENT = 20
_slots: Optional[asyncio.Semaphore] = None


async def enqueue(org_id: str, webhook_id: str, event_type: str, delivery_id: str, payload: Dict[str, Any]) -> str:
    row = WebhookOutbox(id=str(uuid.uuid4()), org_id=org_id, webhook_id=webhook_id, event_type=event_type,
                        delivery_id=delivery_id, payload=payload, status="pending", attempts=0, next_attempt_at=time.time())
    async with get_session_factory()() as s:
        s.add(row)
        await s.commit()
    return row.id


async def send_direct(wh: Dict[str, Any], event_type: str, payload: Dict[str, Any], delivery_id: str) -> bool:
    """Fallback when the outbox could not be written: one bounded in-memory attempt."""
    async with _gate():
        return await delivery._delivery.send(wh["url"], wh["secret"], event_type, payload, delivery_id)


def _gate() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(_MAX_CONCURRENT)
    return _slots


async def _claim(row_id: str) -> bool:
    now = time.time()
    async with get_session_factory()() as s:
        res = await s.execute(update(WebhookOutbox).where(
            WebhookOutbox.id == row_id, WebhookOutbox.status == "pending", WebhookOutbox.next_attempt_at <= now,
        ).values(attempts=WebhookOutbox.attempts + 1, next_attempt_at=now + LEASE, updated_at=now))
        await s.commit()
        return res.rowcount == 1


async def _finish(row_id: str, **values: Any) -> None:
    async with get_session_factory()() as s:
        await s.execute(update(WebhookOutbox).where(WebhookOutbox.id == row_id).values(updated_at=time.time(), **values))
        await s.commit()


async def attempt_row(row_id: str) -> bool:
    """One attempt for one due row. Never raises (a loop must not die on one bad row)."""
    try:
        if not await _claim(row_id):
            return False
        async with get_session_factory()() as s:
            row = await s.get(WebhookOutbox, row_id)
            wh = await s.get(Webhook, row.webhook_id) if row else None
        if row is None:
            return False
        if wh is None or not wh.is_active or wh.org_id != row.org_id:
            await _finish(row_id, status="dead", last_error="webhook removed or disabled")
            return False
        async with _gate():
            ok, retryable, err = await delivery._delivery.attempt(
                wh.url, delivery._signing_secret(wh.secret), row.event_type, row.payload, row.delivery_id)
        if ok:
            await _finish(row_id, status="done", last_error=None)
        elif retryable and row.attempts < MAX_ATTEMPTS:
            await _finish(row_id, next_attempt_at=time.time() + BACKOFF[row.attempts - 1], last_error=err[:500])
        else:
            logger.error("[webhook] dead-lettered %s for %s after %d attempt(s): %s", row.event_type, row.webhook_id, row.attempts, err)
            await _finish(row_id, status="dead", last_error=err[:500])
        return ok
    except Exception as exc:
        logger.warning("[webhook] outbox attempt for %s failed: %s", row_id, exc)
        return False


async def sweep_once(limit: int = SWEEP_BATCH) -> int:
    """Attempt every due row (at most `limit`), purge old finished rows. Returns the number attempted."""
    now = time.time()
    async with get_session_factory()() as s:
        ids: List[str] = list((await s.execute(
            select(WebhookOutbox.id).where(WebhookOutbox.status == "pending", WebhookOutbox.next_attempt_at <= now)
            .order_by(WebhookOutbox.next_attempt_at).limit(limit))).scalars())
        await s.execute(delete(WebhookOutbox).where(
            (WebhookOutbox.status == "done") & (WebhookOutbox.updated_at < now - KEEP_DONE_S)
            | (WebhookOutbox.status == "dead") & (WebhookOutbox.updated_at < now - KEEP_DEAD_S)))
        await s.commit()
    if ids:
        await asyncio.gather(*(attempt_row(i) for i in ids))
    return len(ids)


async def run_sweeper(stop: Optional[asyncio.Event] = None) -> None:
    """Background loop; one pass at most every SWEEP_EVERY seconds and each pass is bounded by SWEEP_BATCH."""
    while not (stop and stop.is_set()):
        try:
            await sweep_once()
        except Exception as exc:
            logger.warning("[webhook] sweeper pass failed: %s", exc)
        await asyncio.sleep(SWEEP_EVERY)


async def dead_letters(org_id: Optional[str], limit: int = 20) -> List[Dict[str, Any]]:
    """Newest dead rows (never the payload or any secret). org_id None = every organisation (platform operator)."""
    q = select(WebhookOutbox).where(WebhookOutbox.status == "dead").order_by(WebhookOutbox.updated_at.desc()).limit(limit)
    if org_id:
        q = q.where(WebhookOutbox.org_id == org_id)
    async with get_session_factory()() as s:
        rows = (await s.execute(q)).scalars().all()
    return [{"id": r.id, "webhook_id": r.webhook_id, "event": r.event_type, "attempts": r.attempts,
             "error": r.last_error, "failed_at": r.updated_at} for r in rows]
