"""Prime — consent to learning (KAN-228): one switch per source plus an overall switch, per person, all off by default.

Owner decisions (22 Nov 2026) and the India DPDP Act 2023: notice, a stated purpose per source, opt-in consent,
and the rights to see, export and erase. Learned data is visible to the person alone (no manager or admin view);
it is never used in performance reviews; there is no keystroke, screen or idle tracking.

`allowed(org_id, user_id, source)` is THE check. Every collector (prime/collectors) and every read or write of
learned data (prime/learned.py) goes through it; tests/test_prime_consent_enforcement.py fails if one does not.
It fails closed: any error, an unknown source, or a person who is not active in that organisation means no.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.prime.models import PrimeConsent
from aether_os.prime.repository import person_in_org

logger = logging.getLogger(__name__)

SOURCES = ("git", "jira", "calendar", "attendance")
ALL = "all"
SWITCHES = (ALL, *SOURCES)

# Bump the version whenever the notice or a purpose changes: a consent records the version it was given under.
NOTICE_VERSION = "2026-11-22"
NOTICE = (
    "Prime can learn how you work so it can help you: draft your updates, suggest what to pick up next, and remind "
    "you of what is coming. It learns only from the sources you switch on below, and nothing is on until you turn it "
    "on. What it learns is shown to you alone: no manager or admin can see it, and it is never used in performance "
    "reviews. Prime does not track keystrokes, your screen or idle time. Turning a source off stops collection at "
    "once and deletes what was learned from it. You can export or erase everything at any time. Learned data is "
    "deleted automatically after your organisation's retention period."
)
PURPOSES: Dict[str, str] = {
    ALL: "Lets Prime learn from the sources you switch on below. Off: Prime learns nothing about you.",
    "git": "Your commits and pull requests (titles, repositories, times), to summarise your work and suggest "
           "related tasks. Code content is not stored.",
    "jira": "Tickets assigned to or created by you (keys, titles, status changes), to track what you are working "
            "on and draft updates.",
    "calendar": "The times and titles of your meetings, to find focus time and prepare reminders. Attendee lists "
                "and meeting notes are not stored.",
    "attendance": "Your check-in and check-out times and leave in Velaris, to help you plan work from home and "
                  "leave. Never used to judge your performance.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC, like the columns


async def _rows(org_id: str, user_id: str) -> Dict[str, PrimeConsent]:
    async with get_session_factory()() as session:
        rows = (await session.execute(select(PrimeConsent).where(
            PrimeConsent.org_id == org_id, PrimeConsent.user_id == user_id))).scalars().all()
    return {r.source: r for r in rows}


async def allowed(org_id: Optional[str], user_id: Optional[str], source: str) -> bool:
    """True only when this person, active in this organisation, has the overall switch AND this source on."""
    if source not in SOURCES or not org_id or not user_id:
        return False
    try:
        if not await person_in_org(org_id, user_id):
            return False
        rows = await _rows(org_id, user_id)
    except Exception as e:  # fail closed: no consent can be read, so nothing is collected or used
        logger.warning("prime consent: check failed for org %s: %s", org_id, type(e).__name__)
        return False
    return all(rows.get(s) is not None and rows[s].enabled for s in (ALL, source))


async def state(org_id: str, user_id: str) -> Dict[str, Any]:
    """The notice and every switch as the person sees it (off when never set)."""
    rows = await _rows(org_id, user_id)
    switches: List[Dict[str, Any]] = []
    for s in SWITCHES:
        r = rows.get(s)
        switches.append({
            "source": s, "enabled": bool(r and r.enabled), "purpose": PURPOSES[s],
            "enabled_at": r.enabled_at.isoformat() if r and r.enabled_at else None,
            "changed_at": r.changed_at.isoformat() if r else None,
            "notice_version": r.notice_version if r else None,
        })
    return {"notice": NOTICE, "notice_version": NOTICE_VERSION, "switches": switches}


async def set_switch(org_id: str, user_id: str, source: str, enabled: bool, by: str,
                     notice_version: str) -> List[str]:
    """Turn one switch on or off for this person. Only the person may (PermissionError). Turning one on needs the
    current notice version, i.e. the notice the person was shown (ValueError). Returns the sources whose learned
    data must now be deleted: the source turned off, or every source when the overall switch goes off (that also
    turns every source off, so nothing restarts silently when it is turned on again)."""
    if by != user_id:
        raise PermissionError("only the person can change their own consent")
    if source not in SWITCHES:
        raise ValueError(f"unknown source {source!r}")
    if enabled and notice_version != NOTICE_VERSION:
        raise ValueError("the notice has changed: read the current notice before switching this on")
    rows = await _rows(org_id, user_id)
    targets = list(SWITCHES) if source == ALL and not enabled else [source]
    changing = [s for s in targets if bool(rows.get(s) and rows[s].enabled) != enabled]
    if not changing:
        return []
    # Ledger first: consent must never change without a record of who changed it, when, and under which notice.
    await audit_chain.append(actor=by, action="prime.consent.change", payload={
        "org_id": org_id, "user_id": user_id, "sources": changing, "enabled": enabled,
        "notice_version": notice_version or NOTICE_VERSION})
    now = _now()
    async with get_session_factory()() as session:
        for s in changing:
            row = await session.get(PrimeConsent, (org_id, user_id, s))
            if row is None:
                row = PrimeConsent(org_id=org_id, user_id=user_id, source=s)
                session.add(row)
            row.enabled = enabled
            row.enabled_at = now if enabled else None
            row.changed_by, row.changed_at = by, now
            row.notice_version = notice_version if enabled else (row.notice_version or NOTICE_VERSION)
            row.purpose = PURPOSES[s]
        await session.commit()
    return [] if enabled else (list(SOURCES) if source == ALL else [source])
