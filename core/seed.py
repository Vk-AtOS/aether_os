"""
Startup seed — idempotent data seeding run on every application startup.

Functions:
  ensure_demo_user()     — creates demo@aetheros.ai org+user if absent
  ensure_marketplace()   — seeds built-in marketplace skills if count < 5
"""
from __future__ import annotations

import logging
import os
import uuid

logger = logging.getLogger(__name__)


async def ensure_demo_user() -> None:
    """
    Creates demo org + admin user if missing.
    Reads AETHER_ADMIN_EMAIL / AETHER_ADMIN_PASS from environment.
    Survives Guardian pg_restore cycles because it runs after every startup.
    """
    import bcrypt
    from sqlalchemy import select
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User, Organisation

    email = os.environ.get("AETHER_ADMIN_EMAIL", "demo@aetheros.ai")
    password = os.environ.get("AETHER_ADMIN_PASS", "demo1234")
    org_id = "org_demo_aetheros_ai"

    sf = get_session_factory()
    async with sf() as session:
        existing = (await session.execute(
            select(User).where(User.email == email)
        )).scalars().first()

        if existing is not None:
            return

        org = (await session.execute(
            select(Organisation).where(Organisation.id == org_id)
        )).scalars().first()

        if org is None:
            session.add(Organisation(
                id=org_id,
                name="AetherOS Demo",
                slug="aetheros-demo",
                plan="pro",
                trial_runs_limit=999,
            ))

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        session.add(User(
            id=str(uuid.uuid4()),
            org_id=org_id,
            email=email,
            password_hash=pw_hash,
            role="admin",
            is_active=True,
            email_verified=True,
        ))
        await session.commit()
        logger.info("Seed: created demo admin user %s", email)


_BUILTIN_SKILLS = [
    ("JWT Authentication", "auth", "Full JWT auth with refresh tokens, bcrypt hashing, and role-based access control"),
    ("CRUD Operations", "general", "Generic SQLAlchemy CRUD endpoints with filtering, pagination, and soft deletes"),
    ("Stripe Payments", "payments", "Stripe checkout, subscription management, webhook handler, and invoice generation"),
    ("Email Service", "general", "SMTP/SendGrid email sender with templating, queue, and delivery tracking"),
    ("Full-text Search", "general", "PostgreSQL full-text search with ranking, facets, and autocomplete"),
    ("File Upload", "general", "S3/local file upload with thumbnail generation and CDN URLs"),
    ("Push Notifications", "general", "Firebase FCM push notifications with topic subscriptions and delivery receipts"),
    ("Analytics Events", "general", "Event tracking pipeline with aggregation, funnel analysis, and retention metrics"),
    ("Admin Dashboard", "admin", "Role-gated admin panel with user management, audit log, and bulk actions"),
    ("Internationalisation", "general", "i18n middleware with locale detection, message catalogs, and date/number formatting"),
]


async def ensure_marketplace() -> None:
    """Seeds built-in marketplace skills if fewer than 5 exist."""
    from sqlalchemy import select, func
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import MarketplaceProfile

    sf = get_session_factory()
    async with sf() as session:
        count = (await session.execute(
            select(func.count()).select_from(MarketplaceProfile)
        )).scalar()

        if count >= 5:
            return

        for name, domain, description in _BUILTIN_SKILLS:
            existing = (await session.execute(
                select(MarketplaceProfile)
                .where(MarketplaceProfile.name == name)
                .where(MarketplaceProfile.org_id == "system")
            )).scalars().first()
            if existing:
                continue
            session.add(MarketplaceProfile(
                id=str(uuid.uuid4()),
                org_id="system",
                name=name,
                base_domain=domain,
                description=description,
                profile_yaml=f"name: {name}\ndomain: {domain}\ndescription: {description}\n",
                is_published=True,
                usage_count=0,
            ))

        await session.commit()
        logger.info("Seed: marketplace seeded with %d built-in skills", len(_BUILTIN_SKILLS))
