"""Prime — ORM storage: delegations, organisation limits, requests (conventions follow core/models.py)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.db import Base
from aether_os.core.models import _utcnow


class PrimeDelegation(Base):
    __tablename__ = "prime_delegations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    grantor: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    deputy: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    # Decimal kept as text so the limit round-trips exactly on every backend.
    max_amount: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    autonomy: Mapped[int] = mapped_column(Integer, nullable=False)
    # Naive UTC, like every other DateTime column in this codebase.
    valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PrimeOrgLimits(Base):
    """Per-organisation Prime limits. No row means the defaults in prime/authz.py."""
    __tablename__ = "prime_org_limits"

    org_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    payment_ceiling: Mapped[str] = mapped_column(String(32), nullable=False)
    max_delegation_days: Mapped[int] = mapped_column(Integer, nullable=False)
    request_ttl_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=72,
                                                   server_default=text("72"))
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PrimeRequest(Base):
    """An action Prime was asked to carry out that reached a person or an executor.

    status:      pending | approved | rejected   (pending past expires_at reads as expired)
    exec_status: NULL | running | succeeded | failed | needs_attention
    """
    __tablename__ = "prime_requests"
    __table_args__ = (Index("ix_prime_requests_status_expires", "status", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    on_behalf_of: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    params: Mapped[dict] = mapped_column(JSON, nullable=False)
    executor: Mapped[str] = mapped_column(String(64), nullable=False)
    delegation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    deputy: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Hash of everything above plus expires_at. Unique: it is also the idempotency key.
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    exec_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    exec_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exec_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Edits (KAN-22): 0 = as submitted. Each edit bumps it and changes request_hash; edited_by
    # lists everyone who changed the request, none of whom may decide it.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    edited_by: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Set once by whichever worker claims it (UPDATE ... WHERE NULL), so a reminder or an
    # expiry notice goes out at most once however many workers run the sweep.
    reminded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expiry_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PrimeCorrection(Base):
    """What a person changed or refused before approving (KAN-24): the agent's proposal, the
    correction and why. Personal data is pseudonymised before it is stored; every row belongs
    to one organisation and is never read across organisations."""
    __tablename__ = "prime_corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    agent: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # request id + revision (or "reject"): the same edit or rejection is stored once.
    ref: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    proposed: Mapped[str] = mapped_column(Text, nullable=False)
    corrected: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approver_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # People it concerns, for erasure (erase_person): the person acted for, the requester, the corrector.
    on_behalf_of: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    corrected_by: Mapped[str] = mapped_column(String(255), nullable=False)
    # In the agent's eval set (KAN-25). True for every new correction (owner decision); a human removes one with False.
    good_example: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=false())
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    changed_outcome_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                                       server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_prime_corrections_lookup", "org_id", "agent", "action_type"),)
