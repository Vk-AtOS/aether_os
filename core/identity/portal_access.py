"""AetherOS — client-portal access tokens and client approvals.

A portal token lets someone outside the organisation (the client) open one
project's portal. An org admin issues it; the plaintext is returned once and
only its SHA-256 is stored (the token is 256 random bits, so a fast hash is
enough and lookup stays a single indexed read). It expires, can be revoked, and
issue / revoke / use are ledgered.

A client approval is a row in portal_approvals plus a ledger entry: who (token
label or signed-in user), which project, when, and an optional comment.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Boolean, Float, String, Text, UniqueConstraint, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import Base, get_session_factory
from aether_os.core.spec_approval import decide_spec

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "aept_"
DEFAULT_TTL_DAYS = 30
MAX_TTL_DAYS = 90
# Reads by one token are ledgered once per this window; approve, feedback and download always.
_READ_LEDGER_WINDOW = 900


class PortalToken(Base):
    __tablename__ = "portal_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    revoked_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    revoked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_used_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class PortalApproval(Base):
    __tablename__ = "portal_approvals"
    # One actor's decisions form a chain: each row names the row it follows ("" for the
    # first). Two requests that read the same latest decision cannot both append.
    __table_args__ = (UniqueConstraint("project_id", "actor_kind", "actor_id", "prev_approval_id",
                                       name="uq_portal_approvals_actor_chain"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)   # "portal_token" | "user"
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)     # token id, or user id
    actor_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Set when this approval released a waiting pipeline gate (today: "spec_review").
    applied_to: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    prev_approval_id: Mapped[str] = mapped_column(String(48), nullable=False, default="", server_default="")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


def _status(row: PortalToken, now: float) -> str:
    return "revoked" if row.revoked_at else ("expired" if row.expires_at <= now else "active")


def _token_view(row: PortalToken, now: float) -> Dict[str, Any]:
    """What the owning org may see: never the hash, never the token."""
    return {
        "id": row.id, "project_id": row.project_id, "label": row.label, "status": _status(row, now),
        "created_by": row.created_by, "created_at": row.created_at, "expires_at": row.expires_at,
        "revoked_at": row.revoked_at, "revoked_by": row.revoked_by, "last_used_at": row.last_used_at,
    }


def _approval_view(row: PortalApproval) -> Dict[str, Any]:
    return {
        "id": row.id, "project_id": row.project_id, "approved": row.approved, "comment": row.comment,
        "actor_kind": row.actor_kind, "actor_id": row.actor_id, "actor_label": row.actor_label,
        "applied_to": row.applied_to, "created_at": row.created_at,
    }


async def _ledger(org_id: str, actor: str, action: str, project_id: str, metadata: Dict[str, Any]) -> None:
    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id=actor, action=action,
        resource_type="portal_project", resource_id=project_id, metadata=metadata)


async def issue_token(org_id: str, project_id: str, created_by: str, label: str = "",
                      ttl_days: int = DEFAULT_TTL_DAYS) -> Tuple[Dict[str, Any], str]:
    """Create a token for one project. Returns (public view, plaintext) — the only time the plaintext exists."""
    if not 1 <= ttl_days <= MAX_TTL_DAYS:
        raise ValueError(f"ttl_days must be between 1 and {MAX_TTL_DAYS}")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = time.time()
    row = PortalToken(org_id=org_id, project_id=project_id, token_hash=_hash(token), label=label[:120],
                      created_by=created_by, created_at=now, expires_at=now + ttl_days * 86400)
    async with get_session_factory()() as session:
        session.add(row)
        await session.commit()
    await _ledger(org_id, created_by, "portal.token_issued", project_id,
                  {"token_id": row.id, "label": row.label, "expires_at": row.expires_at})
    return _token_view(row, now), token


async def list_tokens(org_id: str, project_id: str) -> List[Dict[str, Any]]:
    now = time.time()
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(PortalToken).where(PortalToken.org_id == org_id, PortalToken.project_id == project_id)
            .order_by(PortalToken.created_at.desc()))).scalars().all()
    return [_token_view(r, now) for r in rows]


async def revoke_token(org_id: str, project_id: str, token_id: str, revoked_by: str) -> Optional[Dict[str, Any]]:
    """Revoke one token; None if the org has no such token on this project. Revoking twice is a no-op."""
    now = time.time()
    where = (PortalToken.id == token_id, PortalToken.org_id == org_id, PortalToken.project_id == project_id)
    async with get_session_factory()() as session:
        result = await session.execute(
            update(PortalToken).where(*where, PortalToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_by=revoked_by))
        await session.commit()
        row = (await session.execute(select(PortalToken).where(*where))).scalar_one_or_none()
    if row is None:
        return None
    if result.rowcount:  # ledger the revocation itself, not repeats of the request
        await _ledger(org_id, revoked_by, "portal.token_revoked", project_id, {"token_id": token_id, "label": row.label})
    return _token_view(row, now)


async def verify_token(project_id: str, supplied: str, method: str, route: str) -> Optional[Dict[str, Any]]:
    """The principal for a presented portal token, or None if it does not open this project now.

    Unknown, wrong project, revoked and expired are indistinguishable to the caller.
    """
    now = time.time()
    async with get_session_factory()() as session:
        row = (await session.execute(
            select(PortalToken).where(PortalToken.token_hash == _hash(supplied)))).scalar_one_or_none()
        if row is None or row.project_id != project_id or _status(row, now) != "active":
            return None
        previous_use = row.last_used_at
        row.last_used_at = now
        await session.commit()
    if method != "GET" or route == "download" or previous_use is None or now - previous_use > _READ_LEDGER_WINDOW:
        await _ledger(row.org_id, f"portal_token:{row.id}", "portal.token_used", project_id,
                      {"token_id": row.id, "label": row.label, "method": method, "route": route})
    return {"kind": "portal_token", "id": row.id, "label": row.label or f"portal token {row.id[:8]}",
            "org_id": row.org_id}


async def record_approval(project_id: str, principal: Dict[str, Any], approved: bool,
                          comment: Optional[str]) -> Tuple[Dict[str, Any], bool]:
    """Record the client's decision. Returns (approval, created).

    Idempotent: the same actor repeating their latest decision (same verdict and
    comment) gets that record back and nothing new is written or ledgered. Race-safe:
    each row names the decision it follows, under a unique constraint, so of two
    concurrent requests one inserts and the other re-reads and sees it.
    An approval given while the build waits at the spec-review gate releases it
    through core.spec_approval.decide_spec (ledgered like every other approver).
    """
    comment = (comment or "").strip() or None
    for _ in range(3):  # a lost race re-reads; three losses in a row means real contention
        try:
            return await _record_approval_once(project_id, principal, approved, comment)
        except IntegrityError as e:
            logger.info("portal approval for %s raced another request; re-reading: %s", project_id, e)
    raise RuntimeError("portal approval could not be recorded: concurrent updates kept conflicting")


async def _record_approval_once(project_id: str, principal: Dict[str, Any], approved: bool,
                                comment: Optional[str]) -> Tuple[Dict[str, Any], bool]:
    org_id, kind, actor_id = principal["org_id"], principal["kind"], principal["id"]
    async with get_session_factory()() as session:
        latest = (await session.execute(
            select(PortalApproval)
            .where(PortalApproval.project_id == project_id, PortalApproval.org_id == org_id,
                   PortalApproval.actor_kind == kind, PortalApproval.actor_id == actor_id)
            .order_by(PortalApproval.created_at.desc()).limit(1))).scalar_one_or_none()
        if latest is not None and latest.approved == approved and latest.comment == comment:
            return _approval_view(latest), False
        row = PortalApproval(org_id=org_id, project_id=project_id, approved=approved, comment=comment,
                             actor_kind=kind, actor_id=actor_id, actor_label=principal.get("label", "")[:255],
                             created_at=time.time(), prev_approval_id=latest.id if latest else "")
        session.add(row)
        await session.commit()   # claims this place in the actor's chain before the gate is touched
    if approved:
        outcome = await decide_spec(project_id, org_id, actor=f"{kind}:{actor_id}", via="client_portal",
                                    metadata={"approval_id": row.id, "actor_label": row.actor_label})
        if outcome == "approved":
            row.applied_to = "spec_review"
            async with get_session_factory()() as session:
                await session.execute(update(PortalApproval).where(PortalApproval.id == row.id)
                                      .values(applied_to=row.applied_to))
                await session.commit()
    await _ledger(org_id, f"{kind}:{actor_id}", "portal.client_approval", project_id, {
        "approval_id": row.id, "approved": approved, "comment": comment,
        "actor_label": row.actor_label, "applied_to": row.applied_to,
    })
    return _approval_view(row), True


async def list_approvals(org_id: str, project_id: str) -> List[Dict[str, Any]]:
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(PortalApproval).where(PortalApproval.org_id == org_id, PortalApproval.project_id == project_id)
            .order_by(PortalApproval.created_at.desc()))).scalars().all()
    return [_approval_view(r) for r in rows]
