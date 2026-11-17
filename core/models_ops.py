"""Operational tables that are not part of the product data model (kept out of models.py, which is over the line limit).

Imported by core/models.py so every table is on Base.metadata wherever the models are.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from sqlalchemy import Float, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class WebhookOutbox(Base):
    """One webhook delivery that must survive a restart: pending -> done, or dead after the bounded retries.
    The signing secret and URL are NOT copied here; they are read from the webhook row at send time."""
    __tablename__ = "webhook_outbox"
    __table_args__ = (Index("ix_webhook_outbox_due", "status", "next_attempt_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    webhook_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)


class LlmDailyUsage(Base):
    """Estimated model spend of one organisation for one UTC day. The monthly record (token_budget_records) cannot say
    HOW FAST money is spent; this is what stops a looping agent from burning a whole month in a day."""
    __tablename__ = "llm_daily_usage"
    __table_args__ = (UniqueConstraint("org_id", "day", name="uq_llm_daily_usage"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False)      # YYYY-MM-DD (UTC)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class NotificationQuietHours(Base):
    """A person's quiet hours: e-mail is held back between start and end (local time of `tz`). user_id '' is the
    organisation default. Start == end means no quiet hours."""
    __tablename__ = "notification_quiet_hours"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_notification_quiet_hours"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)   # minutes after local midnight, 0..1439
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    tz: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
