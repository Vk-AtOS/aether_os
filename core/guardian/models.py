"""Guardian DB models — threat events and snapshot registry."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, Text, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from aether_os.core.db import Base


class GuardianEvent(Base):
    __tablename__ = "guardian_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # brute_force | sql_injection | rate_breach | file_tamper | service_crash | anomaly | recovery
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # low | medium | high | critical
    source_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    endpoint: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    org_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class GuardianSnapshot(Base):
    __tablename__ = "guardian_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    snapshot_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # SHA-256 of the dump file for tamper detection
    trigger: Mapped[str] = mapped_column(String(30), default="scheduled")
    # scheduled | manual | pre_threat | post_recovery
    status: Mapped[str] = mapped_column(String(20), default="ok")
    # ok | restoring | restored | failed
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    db_backend: Mapped[str] = mapped_column(String(20), default="sqlite")
    # postgresql | sqlite
