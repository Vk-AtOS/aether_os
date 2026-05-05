import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, Float, Boolean, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferences: Mapped[str] = mapped_column(Text, nullable=False) # JSON
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
