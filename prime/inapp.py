"""In-app notices for Prime approvals (KAN-26, KAN-159). Own module: approvals.py and reminders.py both use it."""
from __future__ import annotations

import logging
from typing import List, Tuple

from sqlalchemy import or_, select

from aether_os.core.db import get_session_factory
from aether_os.core.models import Notification, User
from aether_os.prime.authz import PRIME

logger = logging.getLogger(__name__)


async def recipients(org_id: str, people: List[str]) -> List[Tuple[str, str]]:
    """(user id, email) of these people (ids or emails) in this organisation; unknown ones are skipped."""
    wanted = [p for p in dict.fromkeys(people) if p and p != PRIME and not p.startswith("system:")]
    if not wanted:
        return []
    async with get_session_factory()() as session:
        rows = (await session.execute(select(User.id, User.email).where(
            User.org_id == org_id, User.is_active == True,  # noqa: E712
            or_(User.id.in_(wanted), User.email.in_([w.lower() for w in wanted]))))).all()
    return sorted({(r[0], r[1]) for r in rows})


async def notify_in_app(org_id: str, people: List[str], event: str, title: str, text: str) -> int:
    """One in-app Notification per person (KAN-26: the notice used to be email only). `event` is a key of
    notification_prefs.EVENTS, so a person's own switch hides it. Never raises: the request itself matters more."""
    try:
        who = await recipients(org_id, people)
        if not who:
            return 0
        async with get_session_factory()() as session:
            for uid, _email_addr in who:
                session.add(Notification(org_id=org_id, user_id=uid, type=event, title=title[:255], message=text,
                                         link="/prime/inbox"))
            await session.commit()
        return len(who)
    except Exception as e:
        logger.warning("prime: in-app notice could not be stored: %s", type(e).__name__)
        return 0


