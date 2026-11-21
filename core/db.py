"""
AetherOS — Unified Async Database Layer
Uses SQLAlchemy async + aiosqlite for local dev; PostgreSQL via DATABASE_URL env var.

Key improvements over original:
- WAL mode enabled for SQLite (critical: allows concurrent readers + 1 writer without locking)
- Connection pool tuned for 80K users (PostgreSQL: pool_size=20, max_overflow=40)
- All sync sqlite3.connect() calls replaced with async ORM throughout the codebase
- Indexes on org_id, email, status added via create_all + core/schema_ddl.py
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event, exc as sa_exc, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase

from . import schema_ddl
from .resilience.breaker import CircuitBreaker, CircuitOpen, get_breaker

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


def asyncpg_url_and_ssl(url: str) -> tuple:
    """(url without ?sslmode=, the sslmode or None) for the asyncpg engine.

    Managed databases (RDS, DigitalOcean, Supabase) hand out libpq URLs with ?sslmode=require. SQLAlchemy passes query
    parameters to asyncpg.connect() as keyword arguments, and asyncpg has no `sslmode` argument (TypeError on every
    connection); it takes the same values as `ssl`. Only the async engine converts: Alembic's sync driver needs sslmode.
    """
    u = make_url(url)
    mode = u.query.get("sslmode")
    if mode is None:
        return url, None
    return u.difference_update_query(["sslmode"]).render_as_string(hide_password=False), mode


def _postgres_engine_kwargs() -> dict:
    """Pool + per-connection settings for PostgreSQL.

    DB_STATEMENT_TIMEOUT_MS (default 30000) caps every query. Behind PgBouncer in transaction mode
    (DB_PGBOUNCER=true) asyncpg's prepared-statement cache must be off (statement_cache_size=0) or
    queries fail with "prepared statement does not exist", and startup parameters are not kept per
    server connection, so the timeout is enforced by PgBouncer's query_timeout instead
    (deploy/pgbouncer.ini) and set per transaction is not needed.
    """
    pool_size = int(os.environ.get("DB_POOL_SIZE", "3"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "7"))
    timeout_ms = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "30000"))
    behind_pgbouncer = os.environ.get("DB_PGBOUNCER", "").lower() in ("1", "true", "yes")
    connect_args: dict = {}
    if behind_pgbouncer:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
    else:
        connect_args["server_settings"] = {"statement_timeout": str(timeout_ms)}
    return {
        # N workers x (pool_size + max_overflow) must stay under PG max_connections (or PgBouncer
        # max_client_conn); default 3+7 per worker.
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": 30,
        "pool_recycle": 300,    # cloud DBs drop idle conns
        "pool_pre_ping": True,  # no "closed connection" 500s
        "connect_args": connect_args,
    }


def install_postgres_breaker(engine: AsyncEngine, breaker: CircuitBreaker | None = None) -> CircuitBreaker:
    """Fail fast while PostgreSQL is down instead of making every request wait for a connect timeout.

    After `failure_threshold` consecutive connect failures / dropped connections the breaker opens: new connections are
    refused immediately with CircuitOpen (answered 503, see DEPENDENCY_DOWN) for `reset_after_s`, then one probe goes
    through. Connections already in the pool keep working, so a healthy database is never affected. Per process.
    """
    breaker = breaker or get_breaker("postgres", failure_threshold=int(os.environ.get("DB_BREAKER_FAILURES", "5")),
                                     reset_after_s=float(os.environ.get("DB_BREAKER_RESET_S", "15")))
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "do_connect")
    def _connect(dialect, conn_rec, cargs, cparams):
        # Connect ourselves so a refused/timed-out connect is counted even when it is a raw OSError (not a DBAPI error,
        # so no handle_error event fires for it).
        breaker.before_call()          # raises CircuitOpen while open; in half-open exactly one caller probes
        try:
            conn = dialect.connect(*cargs, **cparams)
        except OSError as exc:
            breaker.record_failure(exc)
            if isinstance(exc, ConnectionError):
                raise
            # A host name that does not resolve (socket.gaierror) or a connect timeout is an OSError but not a
            # ConnectionError, so it missed DEPENDENCY_DOWN and every request answered 500 until the breaker opened.
            raise ConnectionError(f"database connect failed: {type(exc).__name__}: {exc}") from exc
        except Exception as exc:
            breaker.record_failure(exc)
            raise
        breaker.record_success()
        return conn

    @event.listens_for(sync_engine, "handle_error")
    def _on_error(ctx):
        if ctx.is_disconnect:          # an established connection dropped: the database went away mid-flight
            breaker.record_failure(ctx.original_exception)

    return breaker


def get_engine() -> AsyncEngine:
    """Return the global async engine (lazy init)."""
    global _engine
    if _engine is None:
        url = _build_db_url()
        echo = os.environ.get("DB_ECHO", "false").lower() == "true"

        is_sqlite = "sqlite" in url
        is_postgres = "postgresql" in url or "asyncpg" in url

        connect_args: dict = {}
        # hide_parameters: bound values (emails, tokens) never appear in DBAPIError text or logs.
        engine_kwargs: dict = {"echo": echo, "hide_parameters": True}

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
            engine_kwargs.update(_postgres_engine_kwargs())
            url, sslmode = asyncpg_url_and_ssl(url)
            if sslmode:
                engine_kwargs["connect_args"]["ssl"] = sslmode

        _engine = create_async_engine(url, **engine_kwargs)
        if is_postgres:
            install_postgres_breaker(_engine)

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


# "The database cannot be reached" (not "the query is wrong"): the API answers these with 503, see gateway/api.py.
# DBAPIError is only included through its connection-level subclasses so that a bad query stays a 500.
DEPENDENCY_DOWN = (sa_exc.OperationalError, sa_exc.InterfaceError, sa_exc.TimeoutError, ConnectionError, CircuitOpen)


class SchemaNotMigrated(RuntimeError):
    """PostgreSQL schema is not at the Alembic head: run `alembic upgrade head` first."""


async def _require_migrated(engine: AsyncEngine) -> None:
    """Alembic owns the PostgreSQL schema: refuse to start on an un-migrated or stale database."""
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    except Exception as exc:
        raise SchemaNotMigrated(f"alembic_version not readable ({exc}); run `alembic upgrade head`") from exc
    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not ini.exists():
        return
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    heads = set(ScriptDirectory.from_config(Config(str(ini))).get_heads())
    if set(rows) != heads:
        raise SchemaNotMigrated(f"database at {sorted(rows)}, code expects {sorted(heads)}; run `alembic upgrade head`")


# Raw-SQL objects (core/schema_ddl.py), never made by create_all alone: without them the audit ledger
# can be UPDATEd/DELETEd, so PostgreSQL startup refuses to run when they are missing.
LEDGER_TRIGGERS = tuple(schema_ddl.PG_TRIGGERS)


async def require_ledger_triggers(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        have = set((await conn.execute(text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(:n)"),
            {"n": list(LEDGER_TRIGGERS)})).scalars())
    missing = [t for t in LEDGER_TRIGGERS if t not in have]
    if missing:
        raise SchemaNotMigrated(
            f"audit ledger triggers missing {missing}: the ledger is editable. "
            "Run `python scripts/db_migrate.py` (it re-applies core/schema_ddl.py).")


async def init_db() -> None:
    """
    SQLite (dev/tests): create all tables and indexes. PostgreSQL: Alembic owns the schema, so
    only verify it is at head (set AETHER_DB_CREATE_ALL=1 to force create_all, e.g. throwaway DBs).
    Called on application startup.

    Indexes created here match the query patterns in api.py and the pipeline:
    - org_id: nearly every query filters by org
    - email: login lookup (User.email)
    - status: dashboard listing filters by status
    - run_metadata.run_id: priority lookups are per-run
    """
    schema_ddl.register_models()   # every table, also for callers that never load the gateway
    engine = get_engine()
    if engine.dialect.name == "postgresql" and os.environ.get("AETHER_DB_CREATE_ALL", "").lower() not in ("1", "true"):
        await _require_migrated(engine)
        await require_ledger_triggers(engine)
        logger.info("PostgreSQL schema is at the Alembic head")
        return
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            # The model declares a native vector column whenever the pgvector Python package is installed, so create_all needs the
            # extension to exist first (it failed with 'type "vector" does not exist' on a fresh database). A refused CREATE
            # EXTENSION is left for schema_ddl.apply to report; nothing is hidden here.
            try:
                async with conn.begin_nested():
                    await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            except Exception as e:
                logger.warning("pgvector extension could not be created before create_all: %s", e)
        await conn.run_sync(Base.metadata.create_all)
        # Indexes, ledger triggers and pgvector: the same definitions the Alembic revisions use.
        await conn.run_sync(schema_ddl.apply)
    if engine.dialect.name == "postgresql":
        await require_ledger_triggers(engine)  # forced create_all must not leave an editable ledger

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
