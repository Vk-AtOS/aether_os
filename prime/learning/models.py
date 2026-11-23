"""Prime learning loop (KAN-229): one record of every time a learned item was put into a prompt, whether it helped,
and which items are retired. The learned items themselves stay in their own tables (prime_corrections,
golden_builds, fix_memory); these tables only point at them by (org_id, kind, item_id).

Organisation-level data: no person is named here. Every row carries org_id and every query filters by it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint, false, text
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.db import Base
from aether_os.core.models import _utcnow


class LearningUse(Base):
    """A learned item was put into a prompt (or a stored fix was replayed). `helped` stays NULL until the outcome
    is known: approval unchanged, build passed, fix applied cleanly."""
    __tablename__ = "learning_uses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)          # correction | golden | fix
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(200), nullable=False, default="")   # agent:action_type, phase, file kind
    ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # the run it was used in, when there is one
    used_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    helped: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_learning_uses_org_kind_item", "org_id", "kind", "item_id"),
                      Index("ix_learning_uses_org_used_at", "org_id", "used_at"))


class LearningItemState(Base):
    """Retirement of one learned item in one organisation. A retired item is no longer put into prompts.
    `failures` counts outcomes in a row that did not help; it is reset by a helpful outcome and by a restore."""
    __tablename__ = "learning_item_state"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    retired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retired_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)   # "prime" or the admin's user id
    retired_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (UniqueConstraint("org_id", "kind", "item_id", name="uq_learning_item_state_item"),)


class LearningBuildOutcome(Base):
    """How a run's frontend build went (first round green or not): the build first-pass trend."""
    __tablename__ = "learning_build_outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    built: Mapped[bool] = mapped_column(Boolean, nullable=False)
    first_pass: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
