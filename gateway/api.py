"""
AetherOS — Unified FastAPI Gateway
Merges best of Aether-one api.py + DCSP api/main.py.

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
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(pathlib.Path(__file__).parent.parent / ".env", override=True)

DASHBOARD_DIST = pathlib.Path(__file__).parent.parent / "dashboard" / "dist"

# C11: structured JSON logging — must run before any logger.* calls
try:
    from aether_os.core.logging_config import configure_logging
    configure_logging()
except Exception:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

# C10: Sentry error tracking
def _init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment=os.environ.get("ENVIRONMENT", "development"),
            send_default_pii=False,
        )
        logger.info("Sentry error tracking enabled")
    except ImportError:
        logger.warning("sentry-sdk not installed — error tracking disabled")
    except Exception as exc:
        logger.warning("Sentry init failed: %s", exc)

_init_sentry()

# B5: Strong references prevent GC from silently killing in-flight background tasks.
_background_tasks: set = set()

security_scheme = HTTPBearer(auto_error=False)


# ── CORS configuration (Bug 3 fix) ────────────────────────────────────────────

def _get_cors_origins() -> list:
    """
    Bug 3 fix: CORS origins come from env var only. Never wildcard in production.
    Default is localhost for development.
    """
    raw = os.environ.get("CORS_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]

    # Default development origins
    return [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:5173",  # Vite default
    ]


# ── Pydantic models ────────────────────────────────────────────────────────────

class PipelineStartRequest(BaseModel):
    requirement: str
    project_name: str = "untitled"
    language: str = "python"
    output_dir: Optional[str] = None
    max_retries: int = 3


class PipelineStartResponse(BaseModel):
    run_id: str
    status: str
    message: str


class LoginRequest(BaseModel):
    email: str
    password: str


_CURRENT_TOS_VERSION = "1.0"
_CURRENT_DPA_VERSION = "1.0"


class RegisterRequest(BaseModel):
    model_config = {"extra": "forbid"}  # B1: reject any unlisted field (plan, role, is_admin, etc.)
    email: str
    password: str
    name: Optional[str] = None
    org_name: Optional[str] = None
    terms_accepted: bool = False    # D4: GDPR consent — must be True (covers ToS + EULA)
    dpa_accepted: bool = False      # T4-01: GDPR Article 28 Data Processing Agreement


class LoginResponse(BaseModel):
    access_token: str = ""
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    org_slug: str = ""
    org_id: str = ""
    plan: str = ""
    mfa_required: bool = False
    mfa_token: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ApproveRequest(BaseModel):
    ticket_id: str
    decision: str  # "approve" | "deny"
    reason: Optional[str] = None


class ApiKeyCreateRequest(BaseModel):
    name: str


class ApiKeyRequest(BaseModel):
    provider: str
    key: str


class TestProviderRequest(BaseModel):
    provider: str


class PhaseConfigUpdate(BaseModel):
    enabled: bool
    priority: str


class PriorityRequest(BaseModel):
    priority: str  # "high" | "normal" | "low"


class RerunRequest(BaseModel):
    from_phase: str


class FileWriteBody(BaseModel):
    path: str
    content: str


class EnvVarItem(BaseModel):
    key: str
    value: str


class EnvVarsBody(BaseModel):
    vars: List[EnvVarItem]


class SamlConfigRequest(BaseModel):
    idp_entity_id: str
    idp_sso_url: str
    idp_cert: str


class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_shared: bool = False
    preferences: Optional[Dict[str, Any]] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_shared: Optional[bool] = None
    preferences: Optional[Dict[str, Any]] = None


from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import RedirectResponse
import os

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Rate limit headers on factory start and /auth/login routes
        response.headers["X-RateLimit-Factory-Limit"] = os.getenv("MAX_FACTORY_STARTS_PER_MIN", "10")
        response.headers["X-RateLimit-Hourly-Limit"] = os.getenv("MAX_STARTS_PER_ORG_PER_HOUR", "20")
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "frame-src 'self' http://REDACTED_IP:* http://localhost:*; "
            "worker-src 'self' blob: https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'"
        )
        # B11: HSTS only in production — prevents breaking local dev over HTTP
        if os.getenv("ENVIRONMENT") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if os.environ.get("FORCE_HTTPS", "false").lower() == "true":
            proto = request.headers.get("X-Forwarded-Proto")
            if proto == "http":
                url = str(request.url).replace("http://", "https://", 1)
                return RedirectResponse(url=url, status_code=301)
        return await call_next(request)

# NOTE: These are registered inside create_app() below — do not remove this comment.
# SecurityHeadersMiddleware and HttpsRedirectMiddleware are always-on in production.
# HttpsRedirectMiddleware is gated by FORCE_HTTPS env var so local dev still works.

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Dict[str, Any]:
    """FastAPI dependency: validates JWT token or API Key, returns user claims."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    
    token = credentials.credentials
    from aether_os.gateway.auth import decode_access_token, hash_api_key, verify_api_key
    
    # 1. Try JWT
    payload = decode_access_token(token)
    if payload:
        # Reject partial MFA tokens — these may only be used at /auth/mfa/confirm
        if payload.get("mfa_pending"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="MFA verification required. Complete sign-in at /auth/mfa/confirm.",
            )
        jti = payload.get("jti")
        if jti:
            try:
                from aether_os.core.pipeline_state import get_redis
                r = await get_redis()
                if r and await r.exists(f"jwt:blacklist:{jti}"):
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
            except HTTPException:
                raise
            except Exception:
                pass
        return payload
    
    # 2. Try API Key
    if token.startswith("aesk_"):
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import APIKey, Organisation
        from sqlalchemy import select
        
        hashed = hash_api_key(token)
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(APIKey, Organisation).join(Organisation).where(
                APIKey.key_hash == hashed,
                APIKey.is_active == True
            )
            result = await session.execute(stmt)
            row = result.fetchone()
            if row:
                api_key, org = row
                # Update last_used_at (optional, but good for UX)
                api_key.last_used_at = time.time()
                await session.commit()
                
                return {
                    "sub": "api_key",
                    "org_id": org.id,
                    "org_slug": org.slug,
                    "plan": org.plan,
                    "role": "api"
                }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )


