"""Prime — reminders before an approval lapses, and the notice when it did (KAN-26).

sweep() is safe to run from every worker at once: each reminder and each expiry notice is
CLAIMED with `UPDATE ... WHERE <column> IS NULL`, and only the worker whose UPDATE changed a
row sends it, so a request is reminded once and its requester told once. An expired request
is already fail-closed (approvals._state, _why_not); this only tells people. A failed
notification is logged and not retried (the ledger entry records that it was due).
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from sqlalchemy import or_, select, update

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.core.models import User
from aether_os.core.notifications.email import get_email_notifier
from aether_os.prime.approvals import _now
from aether_os.prime.authz import PRIME
from aether_os.prime.models import PrimeRequest

logger = logging.getLogger(__name__)

REMIND_WITHIN = timedelta(hours=24)   # remind when this little time is left, or a third of the lifetime if less
BATCH = 200                           # requests handled per kind per sweep: the loop is bounded
DEFAULT_INTERVAL_SECONDS = 300

Notify = Callable[[str, str, str], Awaitable[Any]]    # (email, subject, text)


async def _email(to: str, subject: str, text: str) -> bool:
    return await get_email_notifier().send(to, subject, f"<p>{text}</p>", text)


async def _addresses(org_id: str, people: List[str]) -> List[str]:
    """Emails of these people (ids or emails) in this organisation; unknown ones are skipped."""
    wanted = [p for p in dict.fromkeys(people) if p and p != PRIME and not p.startswith("system:")]
    if not wanted:
        return []
    async with get_session_factory()() as session:
        rows = (await session.execute(select(User.email).where(
            User.org_id == org_id, User.is_active == True,  # noqa: E712
            or_(User.id.in_(wanted), User.email.in_([w.lower() for w in wanted]))))).scalars().all()
    return sorted(set(rows))


async def _claim(column: str, request_id: str, now: datetime, *extra: Any) -> bool:
    col = getattr(PrimeRequest, column)
    async with get_session_factory()() as session:
        won = (await session.execute(update(PrimeRequest).where(
            PrimeRequest.id == request_id, col.is_(None), *extra).values(**{column: now}))).rowcount
        await session.commit()
    return bool(won)


def _remind_due(row: PrimeRequest, now: datetime) -> bool:
    return row.expires_at - now <= min(REMIND_WITHIN, (row.expires_at - row.created_at) / 3)


async def _tell(notify: Notify, org_id: str, people: List[str], subject: str, text: str) -> int:
    sent = 0
    for to in await _addresses(org_id, people):
        try:
            await notify(to, subject, text)
            sent += 1
        except Exception as e:
            logger.warning("prime: notice to a person could not be sent: %s", type(e).__name__)
    return sent


async def sweep(now: Optional[datetime] = None, notify: Notify = _email) -> Dict[str, int]:
    """Send due reminders and expiry notices. Returns {"reminded": n, "expired": m}."""
    now = now or _now()
    out = {"reminded": 0, "expired": 0}
    async with get_session_factory()() as session:
        soon = (await session.execute(select(PrimeRequest).where(
            PrimeRequest.status == "pending", PrimeRequest.expires_at > now,
            PrimeRequest.expires_at <= now + REMIND_WITHIN, PrimeRequest.reminded_at.is_(None))
            .order_by(PrimeRequest.expires_at).limit(BATCH))).scalars().all()
        lapsed = (await session.execute(select(PrimeRequest).where(
            PrimeRequest.status == "pending", PrimeRequest.expires_at <= now,
            PrimeRequest.expiry_notified_at.is_(None))
            .order_by(PrimeRequest.expires_at).limit(BATCH))).scalars().all()
    for row in soon:
        if _remind_due(row, now) and await _claim("reminded_at", row.id, now,
                                                  PrimeRequest.status == "pending"):
            left = int((row.expires_at - now).total_seconds() // 60)
            await audit_chain.append(actor=PRIME, action="prime.approval.reminder", payload={
                "request_id": row.id, "org_id": row.org_id, "type": row.action_type,
                "expires_at": row.expires_at.isoformat(), "minutes_left": left})
            await _tell(notify, row.org_id, [row.on_behalf_of, row.deputy],
                        "Approval waiting: it expires soon",
                        f"A request to {row.action_type} is waiting for a decision and expires in "
                        f"{left} minutes. Open the Prime inbox to approve or reject it.")
            out["reminded"] += 1
    for row in lapsed:
        if await _claim("expiry_notified_at", row.id, now, PrimeRequest.status == "pending"):
            await audit_chain.append(actor=PRIME, action="prime.approval.expire", payload={
                "request_id": row.id, "org_id": row.org_id, "type": row.action_type,
                "expired_at": row.expires_at.isoformat(), "requested_by": row.requested_by})
            await _tell(notify, row.org_id, [row.requested_by, row.on_behalf_of],
                        "Approval expired: nothing was done",
                        f"Your request to {row.action_type} was not decided in time and has expired. "
                        "It was NOT carried out. Submit it again if it is still needed.")
            out["expired"] += 1
    return out


def interval_seconds() -> int:
    return int(os.environ.get("PRIME_REMINDER_INTERVAL", DEFAULT_INTERVAL_SECONDS))


async def run_periodically(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            summary = await sweep()
            if any(summary.values()):
                logger.info("prime reminder sweep: %s", summary)
        except Exception as e:  # the loop must survive a bad run; the next one retries
            logger.error("prime reminder sweep failed: %s", e)


@asynccontextmanager
async def periodic_lifespan(_app: Any) -> AsyncIterator[None]:
    """Router lifespan: sweep every PRIME_REMINDER_INTERVAL seconds (0 = off)."""
    interval = interval_seconds()
    task = asyncio.create_task(run_periodically(interval)) if interval > 0 else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
