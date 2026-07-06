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
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)


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
            from aether_os.gateway.auth import reload_keys as _reload_jwt_keys
            _jwt_alg = _reload_jwt_keys()
            logger.info("JWT: RS256 asymmetric signing active (algorithm=%s)", _jwt_alg)
        except RuntimeError as _jwt_err:
            logger.critical("FATAL: JWT RS256 key configuration error — %s", _jwt_err)
            import sys as _sys_jwt; _sys_jwt.exit(1)

        # ── Redis startup validation ──────────────────────────────────────────
        _require_redis = os.environ.get("REQUIRE_REDIS", "false").lower() == "true"
        _is_production = os.environ.get("ENVIRONMENT", "development") == "production"
        try:
            from aether_os.core.pipeline_state import get_redis as _get_redis_check
            _r_check = await _get_redis_check()
            if _r_check is None:
                if _require_redis or _is_production:
                    logger.critical(
                        "FATAL: Redis unavailable but REQUIRE_REDIS=true (or ENVIRONMENT=production).\n"
                        "Set REDIS_URL and ensure Redis is running before starting in production."
                    )
                    import sys as _sys_r; _sys_r.exit(1)
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
                from aether_os.core.db import get_engine
                from sqlalchemy import text as _pg_text
                _pg_engine = get_engine()
                async with _pg_engine.connect() as _pg_conn:
                    await _pg_conn.execute(_pg_text("SELECT 1"))
                logger.info("PostgreSQL connection verified OK")
            except Exception as _pg_exc:
                logger.critical(
                    "FATAL: Cannot connect to PostgreSQL at startup: %s\n"
                    "Check DATABASE_URL env var and ensure PostgreSQL is running.",
                    _pg_exc,
                )
                import sys
                sys.exit(1)

        # Initialise database (create tables + indexes)
        try:
            from aether_os.core.db import init_db
            await init_db()
        except Exception as exc:
            logger.warning("DB init failed: %s", exc)

        # Ensure demo/admin user exists — survives Guardian restores and fresh deploys.
        try:
            from aether_os.core.seed import ensure_demo_user
            await ensure_demo_user()
        except Exception as _seed_exc:
            logger.warning("Seed: demo user creation skipped: %s", _seed_exc)

        # Load auto-generated validators learned from past repairs
        try:
            from aether_os.core.repair_learning import load_validators
            load_validators()  # loads from disk, logs count
        except Exception as exc:
            logger.warning("repair_learning: load_validators skipped: %s", exc)

        # Initialise LangSmith tracing (graceful degradation if key absent)
        try:
            from aether_os.core.telemetry.langsmith_tracer import init_langsmith
            init_langsmith()
        except Exception as exc:
            logger.warning("LangSmith init skipped: %s", exc)

        # Pre-build call graph if repo root configured (Bug 5 fix)
        try:
            repo_root = os.environ.get("AETHER_REPO_ROOT")
            if repo_root:
                from aether_os.phases.p08_cicd.webhook import initialise_call_graph
                initialise_call_graph(repo_root)
        except Exception as exc:
            logger.warning("Call graph init skipped: %s", exc)

        # ── Crash recovery ────────────────────────────────────────────────────
        try:
            from aether_os.core.db import get_session_factory
            from sqlalchemy import text as _cr_text
            _ts = time.time()
            _sf = get_session_factory()
            async with _sf() as _cr_session:
                _r1 = await _cr_session.execute(
                    _cr_text("UPDATE phase_completions SET status='interrupted', updated_at=:ts WHERE status='running'"),
                    {"ts": _ts},
                )
                _r2 = await _cr_session.execute(
                    _cr_text("UPDATE runs SET status='interrupted', finished_at=:ts WHERE status='running'"),
                    {"ts": _ts},
                )
                await _cr_session.commit()
            _fixed_phases = _r1.rowcount
            _fixed_runs = _r2.rowcount
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
                import json as _rjson
                import glob as _rglob
                import socket as _sock

                _state_files = sorted(
                    _rglob.glob(str(Path.home() / ".aether_os" / "projects" / "*" / "run_app_state.json")),
                    key=lambda p: Path(p).stat().st_mtime,
                    reverse=True,
                )
                for _sf in _state_files:
                    try:
                        _st = _rjson.loads(Path(_sf).read_text())
                        _rid = _st.get("run_id") or Path(_sf).parent.name
                        _rport = int(_st.get("port", 0))
                        if not _rid or not _rport:
                            continue
                        _alive = False
                        try:
                            with _sock.create_connection(("127.0.0.1", _rport), timeout=1):
                                _alive = True
                        except OSError as e:
                            logger.warning("api: probe connection failed for run %s on port %d: %s", _rid, _rport, e)
                        if _alive:
                            logger.info("run_app: port %d still alive for run %s — registering (no restart)", _rport, _rid)
                            from aether_os.core.app_state import set_app_state as _sas_r
                            await _sas_r(_rid, port=_rport, pid=_st.get("pid", 0),
                                         mode=_st.get("mode", "backend"), app_dir=str(Path(_sf).parent))
                            return
                    except Exception as exc:
                        logger.debug("Failed to parse/probe run_app_state.json: %s", exc)
                        continue

                from aether_os.core.rate_limiter import run_app_port_get as _rapg
                _rid, _rport = await _rapg()
                if not _rid:
                    return
                _dead = True
                try:
                    with _sock.create_connection(("127.0.0.1", _rport), timeout=1):
                        _dead = False
                except OSError as e:
                    logger.warning("api: Redis fallback probe failed for run %s on port %d: %s", _rid, _rport, e)
                if not _dead:
                    logger.info("run_app: port %d still alive for run %s — no restart needed", _rport, _rid)
                    return
                logger.info("run_app: restarting run %s after service restart (old port %d was dead)", _rid, _rport)
                from aether_os.gateway.routers.run_app_router import start_run_app as _sar
                _system_user = {"org_id": None, "user_id": "system", "role": "admin"}
                result = await _sar(run_id=_rid, user=_system_user)
                logger.info("run_app: auto-restarted run %s → port %d", _rid, result.get("port"))
            except Exception as _exc:
                logger.debug("run_app auto-restore skipped: %s", _exc)

        asyncio.create_task(_restore_run_app())

        # Seed marketplace with built-in skills if empty
        try:
            from aether_os.core.seed import ensure_marketplace
            await ensure_marketplace()
        except Exception as _exc:
            logger.warning("Marketplace seeding skipped: %s", _exc)

        # Seed golden build examples from JSON files if the table is empty
        try:
            from aether_os.gateway.api_utils import _seed_golden_examples_if_empty
            await _seed_golden_examples_if_empty()
        except Exception as _ge_exc:
            logger.warning("Golden example seeding failed (non-fatal): %s", _ge_exc)

        # ── SQS Pipeline Consumer ─────────────────────────────────────────────
        try:
            from aether_os.core.queue.pipeline_consumer import start_consumer as _start_sqs
            _start_sqs()
        except Exception as _sqs_exc:
            logger.warning("SQS consumer failed to start: %s", _sqs_exc)

        # ── Workloop Monitor ─────────────────────────────────────────────────
        try:
            from aether_os.core.workloop_monitor import get_workloop_monitor
            get_workloop_monitor().start()
        except Exception as _wl_exc:
            logger.warning("WorkloopMonitor failed to start: %s", _wl_exc)

        # ── Guardian Watchdog ─────────────────────────────────────────────────
        try:
            from aether_os.core.guardian.watchdog import get_watchdog as _get_guardian
            _guardian_task = asyncio.create_task(_get_guardian().start())
            background_tasks.add(_guardian_task)
            logger.info("Guardian watchdog started")
        except Exception as _gw_exc:
            logger.warning("Guardian watchdog failed to start: %s", _gw_exc)

        yield  # ── Application runs here ──────────────────────────────────

        # Shutdown
        logger.info("AetherOS API shutting down...")
        try:
            from aether_os.core.queue.pipeline_consumer import stop_consumer as _stop_sqs
            _stop_sqs()
        except Exception as exc:
            logger.debug("SQS consumer stop failed during shutdown: %s", exc)
        try:
            from aether_os.core.workloop_monitor import get_workloop_monitor
            get_workloop_monitor().stop()
        except Exception as exc:
            logger.debug("Workloop monitor stop failed during shutdown: %s", exc)
        try:
            from aether_os.core.guardian.watchdog import get_watchdog as _get_guardian_stop
            _get_guardian_stop().stop()
        except Exception as exc:
            logger.debug("Guardian watchdog stop failed during shutdown: %s", exc)
        try:
            from aether_os.core.db import close_db
            await close_db()
        except Exception as exc:
            logger.debug("DB close failed during shutdown: %s", exc)

    return lifespan
