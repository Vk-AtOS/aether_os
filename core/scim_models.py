"""SCIM Groups (KAN-163). Membership records for the IdP's groups; a group does not grant a role."""
from __future__ import annotations

import time
import uuid

from sqlalchemy import Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ScimGroup(Base):
    __tablename__ = "scim_groups"
    __table_args__ = (UniqueConstraint("org_id", "display_name", name="uq_scim_group_org_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ScimGroupMember(Base):
    __tablename__ = "scim_group_members"

    group_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
