"""Prime — ORM storage for delegations (conventions follow core/models.py)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, DateTime, Integer, String
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
