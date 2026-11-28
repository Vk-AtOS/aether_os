"""bootstrap.py for the generated backend (KAN-267): what happens at startup, by environment.

The generated app used to run ``create_all`` and a seed that created ``admin@example.com`` on every start, whatever
the environment. This module is the one place that decides:

  * ENVIRONMENT=production: the schema comes from ``alembic upgrade head`` (the container entrypoint runs it);
    startup never creates tables and refuses a missing migration, a weak or default ADMIN_PASSWORD.
  * anything else (development / test): tables are created for convenience.
  * the first admin exists only when ADMIN_EMAIL and ADMIN_PASSWORD are both set; no password is built in.
  * demo rows only when SEED_DEMO_DATA=true.
"""
from __future__ import annotations

_BOOTSTRAP_PY = '''\
"""Startup policy: schema, first admin, demo data (see the generator's templates_bootstrap.py)."""
from __future__ import annotations
import logging
import os

from sqlalchemy import select, text

logger = logging.getLogger(__name__)

MIN_ADMIN_PASSWORD_LENGTH = 12
# Placeholders and well-known defaults that must never protect a production admin account.
KNOWN_DEFAULT_PASSWORDS = frozenset({
    "change-me", "change_me", "changeme", "password", "admin", "admin123", "password123", "demo1234", "secret",
    "123456", "12345678", "123456789", "qwerty", "letmein", "welcome", "test", "example",
})


def environment() -> str:
    return os.environ.get("ENVIRONMENT", "development").strip().lower()


def is_production() -> bool:
    return environment() == "production"


def seed_demo_enabled() -> bool:
    return os.environ.get("SEED_DEMO_DATA", "false").strip().lower() in ("1", "true", "yes")


def validate_production_settings() -> None:
    """Fail fast, with the reason, when a production start would be unsafe."""
    if not os.environ.get("DATABASE_URL", "").strip():
        raise RuntimeError("DATABASE_URL is required in production (for example postgresql+asyncpg://user:pass@host/db)")
    password = os.environ.get("ADMIN_PASSWORD", "")
    if password and (password.lower() in KNOWN_DEFAULT_PASSWORDS or len(password) < MIN_ADMIN_PASSWORD_LENGTH):
        raise RuntimeError(
            f"ADMIN_PASSWORD is a known default or shorter than {MIN_ADMIN_PASSWORD_LENGTH} characters: "
            "set a strong ADMIN_PASSWORD (or unset it and create the admin another way)")
    if password and not os.environ.get("ADMIN_EMAIL", "").strip():
        raise RuntimeError("ADMIN_PASSWORD is set but ADMIN_EMAIL is not: set both to create the first admin")
    if os.environ.get("SEED_DEMO_DATA", "").strip().lower() in ("1", "true", "yes"):
        logger.warning("SEED_DEMO_DATA=true in production: demo rows will be written to the production database")


async def _require_migrated(engine) -> None:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT version_num FROM alembic_version"))
    except Exception as exc:
        raise RuntimeError("the database has no migrations applied: run `alembic upgrade head` before starting "
                           "(the container entrypoint does this)") from exc


async def ensure_admin(db):
    """Return the admin named by ADMIN_EMAIL, creating it from ADMIN_PASSWORD when it does not exist yet.

    Returns None when ADMIN_EMAIL / ADMIN_PASSWORD are not both set: there is no built-in admin.
    """
    from auth import get_password_hash
    from models import User
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        return None
    admin = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if admin is not None:
        return admin
    fields = {"email": email, "password_hash": get_password_hash(password), "role": "admin", "is_active": True}
    if hasattr(User, "org_id"):
        fields["org_id"] = "default"
    admin = User(**fields)
    db.add(admin)
    await db.commit()
    logger.info("Created the first admin %s from ADMIN_EMAIL / ADMIN_PASSWORD", email)
    return admin


async def run_startup(engine, base) -> None:
    """Called from the app lifespan."""
    from database import AsyncSessionLocal
    if is_production():
        validate_production_settings()
        await _require_migrated(engine)
    else:
        async with engine.begin() as conn:      # development / test convenience only; production uses alembic
            await conn.run_sync(base.metadata.create_all)
    try:
        async with AsyncSessionLocal() as db:
            if await ensure_admin(db) is None:
                logger.warning("No admin created: set ADMIN_EMAIL and ADMIN_PASSWORD to create the first admin")
    except Exception as exc:
        if is_production():
            raise
        logger.warning("Admin bootstrap skipped: %s", exc)
    if seed_demo_enabled():
        try:
            from seed import seed_database
            await seed_database()
            logger.info("Demo data seeded (SEED_DEMO_DATA=true)")
        except Exception as exc:
            logger.warning("Demo seed skipped: %s", exc)
'''
