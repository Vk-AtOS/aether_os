"""Fixed production file templates for the generated FastAPI backend.

These are static strings written verbatim into the generated app's src/ directory.
No LLM involvement — pure deterministic output.

Larger application-level templates (main.py, alembic, Dockerfile, requirements)
and their builder functions live in templates_main.py and are re-exported here
so all existing imports continue to work.
"""
from __future__ import annotations

# Re-export everything from templates_main so callers can import from either module.
from aether_os.phases.p04a_backend_codegen.templates_main import (  # noqa: F401
    _MAIN_PY_TEMPLATE,
    _ROUTERS_INIT_PY,
    _REQUIREMENTS_TXT,
    _DOCKERFILE,
    _ALEMBIC_INI,
    _ALEMBIC_ENV_PY,
    _ALEMBIC_SCRIPT_PY_MAKO,
    _SERVICES_INIT_PY,
    _build_main_py,
    _generate_makefile,
    _generate_backend_readme,
    write_alembic_scaffold,
    patch_main_py,
)

from aether_os.phases.p04a_backend_codegen.templates_auth import _AUTH_PY, _AUTH_ROUTER_PY, _RATE_LIMITER_PY  # noqa: F401,E402

# ── Fixed production templates ─────────────────────────────────────────────────

_DATABASE_PY = '''\
"""Async SQLAlchemy engine + session factory.

PostgreSQL is the production default (asyncpg driver).
SQLite with aiosqlite is supported as a local-dev fallback when DATABASE_URL starts with 'sqlite'.
"""
from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# No default: a built-in URL with a well-known password would let the app start against whatever
# database answers on localhost. The generated .env sets SQLite for local development.
_RAW_URL = os.environ.get("DATABASE_URL", "").strip()
if not _RAW_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Set it in the environment or in .env "
        "(local development: sqlite+aiosqlite:///./app.db)."
    )

# Normalise the driver suffix so the correct async driver is always used.
if _RAW_URL.startswith("sqlite"):
    # SQLite path: ensure aiosqlite driver prefix
    if _RAW_URL.startswith("sqlite:///") and "+aiosqlite" not in _RAW_URL:
        DATABASE_URL = _RAW_URL.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    else:
        DATABASE_URL = _RAW_URL
elif _RAW_URL.startswith("postgresql"):
    # PostgreSQL path: ensure asyncpg driver prefix
    if "+asyncpg" not in _RAW_URL:
        DATABASE_URL = _RAW_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        DATABASE_URL = _RAW_URL
else:
    DATABASE_URL = _RAW_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    from sqlalchemy.pool import NullPool as _NullPool
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        hide_parameters=True,   # a failing INSERT must not put the admin's password hash in logs or tracebacks
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
        poolclass=_NullPool,
    )
else:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        hide_parameters=True,   # a failing INSERT must not put the admin's password hash in logs or tracebacks
        pool_pre_ping=True,
        pool_size=int(os.environ.get("DB_POOL_SIZE", str(max(4, (os.cpu_count() or 1) * 2)))),
        max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "20")),
        pool_recycle=300,
        # asyncpg has no `options` argument (it raised TypeError); server settings are how it sets the timeout
        connect_args={"server_settings": {"statement_timeout": "30000"}},
    )
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
'''

_CONFIG_PY = '''\
"""Application settings loaded from environment variables."""
from __future__ import annotations
import os
from functools import lru_cache


class Settings:
    app_name: str = os.environ.get("APP_NAME", "API")
    environment: str = os.environ.get("ENVIRONMENT", "development")
    database_url: str = os.environ.get("DATABASE_URL", "")   # required: database.py refuses to start without it
    secret_key: str = os.environ.get("SECRET_KEY", "")
    # CORS_ORIGINS must be set explicitly — no wildcard default (security hardening)
    cors_origins: list[str] = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]
    debug: bool = os.environ.get("DEBUG", "false").lower() == "true"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
'''

# Standalone cache.py template written to src/cache.py of the generated app.
# Provides no-op fallback so CRUD works identically when REDIS_URL is unset.
_REDIS_CACHE_PY = '''\
"""Redis cache helpers — generated by AetherOS.

Gracefully falls back to no-op when REDIS_URL is not set, so CRUD works
identically in environments without Redis.

Usage:
    from cache import cache_get, cache_set, cache_delete
"""
import os
import json
import hashlib
import logging

logger = logging.getLogger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "")
_cache = None


async def get_cache():
    """Return a live aioredis client, or None when Redis is unavailable."""
    global _cache
    if not _REDIS_URL:
        return None
    if _cache is None:
        try:
            import redis.asyncio as aioredis
            _cache = aioredis.from_url(_REDIS_URL, decode_responses=True)
            await _cache.ping()
        except Exception as exc:
            logger.warning("[cache] Redis unavailable — running without cache: %s", exc)
            _cache = None
    return _cache


async def cache_get(key: str):
    """Return cached value or None on miss / Redis down."""
    r = await get_cache()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        logger.warning("[cache] cache_get failed (non-fatal): %s", exc)
        return None


async def cache_set(key: str, value, ttl: int = 30):
    """Store value in Redis with ttl-second expiry. No-op if Redis is down."""
    r = await get_cache()
    if r is None:
        return
    try:
        await r.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:
        logger.warning("[cache] cache_set failed (non-fatal): %s", exc)


async def cache_delete(key: str):
    """Invalidate a single cached key. No-op if Redis is down."""
    r = await get_cache()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception as exc:
        logger.warning("[cache] cache_delete failed (non-fatal): %s", exc)


async def cache_delete_pattern(pattern: str):
    """Invalidate all keys matching a glob pattern using Redis SCAN.

    r.delete() treats its argument as a literal key — the '*' is never expanded.
    SCAN iterates the keyspace and batch-deletes matching keys so cache
    invalidation on list endpoints works correctly under high traffic.
    """
    r = await get_cache()
    if r is None:
        return
    try:
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=pattern, count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("[cache] cache_delete_pattern failed (non-fatal): %s", exc)
'''

