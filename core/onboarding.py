"""AetherOS — organisation onboarding progress, derived from real data.

Steps are never stored as done: they are read from what exists (an LLM key, a run, a second member, a paid plan,
SSO, a chosen organisation name, an accepted DPA), so progress is the same on every browser and cannot be ticked
without doing the thing. Stored: the dismissal (one row per organisation, so one admin hiding the banner hides it for
everyone) and the DPA acceptance (who and when, for which version: it is a legal act, not a derivable fact).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import DateTime, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.db import Base, get_session_factory
from aether_os.core.models import OrgApiKey, Organisation, Run, SamlConfig, User

PAID_PLANS = ("starter", "pro", "enterprise")
DPA_VERSION = "1.0"     # the version GET /legal/dpa serves; accepting an older one does not count


class OnboardingDismissal(Base):
    __tablename__ = "org_onboarding"

    org_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    dismissed_by: Mapped[str] = mapped_column(String(36), nullable=False)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class DpaAcceptance(Base):
    __tablename__ = "org_dpa_acceptance"

    org_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    version: Mapped[str] = mapped_column(String(20), primary_key=True)
    accepted_by: Mapped[str] = mapped_column(String(36), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


async def _exists(session, query) -> bool:
    return (await session.execute(query.limit(1))).first() is not None


def name_is_set(name: str, emails: List[str]) -> bool:
    """Sign-up fills the name with the owner's address (OAuth, SAML) or its local part (no name typed): that
    placeholder is "not set". Anything else somebody chose counts as set."""
    n = (name or "").strip().lower()
    return bool(n) and n not in {e.lower() for e in emails} and n not in {e.split("@")[0].lower() for e in emails}


async def progress(org_id: str) -> Dict[str, Any]:
    async with get_session_factory()() as session:
        llm_key = await _exists(session, select(OrgApiKey.id).where(OrgApiKey.org_id == org_id))
        first_run = await _exists(session, select(Run.id).where(Run.org_id == org_id))
        members = (await session.execute(select(func.count()).select_from(User).where(
            User.org_id == org_id, User.is_active.is_(True)))).scalar() or 0
        plan = (await session.execute(select(Organisation.plan).where(Organisation.id == org_id))).scalar()
        sso = await _exists(session, select(SamlConfig.id).where(SamlConfig.org_id == org_id))
        name = (await session.execute(select(Organisation.name).where(Organisation.id == org_id))).scalar() or ""
        emails = (await session.execute(select(User.email).where(User.org_id == org_id))).scalars().all()
        dpa = await _exists(session, select(DpaAcceptance.org_id).where(
            DpaAcceptance.org_id == org_id, DpaAcceptance.version == DPA_VERSION))
        dismissed = await _exists(session, select(OnboardingDismissal.org_id).where(OnboardingDismissal.org_id == org_id))
    steps: List[Dict[str, Any]] = [
        {"id": "org_name", "title": "Name your organisation", "done": name_is_set(name, emails), "required": True, "link": "/settings"},
        {"id": "dpa", "title": "Accept the data processing agreement", "done": dpa, "required": True, "link": "/legal?doc=dpa"},
        {"id": "llm_key", "title": "Add an LLM API key", "done": llm_key, "required": True, "link": "/settings"},
        {"id": "first_run", "title": "Run your first pipeline", "done": first_run, "required": True, "link": "/new"},
        {"id": "invite_team", "title": "Invite a teammate", "done": members > 1, "required": True, "link": "/admin/users"},
        {"id": "plan", "title": "Pick a plan", "done": plan in PAID_PLANS, "required": False, "link": "/admin/billing"},
        {"id": "sso", "title": "Connect single sign-on", "done": sso, "required": False, "link": "/settings/sso"},
    ]
    return {"steps": steps, "dismissed": dismissed,
            "complete": all(s["done"] for s in steps if s["required"])}


async def dismiss(org_id: str, user_id: str) -> None:
    async with get_session_factory()() as session:
        if not await _exists(session, select(OnboardingDismissal.org_id).where(OnboardingDismissal.org_id == org_id)):
            session.add(OnboardingDismissal(org_id=org_id, dismissed_by=user_id))
            await session.commit()


async def accept_dpa(org_id: str, user_id: str) -> None:
    """Record that this user accepted the current DPA for the organisation. The first acceptance stays (who and
    when are evidence); accepting again changes nothing."""
    async with get_session_factory()() as session:
        if not await _exists(session, select(DpaAcceptance.org_id).where(
                DpaAcceptance.org_id == org_id, DpaAcceptance.version == DPA_VERSION)):
            session.add(DpaAcceptance(org_id=org_id, version=DPA_VERSION, accepted_by=user_id))
            await session.commit()
