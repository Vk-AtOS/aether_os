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
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, status, Request, APIRouter, UploadFile, File as FastAPIFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
# Pydantic models and middleware classes live in api_helpers.py to keep this
# file under 600 lines. They are re-imported here for backwards compatibility
# with any code that imports them from gateway.api directly.
from aether_os.core.rate_limiter import get_client_ip
from aether_os.gateway.security import require_ci_auth
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
from aether_os.gateway.lifespan import create_lifespan  # noqa: E402

_init_sentry()

# B5: Strong references prevent GC from silently killing in-flight background tasks.
_background_tasks: set = set()

# Auth dependency — defined in gateway/dependencies.py to avoid circular imports.
# Re-exported here for any code that imports it from api directly.
from aether_os.gateway.dependencies import security_scheme, get_current_user  # noqa: E402


# NOTE: _get_cors_origins, Pydantic models, and middleware classes all live in
# api_helpers.py / api_utils.py — imported above. Duplicate definitions removed
# to keep this file under 600 lines.

# ── Generated-app process state — delegated to core.app_state (Redis-backed) ──
# These module-level names are kept for backwards compatibility with any code that
# still imports them directly; they delegate to the canonical storage in core.app_state.
from aether_os.core.app_state import get_all_procs as _get_all_procs, get_all_ports as _get_all_ports, _CURRENT_RUN_MEMORY as _APP_CURRENT_RUN  # noqa: E402

_APP_PROCS: Dict[str, Any] = _get_all_procs()   # same dict object as core.app_state._PROCS
_APP_PORTS: Dict[str, int] = _get_all_ports()   # same dict object as core.app_state._APP_PORTS

# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the AetherOS FastAPI application."""

    # Lifespan (startup/shutdown) logic extracted to gateway/lifespan.py to keep
    # this file under 600 lines.  create_lifespan() closes over _background_tasks
    # so the Guardian watchdog task is kept strongly referenced and won't be GC'd.
    lifespan = create_lifespan(_background_tasks)

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
    # GZip registered after CORS so it wraps the outer response (Starlette reverse order)
    app.add_middleware(GZipMiddleware, minimum_size=500)
    # C9: Prometheus metrics — instrumentation only; /metrics endpoint is in metrics_router
    try:
        from aether_os.core.prometheus_patch import apply as _apply_prom_patch
        _apply_prom_patch()  # must run before .instrument() — see core/prometheus_patch.py
        from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore
        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            excluded_handlers=["/health", "/metrics"],
        ).instrument(app)
        # No instrumentator.expose(): it mounted an unauthenticated /_metrics_internal that
        # bypassed the X-Metrics-Key check. metrics_router serves the same registry at /metrics.
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
                    from aether_os.gateway.auth import decode_bearer_token
                    claims = decode_bearer_token(auth[7:])
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
                            ip_address=get_client_ip(request),
                        ))
            except Exception as exc:
                # ARCH-H2: WARNING so failures are visible in production (DEBUG is off by default).
                # Audit log failures are a SOC-2/GDPR liability — "no events" must not be
                # indistinguishable from "events failed to write".
                logger.warning("Audit log write failed (non-fatal): %s", exc)
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
        ("run_fork",               "aether_os.gateway.routers.run_fork_router",                "router", {}, True),
        ("clarifying",             "aether_os.gateway.routers.clarifying_router",              "router", {}, True),
        ("factory_run_files",      "aether_os.gateway.routers.factory_run_files_router",       "router", {}, True),
        ("factory_run_streaming",  "aether_os.gateway.routers.factory_run_streaming_router",   "router", {}, True),
        ("factory_run_compliance", "aether_os.gateway.routers.factory_run_compliance_router",  "router", {}, True),
        ("run_app",           "aether_os.gateway.routers.run_app_router",           "router",       {},                        True),
        ("run_decisions",     "aether_os.gateway.routers.run_decisions_router",     "router",       {},                        True),
        ("run_spec",          "aether_os.gateway.routers.run_spec_router",          "router",       {},                        True),
        ("factory_decisions", "aether_os.gateway.routers.factory_decisions_router", "router",       {},                        True),
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
        ("app_preview",   "aether_os.gateway.routers.app_preview_router",   "router",       {},                        True),
        ("preview_session", "aether_os.gateway.routers.preview_session_router", "router",   {},                        True),
        ("prime",         "aether_os.gateway.routers.prime_router",         "router",       {},                        False),
        ("prime_inbox",   "aether_os.gateway.routers.prime_inbox_router",   "router",       {},                        False),
        ("prime_ledger",  "aether_os.gateway.routers.prime_ledger_router",  "router",       {},                        False),
        ("prime_service", "aether_os.gateway.routers.prime_service_router", "router",      {},                        False),
        ("ledger_anchor", "aether_os.gateway.routers.ledger_anchor_router", "router",       {},                        False),
        ("ledger_ops",    "aether_os.gateway.routers.ledger_ops_router",    "router",       {},                        False),
        ("velaris",       "aether_os.gateway.routers.velaris_router",       "router",       {},                        False),
        ("velaris_chat", "aether_os.gateway.routers.velaris_chat_router", "router", {}, False),
        ("velaris_mail", "aether_os.gateway.routers.velaris_mail_router", "router", {}, False),
        ("velaris_control", "aether_os.gateway.routers.velaris_control_router", "router", {}, False),
        ("velaris_hr", "aether_os.gateway.routers.velaris_hr_router", "router", {}, False),
        # --- Plugin / optional integrations ---
        ("plugins",       "aether_os.gateway.routers.plugins_router",       "router",       {"prefix": "/v2"},         False),
        ("plugins_connectors", "aether_os.gateway.routers.plugins_connectors_router", "router", {"prefix": "/v2"},    False),
        # Auth is attached at mount time: the router itself (phases/) declares none.
        ("cicd_webhook",  "aether_os.phases.p08_cicd.webhook",              "router",       {"tags": ["CI/CD"], "dependencies": [Depends(require_ci_auth)]}, False),
        ("client_portal", "aether_os.gateway.client_portal.routes",         "router",       {},                        False),
        ("portal_admin",  "aether_os.gateway.routers.portal_admin_router",  "router",       {},                        False),
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
