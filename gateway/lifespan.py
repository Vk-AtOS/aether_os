"""
AetherOS — Application Lifespan (startup / shutdown)

Extracted from gateway/api.py to keep that file under 600 lines.
The create_lifespan() factory returns the @asynccontextmanager lifespan
function that FastAPI calls at startup and shutdown.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Set

from sqlalchemy import delete, text

from aether_os.core.app_state import set_app_state
from aether_os.core.crash_recovery import mark_orphaned_runs
from aether_os.core.db import SchemaNotMigrated, close_db, get_engine, get_session_factory, init_db
from aether_os.core.guardian.watchdog import get_watchdog
from aether_os.core.models import Webhook
from aether_os.core.pipeline_state import get_redis
from aether_os.core.queue.pipeline_consumer import start_consumer, stop_consumer
from aether_os.core.rate_limiter import run_app_port_get
from aether_os.core.repair_learning import load_validators
from aether_os.core.run_app import preview_state
from aether_os.core.seed import ensure_demo_user, ensure_marketplace
from aether_os.core.telemetry.langsmith_tracer import init_langsmith
from aether_os.core.workloop_monitor import get_workloop_monitor
from aether_os.gateway.api_utils import _seed_golden_examples_if_empty
from aether_os.gateway.auth import reload_keys
from aether_os.gateway.routers.run_app_router import start_run_app
from aether_os.phases.p08_cicd.webhook import initialise_call_graph

logger = logging.getLogger(__name__)


async def register_live_run_app(projects_root: Path) -> Optional[str]:
    """After a gateway restart, re-register the newest generated app that is still up; return its run id.

    A state file is only a claim. It is believed when the process it names is
    alive and carries that launch's nonce (preview_state.live_app, the check the
    preview proxy uses). An open port proves nothing: ports are reused, and the
    listener may be another run's app — which is what the old socket probe trusted.
    """
    state_files = sorted((projects_root / preview_state.STATE_DIR).glob(f"*/{preview_state.STATE_FILE}"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
    for state_file in state_files:
        run_id = state_file.parent.name
        app = await asyncio.to_thread(preview_state.live_app, run_id, state_file)
        if app:
            logger.info("run_app: run %s still up on port %d (pid %s) — registering (no restart)",
                        run_id, app["port"], app["pid"])
            await set_app_state(run_id, port=app["port"], pid=app["pid"],
                                mode=app["mode"] or "backend", app_dir=str(projects_root / run_id))
            return run_id
    return None


def create_lifespan(background_tasks: Set):
    """Return the lifespan async context manager bound to the given background_tasks set."""

    @asynccontextmanager
    async def lifespan(app):
        """Application startup/shutdown lifecycle."""
        logger.info("AetherOS API starting up...")

        # ── JWT key validation — reload from env, fail hard if RS256 keys missing ─
        # reload_keys() clears the lazy cache and re-reads from the current
        # environment so keys injected by dotenv AFTER import time are honoured.
        # HS256 fallback has been removed — the server refuses to start without
        # valid RS256 keys to prevent silent algorithm downgrade attacks.
        try:
            _jwt_alg = reload_keys()
            logger.info("JWT: signing active (algorithm=%s)", _jwt_alg)
        except RuntimeError as _jwt_err:
            logger.critical("FATAL: JWT key configuration error — %s", _jwt_err)
            sys.exit(1)

        # ── Redis startup validation ──────────────────────────────────────────
        _require_redis = os.environ.get("REQUIRE_REDIS", "false").lower() == "true"
        _is_production = os.environ.get("ENVIRONMENT", "development") == "production"
        try:
            _r_check = await get_redis()
            if _r_check is None:
                if _require_redis or _is_production:
                    logger.critical(
                        "FATAL: Redis unavailable but REQUIRE_REDIS=true (or ENVIRONMENT=production).\n"
                        "Set REDIS_URL and ensure Redis is running before starting in production."
                    )
                    sys.exit(1)
                else:
                    logger.warning(
                        "Redis unavailable — rate limiting is per-process only (single-worker dev mode).\n"
                        "Set REDIS_URL and REQUIRE_REDIS=true for production deployments."
                    )
            else:
                logger.info("Redis connection verified OK")
        except Exception as _redis_exc:
            logger.warning("Redis startup check failed: %s", _redis_exc)

        # ── Field-level encryption key check ─────────────────────────────────
        if not os.environ.get("AETHER_FIELD_KEY", ""):
            if _is_production:
                raise RuntimeError(
                    "AETHER_FIELD_KEY must be set in production. "
                    "LLM API keys and MFA secrets cannot be stored safely without it. "
                    "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
            logger.warning(
                "\n"
                "  ┌─────────────────────────────────────────────────────────────┐\n"
                "  │  WARNING: AETHER_FIELD_KEY is not set.                      │\n"
                "  │  LLM API keys and MFA secrets are stored UNENCRYPTED.       │\n"
                "  │                                                             │\n"
                "  │  Generate a key with:                                       │\n"
                "  │    python -c \"from cryptography.fernet import Fernet;       │\n"
                "  │    print(Fernet.generate_key().decode())\"                   │\n"
                "  │  Then add AETHER_FIELD_KEY=<key> to your .env file.         │\n"
                "  └─────────────────────────────────────────────────────────────┘"
            )

        # ── CORS startup validation ───────────────────────────────────────────
        if _is_production and not os.environ.get("CORS_ORIGINS", ""):
            logger.warning(
                "CORS_ORIGINS is not set in production — defaulting to localhost origins only. "
                "Set CORS_ORIGINS=https://yourdomain.com to allow browser access from the real domain."
            )

        # ── PostgreSQL startup validation ─────────────────────────────────────
        _db_url = os.environ.get("DATABASE_URL", "")
        if _db_url and ("postgresql" in _db_url or "postgres" in _db_url):
            try:
                _pg_engine = get_engine()
                async with _pg_engine.connect() as _pg_conn:
                    await _pg_conn.execute(text("SELECT 1"))
                logger.info("PostgreSQL connection verified OK")
            except Exception as _pg_exc:
                logger.critical(
                    "FATAL: Cannot connect to PostgreSQL at startup: %s\n"
                    "Check DATABASE_URL env var and ensure PostgreSQL is running.",
                    _pg_exc,
                )
                sys.exit(1)

        # Initialise database (create tables + indexes)
        try:
            await init_db()
        except SchemaNotMigrated as exc:
            logger.critical("FATAL: %s", exc)
            sys.exit(1)
        except Exception as exc:
            logger.warning("DB init failed: %s", exc)

        # Ensure demo/admin user exists — survives Guardian restores and fresh deploys.
        try:
            await ensure_demo_user()
        except Exception as _seed_exc:
            logger.warning("Seed: demo user creation skipped: %s", _seed_exc)

        # Load auto-generated validators learned from past repairs
        try:
            load_validators()  # loads from disk, logs count
        except Exception as exc:
            logger.warning("repair_learning: load_validators skipped: %s", exc)

        # Initialise LangSmith tracing (graceful degradation if key absent)
        try:
            init_langsmith()
        except Exception as exc:
            logger.warning("LangSmith init skipped: %s", exc)

        # Pre-build call graph if repo root configured (Bug 5 fix)
        try:
            repo_root = os.environ.get("AETHER_REPO_ROOT")
            if repo_root:
                initialise_call_graph(repo_root)
        except Exception as exc:
            logger.warning("Call graph init skipped: %s", exc)

        # ── Crash recovery ────────────────────────────────────────────────────
        try:
            _sf = get_session_factory()
            async with _sf() as _cr_session:
                _fixed_phases, _fixed_runs = await mark_orphaned_runs(_cr_session)
                await _cr_session.commit()
            if _fixed_phases or _fixed_runs:
                logger.warning(
                    "Crash recovery: marked %d orphaned phase(s) and %d run(s) as 'interrupted'",
                    _fixed_phases, _fixed_runs,
                )
        except Exception as _exc:
            logger.warning("Crash recovery cleanup failed: %s", _exc)

        # ── Auto-restart last run_app after service restart ───────────────────
        async def _restore_run_app():
            try:
                await asyncio.sleep(5)  # wait for DB + deps to settle

                if await register_live_run_app(Path.home() / ".aether_os" / "projects"):
                    return

                _rid, _rport = await run_app_port_get()
                if not _rid:
                    return
                if await asyncio.to_thread(preview_state.live_app, _rid):
                    logger.info("run_app: run %s is still up — no restart needed", _rid)
                    return
                logger.info("run_app: restarting run %s after service restart (old port %d was dead)", _rid, _rport)
                _system_user = {"org_id": None, "user_id": "system", "role": "admin"}
                result = await start_run_app(run_id=_rid, user=_system_user)
                logger.info("run_app: auto-restarted run %s → port %d", _rid, result.get("port"))
            except Exception as _exc:
                logger.debug("run_app auto-restore skipped: %s", _exc)

        asyncio.create_task(_restore_run_app())

        # ── Purge example.com webhooks left from seed data ───────────────────
        # An https://example.com/webhook record was seeded and fires POST
        # requests on every RUN.COMPLETED / RUN.FAILED event (always failing).
        try:
            async with get_session_factory()() as _wh_session:
                _wh_result = await _wh_session.execute(
                    delete(Webhook).where(Webhook.url.like("%example.com%"))
                )
                await _wh_session.commit()
            if _wh_result.rowcount:
                logger.info(
                    "Startup cleanup: deleted %d example.com webhook(s) (leftover seed data)",
                    _wh_result.rowcount,
                )
        except Exception as _wh_exc:
            logger.warning("example.com webhook cleanup failed (non-fatal): %s", _wh_exc)

        # Seed marketplace with built-in skills if empty
        try:
            await ensure_marketplace()
        except Exception as _exc:
            logger.warning("Marketplace seeding skipped: %s", _exc)

        # Seed golden build examples from JSON files if the table is empty
        try:
            await _seed_golden_examples_if_empty()
        except Exception as _ge_exc:
            logger.warning("Golden example seeding failed (non-fatal): %s", _ge_exc)

        # ── SQS Pipeline Consumer ─────────────────────────────────────────────
        try:
            start_consumer()
        except Exception as _sqs_exc:
            logger.warning("SQS consumer failed to start: %s", _sqs_exc)

        # Periodic monitors query the database on their own schedule. Under a test
        # client they outlive the test's database and fail its teardown at random,
        # so tests switch them off with AETHER_DISABLE_MONITORS=1.
        _monitors_on = os.environ.get("AETHER_DISABLE_MONITORS") != "1"

        # ── Workloop Monitor ─────────────────────────────────────────────────
        try:
            if _monitors_on:
                get_workloop_monitor().start()
        except Exception as _wl_exc:
            logger.warning("WorkloopMonitor failed to start: %s", _wl_exc)

        # ── Guardian Watchdog ─────────────────────────────────────────────────
        try:
            if _monitors_on:
                _guardian_task = asyncio.create_task(get_watchdog().start())
                background_tasks.add(_guardian_task)
                logger.info("Guardian watchdog started")
        except Exception as _gw_exc:
            logger.warning("Guardian watchdog failed to start: %s", _gw_exc)

        # ── Webhook outbox sweeper: deliveries survive a restart and are retried with backoff ──
        try:
            if _monitors_on:
                from aether_os.core.webhooks.outbox import run_sweeper
                _wh_task = asyncio.create_task(run_sweeper())
                background_tasks.add(_wh_task)
                _wh_task.add_done_callback(background_tasks.discard)
        except Exception as _wh_exc:
            logger.warning("Webhook outbox sweeper failed to start: %s", _wh_exc)

        yield  # ── Application runs here ──────────────────────────────────

        # Shutdown
        logger.info("AetherOS API shutting down...")
        try:
            stop_consumer()
        except Exception as exc:
            logger.debug("SQS consumer stop failed during shutdown: %s", exc)
        try:
            get_workloop_monitor().stop()
        except Exception as exc:
            logger.debug("Workloop monitor stop failed during shutdown: %s", exc)
        try:
            get_watchdog().stop()
        except Exception as exc:
            logger.debug("Guardian watchdog stop failed during shutdown: %s", exc)
        try:
            await close_db()
        except Exception as exc:
            logger.debug("DB close failed during shutdown: %s", exc)

    return lifespan
