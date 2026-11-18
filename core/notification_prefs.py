"""AetherOS — notification preferences: which events reach a user, in the app and by email.

Resolution for (org, user, event): the user's own row, else the organisation default row (user_id ''),
else on. The in-app list filters by this when it is read (so turning an event off also hides what already
exists); email is checked when it would be sent. Only events the product actually emits are listed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import NotificationPref
from aether_os.core.models_ops import NotificationQuietHours

EVENTS = {
    "run_completed": "A build finished",
    "run_failed": "A build failed",
    # core/llm/budget.py writes this org-wide in-app notice once a month at 80% (type llm_budget_80:<month>).
    "budget_alert": "AI usage reached 80% of the monthly limit",
    # Prime approvals (prime/reminders.py, prime/approvals.py): written as in-app Notification rows and e-mail.
    "approval_needed": "A request is waiting for your decision",
    "approval_expiring": "A request is about to expire",
    "approval_expired": "A request expired without a decision",
}
ORG_DEFAULT = ""
# Quiet hours hold back E-MAIL only (in-app notices stay, they are silent). These events are time-critical (an approval
# can expire while nobody is told), so they ignore quiet hours. Held e-mail is dropped, not deferred: the in-app
# notice is the record. That default is the owner's to change.
QUIET_EXEMPT = {"approval_needed", "approval_expiring", "approval_expired"}


async def effective(org_id: str, user_id: Optional[str]) -> Dict[str, Dict[str, object]]:
    """{event: {in_app, email, source}} for this user; source is 'user', 'org' or 'default'."""
    async with get_session_factory()() as session:
        rows = (await session.execute(select(NotificationPref).where(
            NotificationPref.org_id == org_id, NotificationPref.user_id.in_([ORG_DEFAULT, user_id or ORG_DEFAULT])
        ))).scalars().all()
    by = {(r.user_id, r.event_type): r for r in rows}
    out: Dict[str, Dict[str, object]] = {}
    for event in EVENTS:
        out[event] = {"in_app": True, "email": True, "source": "default"}
        owners = [(ORG_DEFAULT, "org")] + ([(user_id, "user")] if user_id else [])  # the user's own row wins
        for owner, source in owners:
            row = by.get((owner, event))
            if row is not None:
                out[event] = {"in_app": bool(row.in_app), "email": bool(row.email), "source": source}
    return out


def in_quiet(start: int, end: int, tz: str, now: Optional[datetime] = None) -> bool:
    """Is local time within [start, end) minutes after midnight? The window may wrap midnight (22:00-07:00);
    start == end is no window. An unknown time zone is treated as UTC rather than silencing or spamming."""
    if start == end:
        return False
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        zone = timezone.utc
    local = (now or datetime.now(timezone.utc)).astimezone(zone)
    minute = local.hour * 60 + local.minute
    return start <= minute < end if start < end else (minute >= start or minute < end)


async def get_quiet(org_id: str, user_id: Optional[str]) -> Optional[Dict[str, object]]:
    """The user's own quiet hours, else the organisation default, else None."""
    async with get_session_factory()() as session:
        rows = (await session.execute(select(NotificationQuietHours).where(
            NotificationQuietHours.org_id == org_id,
            NotificationQuietHours.user_id.in_([ORG_DEFAULT, user_id or ORG_DEFAULT])))).scalars().all()
    by = {r.user_id: r for r in rows}
    row = by.get(user_id or ORG_DEFAULT) or by.get(ORG_DEFAULT)
    if row is None:
        return None
    return {"start_minute": row.start_minute, "end_minute": row.end_minute, "tz": row.tz,
            "source": "user" if row.user_id else "org"}


async def set_quiet(org_id: str, user_id: str, start: int, end: int, tz: str) -> None:
    async with get_session_factory()() as session:
        row = (await session.execute(select(NotificationQuietHours).where(
            NotificationQuietHours.org_id == org_id, NotificationQuietHours.user_id == user_id))).scalar_one_or_none()
        if row is None:
            row = NotificationQuietHours(org_id=org_id, user_id=user_id, start_minute=start, end_minute=end, tz=tz)
            session.add(row)
        row.start_minute, row.end_minute, row.tz = start, end, tz
        await session.commit()


async def allows(org_id: str, user_id: Optional[str], event: str, channel: str, now: Optional[datetime] = None) -> bool:
    """May `event` reach this user on `channel` ('in_app' | 'email')? Unknown events are not filtered."""
    if event not in EVENTS:
        return True
    if not (await effective(org_id, user_id))[event][channel]:
        return False
    if channel == "email" and event not in QUIET_EXEMPT:
        q = await get_quiet(org_id, user_id)
        if q and in_quiet(q["start_minute"], q["end_minute"], q["tz"], now):
            return False
    return True


async def disabled_events(org_id: str, user_id: Optional[str], channel: str = "in_app") -> Tuple[str, ...]:
    return tuple(e for e, v in (await effective(org_id, user_id)).items() if not v[channel])


async def set_pref(org_id: str, user_id: str, event: str, in_app: Optional[bool], email: Optional[bool]) -> None:
    """Upsert one row; omitted channels keep what the row (or the default) already says."""
    async with get_session_factory()() as session:
        row = (await session.execute(select(NotificationPref).where(
            NotificationPref.org_id == org_id, NotificationPref.user_id == user_id,
            NotificationPref.event_type == event))).scalar_one_or_none()
        if row is None:
            row = NotificationPref(org_id=org_id, user_id=user_id, event_type=event, in_app=True, email=True)
            session.add(row)
        if in_app is not None:
            row.in_app = in_app
        if email is not None:
            row.email = email
        await session.commit()