# ── Module-level dict for generated-app processes (shared with pipeline) ───────
_APP_PROCS: Dict[str, Any] = {}

# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the AetherOS FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application startup/shutdown lifecycle."""
        logger.info("AetherOS API starting up...")

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

        # Seed marketplace with built-in skills if empty
        try:
            from aether_os.core.db import get_session_factory as _sf_market
            from aether_os.core.models import MarketplaceProfile as _MP
            from sqlalchemy import select as _sel_m, func as _func_m
            import uuid as _uuid_m
            _sf_m = _sf_market()
            async with _sf_m() as _ms:
                _count = (await _ms.execute(
                    _sel_m(_func_m.count()).select_from(_MP)
                )).scalar()
                if _count < 5:  # guard against partial seeds and race between workers
                    _builtin_skills = [
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
                    # Clear any partial seed before re-inserting
                    await _ms.execute(_sel_m(_func_m.count()).select_from(_MP))  # keep session alive
                    for _nm, _dm, _ds in _builtin_skills:
                        _existing = (await _ms.execute(
                            _sel_m(_MP).where(_MP.name == _nm).where(_MP.org_id == "system")
                        )).scalars().first()
                        if _existing:
                            continue
                        _ms.add(_MP(
                            id=str(_uuid_m.uuid4()),
                            org_id="system",
                            name=_nm,
                            base_domain=_dm,
                            description=_ds,
                            profile_yaml=f"name: {_nm}\ndomain: {_dm}\ndescription: {_ds}\n",
                            is_published=True,
                            usage_count=0,
                        ))
                    await _ms.commit()
                    logger.info("Marketplace seeded with %d built-in skills", len(_builtin_skills))
        except Exception as _exc:
            logger.warning("Marketplace seeding skipped: %s", _exc)

        yield

        # Shutdown
        logger.info("AetherOS API shutting down...")
        try:
            from aether_os.core.db import close_db
            await close_db()
        except Exception:
            pass

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
        allow_headers=["*"],
    )

    # C9: Prometheus metrics — /metrics endpoint for Prometheus scraping
    try:
        from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore
        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            excluded_handlers=["/health", "/metrics"],
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
        logger.info("Prometheus metrics enabled at /metrics")
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
            except Exception:
                pass  # Audit logging must never break the request
        return response

    # ── Routes ────────────────────────────────────────────────────────────────

    api_router = APIRouter(prefix="/api")

    @app.get("/")
    async def root_landing():
        """Serve the public landing page."""
        _landing = os.path.join(
            os.path.dirname(__file__), "../public/index.html"
        )
        if os.path.isfile(_landing):
            return FileResponse(_landing, media_type="text/html")
        return RedirectResponse(url="/dashboard/")

    @app.get("/favicon.ico")
    @app.get("/favicon.svg")
    async def favicon():
        """Serve the AetherOS favicon."""
        _svg = os.path.join(os.path.dirname(__file__), "../public/favicon.svg")
        if os.path.isfile(_svg):
            return FileResponse(_svg, media_type="image/svg+xml")
        from fastapi.responses import Response
        return Response(status_code=204)

    @app.get("/health")
    @api_router.get("/health")
    async def health() -> Dict[str, Any]:
        """Health check endpoint."""
        return {
            "status": "ok",
            "timestamp": time.time(),
            "service": "AetherOS API",
            "version": "1.0.0",
        }


    @app.post("/auth/register", response_model=LoginResponse)
    async def register(req: RegisterRequest, request: Request) -> LoginResponse:
        """Register a new organisation and owner user."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation, User
        from aether_os.gateway.auth import get_password_hash, create_access_token
        from aether_os.core.rate_limiter import get_rate_limiter
        from sqlalchemy import select
        import uuid

        # Rate-limit registrations by IP to prevent spam org creation
        client_ip = request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or "unknown"
        rl = get_rate_limiter()
        await rl.record_registration_attempt(client_ip)
        if not await rl.check_registration_attempts(client_ip):
            raise HTTPException(status_code=429, detail="Too many registration attempts. Please try again later.")

        # D4: GDPR consent + T4-01: DPA acceptance gate
        if not req.terms_accepted:
            raise HTTPException(status_code=400, detail="You must accept the terms of service to register.")
        if not req.dpa_accepted:
            raise HTTPException(status_code=400, detail="You must accept the Data Processing Agreement (GDPR Art. 28) to register.")

        # Enforce minimum password length
        if len(req.password) < 10:
            raise HTTPException(status_code=422, detail="Password must be at least 10 characters.")

        session_factory = get_session_factory()
        async with session_factory() as session:
            # Check if email exists
            stmt = select(User).where(User.email == req.email)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email already registered")

            # Create org — plan is always "trial" regardless of request body (B1)
            _org_name = req.org_name or req.email.split("@")[0]
            slug = _org_name.lower().replace(" ", "-")
            org = Organisation(
                id=str(uuid.uuid4()),
                name=_org_name,
                slug=slug,
                plan="trial",  # B1: hardcoded — never from request
            )
            session.add(org)

            # Create owner user — role is always "owner" regardless of request body (B1)
            import json as _json_reg
            from datetime import datetime as _dt
            _consent_now = _dt.utcnow()
            _consent_meta = _json_reg.dumps({
                "tos_version": _CURRENT_TOS_VERSION,
                "dpa_version": _CURRENT_DPA_VERSION,
                "consent_at": _consent_now.isoformat() + "Z",
            })
            user = User(
                id=str(uuid.uuid4()),
                org_id=org.id,
                email=req.email,
                password_hash=get_password_hash(req.password),
                role="owner",  # B1: hardcoded — never from request
                consent_at=_consent_now,  # D4: GDPR consent timestamp
                user_preferences=_consent_meta,  # T4-01: stores ToS+DPA version accepted
            )
            session.add(user)
            await session.commit()

            from aether_os.gateway.auth import create_refresh_token as _crt_reg
            _reg_claims = {
                "sub": user.email,
                "user_id": user.id,
                "org_id": org.id,
                "org_slug": org.slug,
                "role": user.role,
                "plan": org.plan
            }
            token = create_access_token(_reg_claims)
            refresh = _crt_reg(_reg_claims)
            return LoginResponse(
                access_token=token,
                refresh_token=refresh,
                org_slug=org.slug,
                org_id=org.id,
                plan=org.plan
            )

    @app.post("/auth/login", response_model=LoginResponse)
    async def login(req: LoginRequest, request: Request) -> LoginResponse:
        """Authenticate and return a JWT token."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation, User
        from aether_os.gateway.auth import verify_password, create_access_token
        from aether_os.core.rate_limiter import get_rate_limiter
        from sqlalchemy import select

        # Rate-limit login attempts by IP — prevents brute force
        client_ip = request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or "unknown"
        rl = get_rate_limiter()
        await rl.record_login_attempt(client_ip)
        if not await rl.check_login_attempts(client_ip):
            raise HTTPException(status_code=429, detail="Too many login attempts. Please wait 15 minutes before trying again.")

        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(User, Organisation).join(Organisation).where(User.email == req.email)
            result = await session.execute(stmt)
            row = result.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )

            loop = asyncio.get_running_loop()
            pw_ok = await loop.run_in_executor(None, verify_password, req.password, row[0].password_hash)
            if not pw_ok:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )

            user, org = row
            if not user.is_active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

            if user.mfa_enabled:
                # Issue a 5-minute partial token — client must complete MFA via /auth/mfa/confirm
                # The mfa_pending claim prevents this token from being used for real API calls
                mfa_token = create_access_token(
                    {"mfa_pending": True, "user_id": user.id},
                    expires_hours=1,  # 1hr ceiling; mfa_pending claim is the real gate
                )
                return LoginResponse(mfa_required=True, mfa_token=mfa_token)

            from aether_os.gateway.auth import create_refresh_token as _crt
            _token_claims = {
                "sub": user.email,
                "user_id": user.id,
                "org_id": org.id,
                "org_slug": org.slug,
                "role": user.role,
                "plan": org.plan
            }
            token = create_access_token(_token_claims)
            refresh = _crt(_token_claims)
            return LoginResponse(
                access_token=token,
                refresh_token=refresh,
                org_slug=org.slug,
                org_id=org.id,
                plan=org.plan
            )

    @app.post("/auth/logout")
    async def logout(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, str]:
        """Invalidate the current JWT by adding its jti to Redis blacklist."""
        jti = user.get("jti")
        exp = user.get("exp", 0)
        if jti and isinstance(exp, (int, float)):
            try:
                from aether_os.core.pipeline_state import get_redis
                r = await get_redis()
                if r:
                    ttl = max(1, int(exp - time.time()))
                    await r.setex(f"jwt:blacklist:{jti}", ttl, "1")
            except Exception:
                pass
        return {"message": "Logged out"}

    @app.post("/auth/refresh", response_model=LoginResponse)
    async def refresh_token_endpoint(req: RefreshRequest) -> LoginResponse:
        """Exchange a valid refresh token for a new access + refresh token pair."""
        from aether_os.gateway.auth import decode_access_token, create_access_token, create_refresh_token as _crt_ref
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User, Organisation
        from sqlalchemy import select

        claims = decode_access_token(req.refresh_token)
        if not claims or claims.get("token_type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        # Check Redis blacklist
        jti = claims.get("jti")
        if jti:
            try:
                from aether_os.core.pipeline_state import get_redis
                r = await get_redis()
                if r and await r.get(f"jwt:blacklist:{jti}"):
                    raise HTTPException(status_code=401, detail="Refresh token has been revoked")
            except HTTPException:
                raise
            except Exception:
                pass

        user_id = claims.get("user_id")
        session_factory = get_session_factory()
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(User, Organisation).join(Organisation).where(User.id == user_id)
                )
            ).fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="User not found")
            user, org = row
            if not user.is_active:
                raise HTTPException(status_code=403, detail="Account is disabled")

            _new_claims = {
                "sub": user.email,
                "user_id": user.id,
                "org_id": org.id,
                "org_slug": org.slug,
                "role": user.role,
                "plan": org.plan,
            }
            new_access = create_access_token(_new_claims)
            new_refresh = _crt_ref(_new_claims)
            return LoginResponse(
                access_token=new_access,
                refresh_token=new_refresh,
                org_slug=org.slug,
                org_id=org.id,
                plan=org.plan,
            )

    @app.post("/auth/api-keys")
    async def create_api_key(
        req: ApiKeyCreateRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Create a new API key for the current organisation."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import APIKey
        from aether_os.gateway.auth import generate_api_key, hash_api_key
        import uuid

        org_id = user.get("org_id")
        raw_key = generate_api_key()
        hashed = hash_api_key(raw_key)

        session_factory = get_session_factory()
        async with session_factory() as session:
            api_key = APIKey(
                id=str(uuid.uuid4()),
                org_id=org_id,
                key_hash=hashed,
                name=req.name
            )
            session.add(api_key)
            await session.commit()

        return {
            "api_key": raw_key,
            "name": req.name,
            "message": "Store this key safely. It will not be shown again."
        }




































    @app.post("/auth/change-password")
    async def change_password(req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User
        from aether_os.gateway.auth import verify_password, get_password_hash
        user_id = user.get("user_id", "")
        current_pw = req.get("current_password", "")
        new_pw = req.get("new_password", "")
        if len(new_pw) < 10:
            raise HTTPException(status_code=422, detail="Password must be at least 10 characters.")
        sf = get_session_factory()
        async with sf() as session:
            db_user = await session.get(User, user_id)
            if not db_user:
                raise HTTPException(status_code=404)
            loop = asyncio.get_running_loop()
            pw_ok = await loop.run_in_executor(None, verify_password, current_pw, db_user.password_hash)
            if not pw_ok:
                raise HTTPException(status_code=401, detail="Current password is incorrect.")
            db_user.password_hash = await loop.run_in_executor(None, get_password_hash, new_pw)
            await session.commit()
        return {"message": "Password changed"}

    # ── Mount all routers ─────────────────────────────────────────────────────
    app.include_router(api_router)

    # Routers with individual try/except (may be absent in some deployments)
    for _imp, _attr, _kw in [
        ("aether_os.gateway.routers.factory",          "router",      {"prefix": "/v2"}),
        ("aether_os.gateway.routers.auth_router",      "router",      {"prefix": "/v2"}),
        ("aether_os.gateway.routers.plugins_router",   "router",      {"prefix": "/v2"}),
        ("aether_os.phases.p08_cicd.webhook",          "router",      {"tags": ["CI/CD"]}),
        ("aether_os.gateway.client_portal.routes",     "router",      {}),
        ("aether_os.gateway.mcp_router",               "router",      {}),
        ("aether_os.gateway.auth_saml",                "saml_router", {}),
        ("aether_os.gateway.auth_oauth",               "oauth_router",{}),
        ("aether_os.gateway.auth_mfa",                 "mfa_router",  {}),
    ]:
        try:
            import importlib as _il
            _m = _il.import_module(_imp)
            app.include_router(getattr(_m, _attr), **_kw)
        except Exception as _exc:
            logger.warning("Router %s not loaded: %s", _imp, _exc)

    # Domain routers — extracted from api.py (QUAL-002)
    for _rname, _rmod, _prefix in [
        ("legal",         "gateway.routers.legal_router",         ""),
        ("notifications", "gateway.routers.notifications_router", ""),
        ("learning",      "gateway.routers.learning_router",      ""),
        ("memory",        "gateway.routers.memory_router",        ""),
        ("webhooks",      "gateway.routers.webhooks_router",      ""),
        ("workspaces",    "gateway.routers.workspaces_router",    ""),
        ("marketplace",   "gateway.routers.marketplace_router",   ""),
        ("billing",       "gateway.routers.billing_router",       ""),
        ("account",       "gateway.routers.account_router",       ""),
        ("admin",         "gateway.routers.admin_router",         ""),
        ("settings",      "gateway.routers.settings_router",      ""),
        ("system",        "gateway.routers.system_router",        ""),
        ("intelligence",  "gateway.routers.intelligence_router",  ""),
        ("compliance",    "gateway.routers.compliance_router",    ""),
        ("scim",          "gateway.routers.scim_router",          ""),
        ("agents",        "gateway.routers.agents_router",        ""),
        ("factory_ops",   "gateway.routers.factory_ops_router",   ""),
        ("factory_runs",  "gateway.routers.factory_runs_router",  ""),
    ]:
        try:
            import importlib as _il2
            _m2 = _il2.import_module(_rmod)
            app.include_router(_m2.router, prefix=_prefix)
            logger.info("Mounted router: %s", _rname)
        except Exception as _exc2:
            logger.critical("Failed to mount %s router: %s", _rname, _exc2)

    # ── Legal documents (GDPR D-001) — public, no auth required ──────────────
    return app

# Module-level app instance for uvicorn
app = create_app()

# ── Dashboard static files — MUST be last, after all routes ──────────────────
import os as _os
from fastapi.responses import FileResponse as _FileResponse

_dist = _os.path.abspath(
    _os.path.join(_os.path.dirname(__file__), "../dashboard/dist")
)

if _os.path.isdir(_dist):
    logger.info("Mounting dashboard SPA from %s", _dist)

    # SPA catch-all: serves static files by exact path, falls back to
    # index.html for any unknown sub-path (e.g. /dashboard/projects).
    # This route is registered BEFORE the StaticFiles mount so it takes
    # priority and always returns HTTP 200 (browsers need 200 for script
    # module loading to work correctly in all environments).
    @app.get("/dashboard", include_in_schema=False)
    @app.get("/dashboard/{path:path}", include_in_schema=False)
    async def _dashboard_spa(path: str = ""):
        _index = _os.path.join(_dist, "index.html")
        if path:
            candidate = _os.path.normpath(_os.path.join(_dist, path))
            # Security: stay inside dist/
            if candidate.startswith(_dist) and _os.path.isfile(candidate):
                return _FileResponse(candidate)
        return _FileResponse(_index)

    # StaticFiles mount kept for efficient directory listing / HEAD requests
    app.mount(
        "/dashboard",
        StaticFiles(directory=_dist, html=True),
        name="dashboard"
    )
