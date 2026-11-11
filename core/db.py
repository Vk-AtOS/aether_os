"""
AetherOS — Unified Async Database Layer
Uses SQLAlchemy async + aiosqlite for local dev; PostgreSQL via DATABASE_URL env var.

Key improvements over original:
- WAL mode enabled for SQLite (critical: allows concurrent readers + 1 writer without locking)
- Connection pool tuned for 80K users (PostgreSQL: pool_size=20, max_overflow=40)
- All sync sqlite3.connect() calls replaced with async ORM throughout the codebase
- Indexes on org_id, email, status added via create_all + explicit DDL
"""
from __future__ import annotations
import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event, text
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
    db_path = Path.home() / ".aether_os" / "aether_os.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"


def get_engine() -> AsyncEngine:
    """Return the global async engine (lazy init)."""
    global _engine
    if _engine is None:
        url = _build_db_url()
        echo = os.environ.get("DB_ECHO", "false").lower() == "true"

        is_sqlite = "sqlite" in url
        is_postgres = "postgresql" in url or "asyncpg" in url

        connect_args: dict = {}
        engine_kwargs: dict = {"echo": echo}

        if is_sqlite:
            connect_args = {"check_same_thread": False}
            # SQLite: single writer, no pool needed — use StaticPool to avoid
            # "ProgrammingError: Cannot operate on a closed database" under asyncio
            from sqlalchemy.pool import NullPool
            engine_kwargs["poolclass"] = NullPool
            engine_kwargs["connect_args"] = connect_args

        elif is_postgres:
            # T3-04: pool_size per worker must fit within PG max_connections.
            # With WORKERS=8 (default): 8 × (pool_size + max_overflow) ≤ max_connections.
            # DB_POOL_SIZE default=3 → 8×(3+7)=80 connections, safe under PG default of 100.
            # Use PgBouncer in production to allow larger effective concurrency.
            _pool_size = int(os.environ.get("DB_POOL_SIZE", "3"))
            _max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "7"))
            engine_kwargs.update({
                "pool_size": _pool_size,
                "max_overflow": _max_overflow,
                "pool_timeout": 30,
                "pool_recycle": 300,    # recycle every 5 min — cloud DBs drop idle conns
                "pool_pre_ping": True,  # test conn before use; prevents "closed conn" 500s
                # Hard cap per-query so a runaway query can't starve the pool (30 s)
                # asyncpg uses server_settings dict, not psycopg2's options string
                "connect_args": {"server_settings": {"statement_timeout": "30000"}},
            })

        _engine = create_async_engine(url, **engine_kwargs)

        if is_sqlite:
            # Enable WAL mode synchronously on the underlying sync driver.
            # WAL is critical: without it, concurrent readers block on writes,
            # causing timeouts at scale. WAL allows unlimited concurrent reads.
            @event.listens_for(_engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, _connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")   # faster than FULL, safe with WAL
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA cache_size=-64000")    # 64MB page cache
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.close()

        logger.info(
            "Database engine initialised: %s",
            url.split("@")[-1] if "@" in url else url,
        )
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
        except Exception as e:
            logger.warning("db session error, rolling back: %s", e)
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Create all tables and indexes. Called on application startup.

    Indexes created here match the query patterns in api.py and the pipeline:
    - org_id: nearly every query filters by org
    - email: login lookup (User.email)
    - status: dashboard listing filters by status
    - run_metadata.run_id: priority lookups are per-run
    """
    from . import models  # Ensure all models are registered with Base
    from .billing import payments  # noqa: F401  registers billing_payments for callers that never load the gateway
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Add indexes that aren't defined on the ORM models themselves.
        # IF NOT EXISTS is safe to run repeatedly on every startup.
        index_ddl = [
            # Core lookup indexes
            "CREATE INDEX IF NOT EXISTS ix_runs_org_id           ON runs(org_id)",
            "CREATE INDEX IF NOT EXISTS ix_runs_status           ON runs(status)",
            "CREATE INDEX IF NOT EXISTS ix_runs_started_at       ON runs(started_at)",
            "CREATE INDEX IF NOT EXISTS ix_users_email           ON users(email)",
            "CREATE INDEX IF NOT EXISTS ix_users_org_id          ON users(org_id)",
            "CREATE INDEX IF NOT EXISTS ix_api_keys_org_id       ON api_keys(org_id)",
            "CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash     ON api_keys(key_hash)",
            "CREATE INDEX IF NOT EXISTS ix_phase_completions_run ON phase_completions(run_id, phase_name)",
            # FK indexes on high-traffic join columns (prevent full table scans)
            "CREATE INDEX IF NOT EXISTS ix_events_run_id         ON events(run_id)",
            "CREATE INDEX IF NOT EXISTS ix_snapshots_run_id      ON snapshots(run_id)",
            "CREATE INDEX IF NOT EXISTS ix_decisions_org_id      ON decisions(org_id)",
            "CREATE INDEX IF NOT EXISTS ix_decisions_run_id      ON decisions(run_id)",
            "CREATE INDEX IF NOT EXISTS ix_audit_log_org_id      ON audit_log(org_id)",
            "CREATE INDEX IF NOT EXISTS ix_audit_log_created_at  ON audit_log(created_at)",
            "CREATE INDEX IF NOT EXISTS ix_webhooks_org_id       ON webhooks(org_id)",
            "CREATE INDEX IF NOT EXISTS ix_workspaces_org_id     ON workspaces(org_id)",
            # Learning loop isolation — both filters required on every query
            "CREATE INDEX IF NOT EXISTS ix_learning_patterns_user ON user_learning_patterns(org_id, user_id, pattern_type)",
            "CREATE INDEX IF NOT EXISTS ix_learning_clarif_user   ON learning_clarifications_pending(org_id, user_id)",
            # Run specs lookup by run
            "CREATE INDEX IF NOT EXISTS ix_run_specs_run_id       ON run_specs(run_id)",
        ]
        for ddl in index_ddl:
            try:
                await conn.execute(text(ddl))
            except Exception as exc:
                # Index may already exist or table name may differ — log and continue
                logger.debug("Index DDL skipped: %s — %s", ddl[:60], exc)

    logger.info("Database tables and indexes initialised")


async def close_db() -> None:
    """Dispose engine connections. Called on application shutdown."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    logger.info("Database connections closed")


async def run_in_db(coro):
    """
    Helper for running a single async DB operation with a fresh session.
    Usage: result = await run_in_db(lambda s: s.execute(stmt))
    Not a replacement for get_db() in request handlers — use Depends(get_db) there.
    """
    factory = get_session_factory()
    async with factory() as session:
        result = await coro(session)
        await session.commit()
        return result
