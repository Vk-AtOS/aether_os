"""
User repository — CRUD helpers for the users table.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models import User, Tenant

logger = logging.getLogger(__name__)


def get_user_by_username(session: Session, username: str) -> Optional[User]:
    return session.query(User).filter(User.username == username).first()


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    return session.query(User).filter(User.email == email).first()


def get_user_by_id(session: Session, user_id: str) -> Optional[User]:
    return session.query(User).filter(User.id == user_id).first()


def create_user(
    session: Session,
    username: str,
    email: str,
    password_hash: str,
    tenant_id: Optional[str] = None,
    role: str = "member",
    display_name: Optional[str] = None,
) -> User:
    """Create and persist a new user. Caller is responsible for hashing the password."""
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        password_hash=password_hash,
        tenant_id=tenant_id,
        role=role,
        display_name=display_name or username,
        created_at=datetime.utcnow(),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def update_password(session: Session, user: User, new_hash: str) -> None:
    """Update a user's password hash in-place."""
    user.password_hash = new_hash
    session.commit()


def update_display_name(session: Session, user: User, name: str) -> None:
    """Update a user's display name."""
    user.display_name = name
    session.commit()


def upsert_admin_users() -> None:
    """
    Create the admin and demo users from env vars if they don't exist yet.
    Called once at app startup.
    """
    from src.database import SessionLocal
    from src.api.auth import hash_password

    admin_username = os.environ.get("DCSP_ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("DCSP_ADMIN_PASSWORD", "dcsp2024")
    admin_email = os.environ.get("DCSP_ADMIN_EMAIL", "admin@dcsp.local")

    demo_username = os.environ.get("DCSP_DEMO_USERNAME", "demo")
    demo_password = os.environ.get("DCSP_DEMO_PASSWORD", "demo123")
    demo_email = os.environ.get("DCSP_DEMO_EMAIL", "demo@dcsp.local")

    session = SessionLocal()
    try:
        # Ensure there is at least one tenant to attach users to
        default_tenant = session.query(Tenant).filter(Tenant.slug == "default").first()
        if not default_tenant:
            default_tenant = Tenant(
                id=str(uuid.uuid4()),
                name="Default",
                slug="default",
                plan="enterprise",
                created_at=datetime.utcnow(),
                is_active=True,
            )
            session.add(default_tenant)
            session.commit()
            session.refresh(default_tenant)

        for uname, pw, email, role in [
            (admin_username, admin_password, admin_email, "admin"),
            (demo_username, demo_password, demo_email, "member"),
        ]:
            existing = get_user_by_username(session, uname)
            if not existing:
                hashed = hash_password(pw)
                create_user(
                    session,
                    username=uname,
                    email=email,
                    password_hash=hashed,
                    tenant_id=default_tenant.id,
                    role=role,
                )
                logger.info("Created user '%s' (role=%s)", uname, role)
    except Exception as e:
        logger.error("upsert_admin_users failed: %s", e)
    finally:
        session.close()
