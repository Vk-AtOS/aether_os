"""
AetherOS — Unified Async Database Layer
Merged from DCSP/src/database.py (schema) + Aether-one/aetherone/db.py (async setup).
Uses SQLAlchemy async + aiosqlite for local dev; PostgreSQL optional via env.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


class Base(DeclarativeBase):
    """Shared declarative base for all AetherOS ORM models."""
    pass


def _build_db_url() -> str:
    """
    Build the database URL from environment or config.
    PostgreSQL if DATABASE_URL is set; SQLite otherwise.
    """
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Ensure asyncpg driver for postgres
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        return db_url

    # Default: SQLite with aiosqlite
    from .config.loader import get_config
    from pathlib import Path as _Path
    (_Path.home() / ".aether_os").mkdir(parents=True, exist_ok=True)
    
    db_path_raw = get_config().get("database.path", str(_Path.home() / ".aether_os" / "aether_os.db"))
    db_path = _Path(db_path_raw).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"


def get_engine() -> AsyncEngine:
    """Return the global async engine (lazy init)."""
    global _engine
    if _engine is None:
        url = _build_db_url()
        echo = os.environ.get("DB_ECHO", "false").lower() == "true"
        connect_args = {}
        if "sqlite" in url:
            connect_args = {"check_same_thread": False}
        _engine = create_async_engine(url, echo=echo, connect_args=connect_args)
        logger.info("Database engine initialised: %s", url.split("@")[-1] if "@" in url else url)
    return _engine


def get_session_factory() -> async_sessionmaker:
    """Return the async session factory (lazy init)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields an async DB session per request.
    Usage: db: AsyncSession = Depends(get_db)
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables. Call on application startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialised")


async def close_db() -> None:
    """Dispose engine connections. Call on application shutdown."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    logger.info("Database connections closed")
