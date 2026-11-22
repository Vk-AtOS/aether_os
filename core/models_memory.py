"""Structured run memory (KAN-215): repair fixes keyed by a normalised error signature, and typed per-run patterns.

Split out of core/models.py (600-line rule); imported there so the tables are on Base.metadata. Every row carries
org_id and every query in core/fix_memory.py filters by it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FixMemory(Base):
    """A repair that worked: {error_signature, file_kind, patches}. Dropped once it fails twice (core/fix_memory.py)."""
    __tablename__ = "fix_memory"
    __table_args__ = (UniqueConstraint("org_id", "signature", name="uq_fix_memory_org_signature"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    patches: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Provenance, so a bad row can be audited and deleted (core/fix_memory.purge_run).
    run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, default="system")
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RunPatternMemory(Base):
    """What a finished run chose: domain, entity names, patterns. Retrieved by key (domain, entity names)."""
    __tablename__ = "run_pattern_memory"
    __table_args__ = (UniqueConstraint("org_id", "run_id", name="uq_run_pattern_memory_org_run"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    entities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    patterns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
