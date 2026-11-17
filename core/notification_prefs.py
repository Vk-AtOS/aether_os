"""AetherOS — notification preferences: which events reach a user, in the app and by email.

Resolution for (org, user, event): the user's own row, else the organisation default row (user_id ''),
else on. The in-app list filters by this when it is read (so turning an event off also hides what already
exists); email is checked when it would be sent. Only events the product actually emits are listed.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import NotificationPref

EVENTS = {
    "run_completed": "A build finished",
    "run_failed": "A build failed",
    # Prime approvals (prime/reminders.py, prime/approvals.py): written as in-app Notification rows and e-mail.
    "approval_needed": "A request is waiting for your decision",
    "approval_expiring": "A request is about to expire",
    "approval_expired": "A request expired without a decision",
}
ORG_DEFAULT = ""


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


async def allows(org_id: str, user_id: Optional[str], event: str, channel: str) -> bool:
    """May `event` reach this user on `channel` ('in_app' | 'email')? Unknown events are not filtered."""
    if event not in EVENTS:
        return True
    return bool((await effective(org_id, user_id))[event][channel])


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
