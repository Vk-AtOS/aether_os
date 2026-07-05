"""
AetherOS — Unified FastAPI Gateway

Bug 3 fix: CORS reads from CORS_ORIGINS env var, never ["*"].
Bug 4 fix: JWT SECRET_KEY raises RuntimeError if not set.

Routes:
  POST /pipeline/start      — start a new pipeline run
  GET  /pipeline/status/{run_id} — get pipeline status
  POST /pipeline/approve/{ticket_id} — approve a human-gated action
  POST /ci/webhook          — receive CI failure webhook (Bug 5 fixed)
  POST /auth/login          — get JWT token
  GET  /health              — health check
"""
from __future__ import annotations
import sys as _sys
import pathlib as _pathlib
# Ensure aether_os package is importable regardless of CWD / how uvicorn is invoked.
# __file__ is .../aether_os/gateway/api.py → parent.parent.parent is ~/Desktop/
_pkg_root = str(_pathlib.Path(__file__).resolve().parent.parent.parent)
if _pkg_root not in _sys.path:
    _sys.path.insert(0, _pkg_root)

import logging
import os
import pathlib
import time
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, status, Request, APIRouter, UploadFile, File as FastAPIFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
# Pydantic models and middleware classes live in api_helpers.py to keep this
# file under 600 lines. They are re-imported here for backwards compatibility
# with any code that imports them from gateway.api directly.
from aether_os.gateway.api_helpers import (  # noqa: F401 (re-export)
    PipelineStartRequest, PipelineStartResponse,
    ApproveRequest, ApiKeyRequest, TestProviderRequest,
    PhaseConfigUpdate, PriorityRequest, RerunRequest,
    FileWriteBody, EnvVarItem, EnvVarsBody,
    SamlConfigRequest, WorkspaceCreate, WorkspaceUpdate,
    OrgIDLoggingMiddleware, SecurityHeadersMiddleware, HttpsRedirectMiddleware,
)

load_dotenv(pathlib.Path(__file__).parent.parent / ".env", override=False)

DASHBOARD_DIST = pathlib.Path(__file__).parent.parent / "dashboard" / "dist"

# C11: structured JSON logging — must run before any logger.* calls
try:
    from aether_os.core.logging_config import configure_logging
    configure_logging()
except Exception as exc:
    logging.basicConfig(level=logging.INFO)
    logging.warning("Failed to load structured logging config, using basicConfig fallback: %s", exc)

logger = logging.getLogger(__name__)

# Utility helpers live in api_utils.py to keep this file under 600 lines.
from aether_os.gateway.api_utils import _init_sentry, _get_cors_origins, _json_safe, _seed_golden_examples_if_empty  # noqa: E402

_init_sentry()

# B5: Strong references prevent GC from silently killing in-flight background tasks.
_background_tasks: set = set()

# Auth dependency — defined in gateway/dependencies.py to avoid circular imports.
# Re-exported here for any code that imports it from api directly.
from aether_os.gateway.dependencies import security_scheme, get_current_user  # noqa: E402


# NOTE: _get_cors_origins, Pydantic models, and middleware classes all live in
# api_helpers.py / api_utils.py — imported above. Duplicate definitions removed
# to keep this file under 600 lines.

# get_current_user is now defined in gateway/dependencies.py and re-exported above.


# ── Generated-app process state — delegated to core.app_state (Redis-backed) ──
# These module-level names are kept for backwards compatibility with any code that
# still imports them directly; they delegate to the canonical storage in core.app_state.
from aether_os.core.app_state import get_all_procs as _get_all_procs, get_all_ports as _get_all_ports, _CURRENT_RUN_MEMORY as _APP_CURRENT_RUN  # noqa: E402

_APP_PROCS: Dict[str, Any] = _get_all_procs()   # same dict object as core.app_state._PROCS
_APP_PORTS: Dict[str, int] = _get_all_ports()   # same dict object as core.app_state._APP_PORTS

# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the AetherOS FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application startup/shutdown lifecycle."""
        logger.info("AetherOS API starting up...")

        # ── JWT key validation — reload from env, fail fast if misconfigured ───
        # reload_keys() clears the lazy cache and re-reads from the current
        # environment so keys injected by dotenv AFTER import time are honoured.
        try:
            from aether_os.gateway.auth import reload_keys as _reload_jwt_keys
            _jwt_alg = _reload_jwt_keys()
            logger.info("JWT: algorithm=%s", _jwt_alg)
            if _jwt_alg == "HS256":
                _hs_secret = os.environ.get("AETHER_SECRET_KEY", "")
                if not _hs_secret:
                    raise RuntimeError(
                        "HS256 is active but AETHER_SECRET_KEY is not set. "
                        "Set AETHER_JWT_PRIVATE_KEY_B64 + AETHER_JWT_PUBLIC_KEY_B64 (RS256, recommended) "
                        "or AETHER_SECRET_KEY (HS256, legacy) before starting the server."
                    )
                logger.warning(
                    "JWT: HS256 mode active (symmetric). "
                    "Set AETHER_JWT_PRIVATE_KEY_B64 + AETHER_JWT_PUBLIC_KEY_B64 to upgrade to RS256."
                )
            else:
                logger.info("JWT: RS256 asymmetric signing active.")
        except RuntimeError as _jwt_err:
            logger.critical("FATAL: JWT key configuration error — %s", _jwt_err)
            import sys as _sys_jwt; _sys_jwt.exit(1)

        # ── Redis startup validation ──────────────────────────────────────────
        # REQUIRE_REDIS=true makes Redis mandatory (production). Without Redis,
        # rate limiting is per-worker only (unsafe at scale) and SSE/pause/cancel
        # won't work across multiple uvicorn processes.
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
        # If DATABASE_URL is set, verify we can actually connect before accepting
        # traffic. A misconfigured URL would otherwise produce silent SQLite
        # fallback that collapses under multi-worker load.
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
                # Log prominently and exit — running on broken DB is worse than not starting
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
            _validators = load_validators()  # loads from disk, logs count
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
        # Any runs/phases still showing "running" when we start up were orphaned
        # by a previous server crash or restart.  Mark them "interrupted" so the
        # dashboard shows accurate state and users know they need to re-run.
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
            _fixed_runs   = _r2.rowcount
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
                import json as _rjson, glob as _rglob
                import socket as _sock

                # First: scan per-run state files for a live port (avoids Redis overwrite)
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

                # Fallback: check Redis
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
            await _seed_golden_examples_if_empty()
        except Exception as _ge_exc:
            logger.warning("Golden example seeding failed (non-fatal): %s", _ge_exc)

        # ── SQS Pipeline Consumer ─────────────────────────────────────────────
        # Long-polls aetheros-pipeline-jobs queue and executes runs off the
        # HTTP request path. Only activates when SQS_QUEUE_URL is set in env.
        try:
            from aether_os.core.queue.pipeline_consumer import start_consumer as _start_sqs
            _start_sqs()
        except Exception as _sqs_exc:
            logger.warning("SQS consumer failed to start: %s", _sqs_exc)

        # ── Workloop Monitor ─────────────────────────────────────────────────
        # Background self-healing: scans recent run failures every 5 minutes,
        # runs LLM diagnosis, and auto-applies safe platform fixes.
        try:
            from aether_os.core.workloop_monitor import get_workloop_monitor
            get_workloop_monitor().start()
        except Exception as _wl_exc:
            logger.warning("WorkloopMonitor failed to start: %s", _wl_exc)

        # ── Guardian Watchdog ─────────────────────────────────────────────────
        # Autonomous self-monitoring: threat detection, snapshots, auto-recovery.
        # Strong reference kept in _background_tasks WITHOUT a discard callback so
        # the task is never GC'd if it exits early (bug [16]).
        try:
            from aether_os.core.guardian.watchdog import get_watchdog as _get_guardian
            _guardian_task = asyncio.create_task(_get_guardian().start())
            _background_tasks.add(_guardian_task)
            # Do NOT add a discard callback — the task must stay referenced even if
            # it finishes/crashes so Python's GC cannot collect it silently.
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

    # B11: disable interactive docs in production — prevents API schema exposure
    _env = os.getenv("ENVIRONMENT", "development")
    app = FastAPI(
        title="AetherOS API",
        description="Unified multi-agent software development system",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if _env == "production" else "/docs",
        redoc_url=None if _env == "production" else "/redoc",
    )

    # Bug fix: Strip /api prefix for local dev support (dashboard expects /api)
    @app.middleware("http")
    async def strip_api_prefix(request: Request, call_next):
        if request.url.path.startswith("/api"):
            # Only strip if it's followed by a slash or is just /api
            if request.url.path == "/api":
                request.scope["path"] = "/"
            elif request.url.path.startswith("/api/"):
                request.scope["path"] = request.url.path[4:]
        return await call_next(request)

    # Security middleware — always enabled
    app.add_middleware(OrgIDLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(HttpsRedirectMiddleware)

    # Bug 3 fix: CORS from env var
    cors_origins = _get_cors_origins()
    logger.info("CORS origins: %s", cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Content-Type", "Authorization", "X-Org-ID", "Accept"],
    )

    # C9: Prometheus metrics — instrumentation only; /metrics endpoint is in metrics_router
    try:
        from aether_os.core.prometheus_patch import apply as _apply_prom_patch
        _apply_prom_patch()  # must run before .instrument() — see core/prometheus_patch.py
        from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore
        instrumentator = Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            excluded_handlers=["/health", "/metrics"],
        ).instrument(app)
        instrumentator.expose(app, endpoint="/_metrics_internal", include_in_schema=False)
        logger.info("Prometheus instrumentation enabled (handler: metrics_router)")
    except ImportError:
        logger.warning("prometheus-fastapi-instrumentator not installed — metrics disabled")
    except Exception as exc:
        logger.warning("Prometheus init failed: %s", exc)

    # P5: Audit log middleware — automatically logs every mutating authenticated request
    @app.middleware("http")
    async def audit_log_middleware(request: Request, call_next):
        response = await call_next(request)
        # Only log mutating requests to API paths (not health, docs, static, SSE)
        method = request.method
        path = request.url.path
        if (method in ("POST", "PUT", "PATCH", "DELETE")
                and not any(path.startswith(p) for p in ("/docs", "/redoc", "/openapi", "/health", "/metrics"))
                and not path.endswith("/stream")):
            try:
                # Extract user from Authorization header (best-effort — don't block request)
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    from aether_os.gateway.auth import decode_access_token
                    claims = decode_access_token(auth[7:])
                    if claims:
                        from aether_os.core.audit.ledger import get_ledger
                        import asyncio
                        path_parts = path.split("/")
                        asyncio.create_task(get_ledger().async_log_audit_event(
                            org_id=claims.get("org_id", "unknown"),
                            user_id=str(claims.get("user_id", "unknown")),
                            action=f"{method} {path}",
                            resource_type=path_parts[1] if len(path_parts) > 1 else "api",
                            resource_id=path_parts[2] if len(path_parts) > 2 else "-",
                            metadata={},
                            ip_address=(
                                request.headers.get("X-Real-IP")
                                or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                                or (request.client.host if request.client else "unknown")
                            ),
                        ))
            except Exception as exc:
                logger.debug("Audit log write failed (non-fatal): %s", exc)  # Audit logging must never break the request
        return response

    # ── Global exception handler — prevents stack traces leaking to clients ────
    # _json_safe() is imported from api_utils at module level above.
    from fastapi import Request as _Request
    from fastapi.responses import JSONResponse as _JSONResponse
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_req: _Request, exc: RequestValidationError):
        return _JSONResponse(
            status_code=422,
            content={"detail": _json_safe(exc.errors()), "body": str(exc.body)[:200]},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_req: _Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", _req.method, _req.url.path)
        return _JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred. The error has been logged."},
        )

    # ── Routes ────────────────────────────────────────────────────────────────

    api_router = APIRouter(prefix="/api")

    # ── Mount all routers ─────────────────────────────────────────────────────
    # Each entry: (name, module, attr_name, extra_kwargs, required)
    # required=True  → startup aborts if the router cannot be imported (fail-fast)
    # required=False → logs a warning and continues (optional / deployment-specific)
    app.include_router(api_router)

    _ROUTERS = [
        # --- Required: core auth & user-facing API ---
        ("auth",              "aether_os.gateway.routers.auth_router",              "router",       {},                        True),
        ("auth_refresh",      "aether_os.gateway.routers.auth_refresh_router",      "router",       {},                        True),
        ("auth_keys",         "aether_os.gateway.routers.auth_keys_router",         "router",       {},                        True),
        ("auth_password",     "aether_os.gateway.routers.auth_password_router",     "router",       {},                        True),
        ("health",            "aether_os.gateway.routers.health_router",            "router",       {},                        True),
        ("admin",             "aether_os.gateway.routers.admin_router",             "router",       {},                        True),
        ("admin_platform",    "aether_os.gateway.routers.admin_platform_router",    "router",       {},                        True),
        ("admin_quality",     "aether_os.gateway.routers.admin_quality_router",     "router",       {},                        True),
        ("factory_runs",           "aether_os.gateway.routers.factory_runs_router",            "router", {}, True),
        ("factory_run_files",      "aether_os.gateway.routers.factory_run_files_router",       "router", {}, True),
        ("factory_run_streaming",  "aether_os.gateway.routers.factory_run_streaming_router",   "router", {}, True),
        ("factory_run_compliance", "aether_os.gateway.routers.factory_run_compliance_router",  "router", {}, True),
        ("run_app",           "aether_os.gateway.routers.run_app_router",           "router",       {},                        True),
        ("run_decisions",     "aether_os.gateway.routers.run_decisions_router",     "router",       {},                        True),
        ("run_spec",          "aether_os.gateway.routers.run_spec_router",          "router",       {},                        True),
        ("run_deploy",        "aether_os.gateway.routers.run_deploy_router",        "router",       {},                        True),
        ("run_preview",       "aether_os.gateway.routers.run_preview_router",       "router",       {},                        True),
        ("factory_ops",       "aether_os.gateway.routers.factory_ops_router",       "router",       {},                        True),
        ("factory_start",     "aether_os.gateway.routers.factory_start_router",     "router",       {},                        True),
        ("factory_intake",    "aether_os.gateway.routers.factory_intake_router",    "router",       {},                        True),
        ("factory_analytics", "aether_os.gateway.routers.factory_analytics_router", "router",       {},                        True),
        ("account",           "aether_os.gateway.routers.account_router",           "router",       {},                        True),
        ("account_settings",  "aether_os.gateway.routers.account_settings_router",  "router",       {},                        True),
        ("account_codebase",  "aether_os.gateway.routers.account_codebase_router",  "router",       {},                        True),
        ("billing",       "aether_os.gateway.routers.billing_router",       "router",       {},                        True),
        ("settings",      "aether_os.gateway.routers.settings_router",      "router",       {},                        True),
        ("settings_advanced", "aether_os.gateway.routers.settings_advanced_router", "router", {},                   True),
        # --- Optional: present in most deployments but non-critical ---
        ("metrics",       "aether_os.gateway.routers.metrics_router",       "router",       {},                        False),
        ("spa",           "aether_os.gateway.routers.spa_router",           "router",       {},                        False),
        ("legal",         "aether_os.gateway.routers.legal_router",         "router",       {},                        False),
        ("notifications", "aether_os.gateway.routers.notifications_router", "router",       {},                        False),
        ("learning",      "aether_os.gateway.routers.learning_router",      "router",       {},                        False),
        ("memory",        "aether_os.gateway.routers.memory_router",        "router",       {},                        False),
        ("webhooks",      "aether_os.gateway.routers.webhooks_router",      "router",       {},                        False),
        ("workspaces",    "aether_os.gateway.routers.workspaces_router",    "router",       {},                        False),
        ("marketplace",   "aether_os.gateway.routers.marketplace_router",   "router",       {},                        False),
        ("billing_stripe","aether_os.gateway.routers.billing_stripe_router","router",       {},                        False),
        ("system",        "aether_os.gateway.routers.system_router",        "router",       {},                        False),
        ("system_info",   "aether_os.gateway.routers.system_info_router",   "router",       {},                        False),
        ("intelligence",  "aether_os.gateway.routers.intelligence_router",  "router",       {},                        False),
        ("compliance",    "aether_os.gateway.routers.compliance_router",    "router",       {},                        False),
        ("scim",          "aether_os.gateway.routers.scim_router",          "router",       {},                        False),
        ("agents",        "aether_os.gateway.routers.agents_router",        "router",       {},                        False),
        ("guardian",      "aether_os.gateway.routers.guardian_router",      "router",       {},                        False),
        ("guardian_snapshots", "aether_os.gateway.routers.guardian_snapshots_router", "router", {},                    False),
        ("app_preview",   "aether_os.gateway.routers.app_preview_router",   "router",       {},                        False),
        # --- Plugin / optional integrations ---
        ("plugins",       "aether_os.gateway.routers.plugins_router",       "router",       {"prefix": "/v2"},         False),
        ("plugins_connectors", "aether_os.gateway.routers.plugins_connectors_router", "router", {"prefix": "/v2"},    False),
        ("cicd_webhook",  "aether_os.phases.p08_cicd.webhook",              "router",       {"tags": ["CI/CD"]},       False),
        ("client_portal", "aether_os.gateway.client_portal.routes",         "router",       {},                        False),
        ("mcp",           "aether_os.gateway.mcp_router",                   "router",       {},                        False),
        ("saml",          "aether_os.gateway.auth_saml",                    "saml_router",  {},                        False),
        ("oauth",         "aether_os.gateway.auth_oauth",                   "oauth_router", {},                        False),
        ("mfa",           "aether_os.gateway.auth_mfa",                     "mfa_router",   {},                        False),
        # Interactive Questionnaire System
        ("questionnaire", "aether_os.gateway.routers.questionnaire_router",  "router",       {},                        True),
    ]

    import importlib as _importlib
    for _rname, _rmod, _rattr, _rkw, _required in _ROUTERS:
        try:
            _m = _importlib.import_module(_rmod)
            app.include_router(getattr(_m, _rattr), **_rkw)
            logger.info("Mounted router: %s", _rname)
        except Exception as _exc:
            if _required:
                raise RuntimeError(
                    f"Critical router {_rname!r} ({_rmod}) failed to load — aborting startup: {_exc}"
                ) from _exc
            logger.warning("Optional router %s not loaded (non-fatal): %s", _rname, _exc)

    # ── Public landing page static assets (js/, images/, etc.)
    _public = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../public")
    )
    if os.path.isdir(_public):
        app.mount("/js", StaticFiles(directory=os.path.join(_public, "js")), name="public-js")

    # ── Dashboard static files — served by spa_router (see gateway/routers/spa_router.py)
    # Static asset mount: needed so /dashboard/assets/* are served directly by StaticFiles
    _dist = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../dashboard/dist")
    )
    if os.path.isdir(_dist):
        logger.info("Mounting dashboard static assets from %s", _dist)
        app.mount("/dashboard", StaticFiles(directory=_dist, html=True), name="dashboard")

    return app

# Module-level app instance (used when NOT in --factory mode)
app = create_app()
