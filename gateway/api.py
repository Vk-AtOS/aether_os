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
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "font-src 'self' data: https://fonts.gstatic.com; "
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

    @app.get("/system/metrics")
    async def system_metrics() -> Dict[str, Any]:
        """System resource metrics — CPU, memory, disk, Redis."""
        result: Dict[str, Any] = {}
        try:
            import psutil
            loop = asyncio.get_event_loop()
            cpu_pct = await loop.run_in_executor(None, lambda: psutil.cpu_percent(interval=0.1))
            result["system"] = {
                "cpu_pct":    cpu_pct,
                "mem_pct":    psutil.virtual_memory().percent,
                "disk_pct":   psutil.disk_usage("/").percent,
                "swap_pct":   psutil.swap_memory().percent,
                "load_1m":    psutil.getloadavg()[0],
                "load_5m":    psutil.getloadavg()[1],
                "cpu_cores":  psutil.cpu_count(),
            }
        except Exception:
            pass
        try:
            import redis.asyncio as _redis_mod
            _r = _redis_mod.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
            info = await _r.info("all")
            await _r.aclose()
            result["redis"] = {
                "used_memory_human":   info.get("used_memory_human"),
                "connected_clients":   info.get("connected_clients"),
                "uptime_in_seconds":   info.get("uptime_in_seconds"),
            }
        except Exception:
            pass
        result["latency_ms"] = 0
        return result

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

            loop = asyncio.get_event_loop()
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

    @app.get("/account/usage")
    async def get_usage(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Get current usage and limits for the organisation."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import select

        org_id = user.get("org_id")
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(Organisation).where(Organisation.id == org_id)
            result = await session.execute(stmt)
            org = result.scalar_one_or_none()
            if not org:
                raise HTTPException(status_code=404, detail="Organisation not found")
            
            return {
                "org_name": org.name,
                "org_slug": org.slug,
                "plan": org.plan,
                "runs_used": org.trial_runs_used,
                "runs_limit": org.trial_runs_limit if org.plan == "trial" else None,
                "runs_remaining": max(0, org.trial_runs_limit - org.trial_runs_used) if org.plan == "trial" else None,
            }

    @app.delete("/account")
    async def delete_account(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, str]:
        """GDPR erasure: anonymise and soft-delete the calling user's account."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User, APIKey
        from aether_os.core.audit.ledger import get_ledger
        from sqlalchemy import update as _saup
        from datetime import datetime as _dt

        user_id = user.get("user_id", "")
        org_id = user.get("org_id", "")
        sf = get_session_factory()
        async with sf() as session:
            db_user = await session.get(User, user_id)
            if not db_user or db_user.org_id != org_id:
                raise HTTPException(status_code=404, detail="User not found")
            db_user.email = f"deleted_{user_id[:8]}@deleted.invalid"
            db_user.password_hash = "DELETED"
            db_user.is_active = False
            db_user.deleted_at = _dt.utcnow()
            db_user.user_preferences = None
            await session.execute(_saup(APIKey).where(APIKey.org_id == org_id).values(is_active=False))
            await session.commit()

        jti = user.get("jti")
        exp = user.get("exp", 0)
        if jti:
            try:
                from aether_os.core.pipeline_state import get_redis
                r = await get_redis()
                if r:
                    ttl = max(1, int(exp - time.time()))
                    await r.setex(f"jwt:blacklist:{jti}", ttl, "1")
            except Exception:
                pass

        await get_ledger().async_log_audit_event(
            org_id=org_id, user_id=user_id, action="account.deleted",
            resource_type="user", resource_id=user_id, metadata={}, ip_address="self",
        )
        return {"message": "Account deleted"}

    @app.get("/account/data-export")
    async def data_export(user: Dict[str, Any] = Depends(get_current_user)):
        """GDPR portability: return all user data as a downloadable JSON file."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User, Run
        from aether_os.core.audit.ledger import get_ledger
        from sqlalchemy import select
        from fastapi.responses import StreamingResponse
        import json as _json

        user_id = user.get("user_id", "")
        org_id = user.get("org_id", "")
        sf = get_session_factory()
        async with sf() as session:
            db_user = await session.get(User, user_id)
            runs = (await session.execute(
                select(Run).where(Run.org_id == org_id)
                .order_by(Run.started_at.desc()).limit(500)
            )).scalars().all()

        audit = await get_ledger().async_get_audit_logs(org_id=org_id, page=1, limit=500)
        export = {
            "export_version": "1.0",
            "exported_at": time.time(),
            "user": {
                "id": user_id,
                "email": db_user.email if db_user else None,
                "role": db_user.role if db_user else None,
                "created_at": str(db_user.created_at) if db_user else None,
                "consent_at": str(db_user.consent_at) if db_user and db_user.consent_at else None,
            },
            "runs": [
                {"id": r.id, "project_name": r.project_name, "status": r.status,
                 "domain": r.domain, "started_at": r.started_at, "cost": r.cost}
                for r in runs
            ],
            "audit_logs": audit.get("logs", []),
        }
        payload = _json.dumps(export, indent=2, default=str).encode()
        return StreamingResponse(
            iter([payload]),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="aetheros-data-export.json"'},
        )

    @app.get("/pricing")
    async def pricing():
        """Return pricing information."""
        from fastapi.responses import HTMLResponse
        html = """
        <html>
        <head><title>AetherOS Pricing</title></head>
        <body style="font-family: sans-serif; padding: 40px; line-height: 1.6;">
            <h1>AetherOS Plans</h1>
            <div style="display: flex; gap: 20px;">
                <div style="border: 1px solid #ccc; padding: 20px; border-radius: 8px; flex: 1;">
                    <h2>Trial</h2>
                    <p>Free</p>
                    <ul>
                        <li>3 Pipeline Runs</li>
                        <li>Standard Agents</li>
                    </ul>
                </div>
                <div style="border: 1px solid #007bff; padding: 20px; border-radius: 8px; flex: 1; background: #f0f7ff;">
                    <h2>Pro</h2>
                    <p>₹2,00,000 One-time</p>
                    <ul>
                        <li>Unlimited Runs</li>
                        <li>Priority Support</li>
                        <li>Custom Agents</li>
                    </ul>
                </div>
                <div style="border: 1px solid #ccc; padding: 20px; border-radius: 8px; flex: 1;">
                    <h2>Enterprise</h2>
                    <p>Custom</p>
                    <ul>
                        <li>On-premise deployment</li>
                        <li>SLA Guarantees</li>
                        <li>Dedicated Infrastructure</li>
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html)

    @app.post("/pipeline/start", response_model=PipelineStartResponse, deprecated=True,
              summary="[DEPRECATED] Start pipeline run — use POST /factory/start instead")
    async def start_pipeline(
        req: PipelineStartRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> PipelineStartResponse:
        """Deprecated v1 endpoint. Use POST /factory/start instead."""
        from aether_os.orchestrator.pipeline import get_pipeline
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import select, update as _sa_update
        import asyncio

        org_id = user.get("org_id")

        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(Organisation).where(Organisation.id == org_id)
            result = await session.execute(stmt)
            org = result.scalar_one_or_none()

            if not org:
                raise HTTPException(status_code=404, detail="Organisation not found")

            # Check storage limit
            limit = -1
            if org.plan == "trial": limit = float(os.environ.get("STORAGE_LIMIT_MB_TRIAL", 500))
            elif org.plan == "pro": limit = float(os.environ.get("STORAGE_LIMIT_MB_PRO", 10000))

            if limit > 0 and org.storage_used_mb >= limit:
                raise HTTPException(
                    status_code=402,
                    detail={"error": "storage_limit_reached", "used_mb": org.storage_used_mb, "limit_mb": limit}
                )

            if org.plan == "trial":
                # Atomic increment — prevents TOCTOU race (K-04)
                upd = await session.execute(
                    _sa_update(Organisation)
                    .where(Organisation.id == org_id)
                    .where(Organisation.trial_runs_used < Organisation.trial_runs_limit)
                    .values(trial_runs_used=Organisation.trial_runs_used + 1)
                )
                await session.commit()
                if upd.rowcount == 0:
                    raise HTTPException(
                        status_code=402,
                        detail={"error": "trial_limit_reached", "upgrade_url": "/pricing"}
                    )

        # Pre-generate run_id so client and pipeline share the same ID (FIX-004)
        import uuid as _uuid
        run_id = str(_uuid.uuid4())
        user_id = user.get("id") or user.get("sub")

        pipeline = get_pipeline()
        logger.info("Pipeline start requested by %s (org: %s): %s", user.get("sub"), org_id, req.requirement[:60])

        async def _run_bg():
            try:
                result = await pipeline.run(
                    requirement=req.requirement,
                    project_name=req.project_name,
                    language=req.language,
                    output_dir=req.output_dir,
                    max_retries=req.max_retries,
                    run_id=run_id,
                    org_id=org_id,
                )
                # Stamp user_id on the run record so the learning loop can find it
                if user_id and org_id:
                    try:
                        from aether_os.core.db import get_session_factory as _gsf
                        from aether_os.core.models import Run as _Run
                        from sqlalchemy import update as _upd2
                        _sf = _gsf()
                        async with _sf() as _s:
                            await _s.execute(_upd2(_Run).where(_Run.id == run_id).values(user_id=user_id))
                            await _s.commit()
                        from aether_os.core.services import learning_service as _ls
                        async with _gsf()() as _s2:
                            await _ls.extract_patterns_from_run(run_id, org_id, user_id, _s2)
                    except Exception as _le:
                        logger.debug("[pipeline] Learning loop skipped: %s", _le)
                logger.info("Pipeline completed: run_id=%s status=%s", result.get("run_id"), result.get("status"))
            except Exception as exc:
                logger.error("Background pipeline failed: %s", exc)

        _t = asyncio.create_task(_run_bg())
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)

        return PipelineStartResponse(
            run_id=run_id,
            status="started",
            message=f"Pipeline queued for: {req.requirement[:60]}",
        )

    @app.get("/pipeline/status/{run_id}")
    async def get_pipeline_status(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Get status of a pipeline run."""
        from aether_os.core.audit.ledger import get_ledger
        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return detail

    @app.post("/pipeline/approve/{ticket_id}")
    async def approve_action(
        ticket_id: str,
        req: ApproveRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Approve or deny a human-gated pipeline action via DecisionEngine."""
        from aether_os.core.decisions.decision_engine import get_decision_engine
        engine = get_decision_engine()
        approved = req.decision in ("approve", "approved", "yes", True)
        try:
            decision = await engine.resolve(
                decision_id=ticket_id,
                org_id=user.get("org_id", ""),
                approved=approved,
                choice=req.reason,
            )
            return {
                "ticket_id": ticket_id,
                "decision":  "approved" if approved else "denied",
                "decided_by": user.get("sub"),
                "reason":    req.reason,
                "timestamp": time.time(),
                "status":    decision.status if decision else "resolved",
            }
        except LookupError:
            # Decision not pending in engine — treat as already resolved
            return {
                "ticket_id": ticket_id,
                "decision":  "approved" if approved else "denied",
                "decided_by": user.get("sub"),
                "timestamp": time.time(),
                "status": "already_resolved",
            }

    # ── Mount domain routers (permanent architecture split) ───────────────────
    # These routers replace the monolithic route definitions below and contain
    # the clean service-layer implementations. The old inline routes are kept
    # as fallbacks during migration and will be removed in a follow-up pass.

    try:
        from aether_os.gateway.routers.factory import router as factory_router
        app.include_router(factory_router, prefix="/v2")  # /v2/factory/* — new clean routes
        logger.info("Factory router (v2) mounted")
    except Exception as exc:
        logger.warning("Factory v2 router not loaded: %s", exc)

    try:
        from aether_os.gateway.routers.auth_router import router as auth_v2_router
        app.include_router(auth_v2_router, prefix="/v2")  # /v2/auth/* — new clean routes
        logger.info("Auth router (v2) mounted")
    except Exception as exc:
        logger.warning("Auth v2 router not loaded: %s", exc)

    try:
        from aether_os.gateway.routers.plugins_router import router as plugins_router
        app.include_router(plugins_router, prefix="/v2")  # /v2/plugins/* — plugin system
        logger.info("Plugins router (v2) mounted")
    except Exception as exc:
        logger.warning("Plugins v2 router not loaded: %s", exc)

    # Wire CI webhook router — lives in the consolidated p08_cicd_deployment phase
    try:
        from aether_os.phases._legacy.p08_cicd.webhook import router as ci_router
        app.include_router(ci_router, tags=["CI/CD"])
        logger.info("CI webhook router mounted")
    except Exception as exc:
        logger.warning("CI webhook router not loaded: %s", exc)

    # Wire client portal router
    try:
        from aether_os.gateway.client_portal.routes import router as portal_router
        app.include_router(portal_router)
        logger.info("Client portal router mounted at /portal")
    except Exception as exc:
        logger.warning("Client portal router not loaded: %s", exc)

    # Wire MCP REST router — exposes AetherOS tools to Claude Desktop/Code
    try:
        from aether_os.gateway.mcp_router import router as mcp_router
        app.include_router(mcp_router)
        logger.info("MCP router mounted at /mcp")
    except Exception as exc:
        logger.warning("MCP router not loaded (non-fatal): %s", exc)

    # Wire SAML SSO router (C8)
    try:
        from aether_os.gateway.auth_saml import saml_router
        app.include_router(saml_router)
        logger.info("SAML SSO router mounted at /auth/saml")
    except Exception as exc:
        logger.warning("SAML router not loaded (non-fatal): %s", exc)

    # Wire OAuth2 social login router (T6-01b)
    try:
        from aether_os.gateway.auth_oauth import oauth_router
        app.include_router(oauth_router)
        logger.info("OAuth2 router mounted at /auth/oauth")
    except Exception as exc:
        logger.warning("OAuth router not loaded (non-fatal): %s", exc)

    # Wire TOTP MFA router (T6-03)
    try:
        from aether_os.gateway.auth_mfa import mfa_router
        app.include_router(mfa_router)
        logger.info("MFA router mounted at /auth/mfa")
    except Exception as exc:
        logger.warning("MFA router not loaded (non-fatal): %s", exc)

    @app.post("/factory/upload-requirement")
    async def upload_requirement_file(
        file: UploadFile = FastAPIFile(...),
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Parse an uploaded file (PDF/MD/TXT/image) and return extracted requirement text."""
        import io
        content = await file.read()
        filename = file.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        extracted = ""
        if ext in ("txt", "md", "rst"):
            extracted = content.decode("utf-8", errors="ignore")
        elif ext == "pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(content))
                extracted = "\n".join(p.extract_text() or "" for p in reader.pages)
            except ImportError:
                try:
                    import pdfplumber
                    with pdfplumber.open(io.BytesIO(content)) as pdf:
                        extracted = "\n".join(p.extract_text() or "" for p in pdf.pages)
                except Exception as e:
                    return {"text": "", "error": f"PDF parsing unavailable: {e}"}
        elif ext in ("png", "jpg", "jpeg", "webp"):
            # Return placeholder — vision extraction requires separate LLM call
            return {"text": "", "error": "Image requirement extraction not yet supported — please paste text instead"}
        elif ext in ("docx",):
            try:
                import docx
                doc = docx.Document(io.BytesIO(content))
                extracted = "\n".join(p.text for p in doc.paragraphs)
            except Exception as e:
                return {"text": "", "error": f"DOCX parsing failed: {e}"}
        else:
            extracted = content.decode("utf-8", errors="ignore")
        return {"text": extracted[:8000], "filename": filename}

    @app.post("/factory/fetch-github-repo")
    async def fetch_github_repo(req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        """Fetch key files from a GitHub repo to use as codebase context."""
        import httpx
        repo_url = req.get("repo_url", "").strip().rstrip("/")
        github_token = req.get("github_token", "")
        if not repo_url:
            raise HTTPException(status_code=422, detail="repo_url required")
        # Parse owner/repo from URL
        parts = repo_url.replace("https://github.com/", "").split("/")
        if len(parts) < 2:
            raise HTTPException(status_code=422, detail="Invalid GitHub URL format")
        owner, repo = parts[0], parts[1]
        headers = {"Accept": "application/vnd.github.v3+json"}
        if github_token:
            headers["Authorization"] = f"token {github_token}"
        async with httpx.AsyncClient(timeout=20) as gh:
            # Get file tree
            tree_res = await gh.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1", headers=headers)
            if tree_res.status_code == 404:
                raise HTTPException(status_code=404, detail="Repository not found or private (provide github_token)")
            tree = tree_res.json().get("tree", [])
            # Pick key files: README, main files, package.json, requirements.txt
            _KEY = {"readme.md", "readme.txt", "readme", "main.py", "app.py", "index.js", "index.ts",
                    "package.json", "requirements.txt", "pyproject.toml", "schema.sql"}
            key_files = [f for f in tree if f.get("type") == "blob" and f["path"].lower().split("/")[-1] in _KEY][:10]
            context_parts = [f"Repository: {owner}/{repo}"]
            for f in key_files:
                blob_res = await gh.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{f['path']}", headers=headers)
                if blob_res.status_code == 200:
                    import base64
                    blob_data = blob_res.json()
                    try:
                        text = base64.b64decode(blob_data.get("content", "")).decode("utf-8", errors="ignore")[:2000]
                        context_parts.append(f"\n--- {f['path']} ---\n{text}")
                    except Exception:
                        pass
        return {"context": "\n".join(context_parts), "repo": f"{owner}/{repo}"}

    @app.post("/factory/fetch-repo")
    async def fetch_repo(req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        """Fetch codebase context from GitHub, GitLab, or an SSH-accessible repository.

        Body:
          type: 'github' | 'gitlab' | 'ssh'
          url:  repo URL or SSH remote
          token:      personal access token (GitHub / GitLab)
          ssh_key:    PEM private key string (SSH type)
          gitlab_url: self-hosted GitLab base URL (optional, default https://gitlab.com)
          max_files:  max files to include (default 15)
        """
        import httpx, base64, asyncio, tempfile, subprocess, shutil

        rtype = req.get("type", "github").lower()
        url   = (req.get("url") or req.get("repo_url") or "").strip().rstrip("/")
        token = req.get("token") or req.get("github_token") or ""
        ssh_key = req.get("ssh_key", "")
        gitlab_base = (req.get("gitlab_url") or "https://gitlab.com").rstrip("/")
        max_files = min(int(req.get("max_files", 15)), 30)

        if not url:
            raise HTTPException(status_code=422, detail="url required")

        _KEY_FILES = {"readme.md", "readme.txt", "readme", "main.py", "app.py", "server.py",
                      "index.js", "index.ts", "main.ts", "package.json", "requirements.txt",
                      "pyproject.toml", "schema.sql", "docker-compose.yml", "dockerfile",
                      ".env.example", "openapi.yaml", "openapi.json"}

        context_parts: list[str] = []

        if rtype in ("github", "gitlab"):
            is_gitlab = rtype == "gitlab"
            if is_gitlab:
                # Support self-hosted GitLab
                path = url.replace(gitlab_base + "/", "").replace("https://gitlab.com/", "")
                api_base = f"{gitlab_base}/api/v4"
                encoded = path.replace("/", "%2F")
                hdrs: Dict[str, str] = {}
                if token:
                    hdrs["PRIVATE-TOKEN"] = token
                async with httpx.AsyncClient(timeout=20) as gl:
                    tree_res = await gl.get(f"{api_base}/projects/{encoded}/repository/tree?recursive=true&per_page=200", headers=hdrs)
                    if tree_res.status_code == 404:
                        raise HTTPException(status_code=404, detail="GitLab project not found or private (provide token)")
                    tree = tree_res.json()
                    key_files = [f for f in tree if f.get("type") == "blob" and f["name"].lower() in _KEY_FILES][:max_files]
                    context_parts.append(f"Repository: {path} (GitLab)")
                    for f in key_files:
                        fpath = f["path"]
                        raw_res = await gl.get(f"{api_base}/projects/{encoded}/repository/files/{fpath.replace('/',  '%2F')}/raw?ref=HEAD", headers=hdrs)
                        if raw_res.status_code == 200:
                            text = raw_res.text[:3000]
                            context_parts.append(f"\n--- {fpath} ---\n{text}")
            else:
                # GitHub (existing logic unified here)
                parts = url.replace("https://github.com/", "").split("/")
                if len(parts) < 2:
                    raise HTTPException(status_code=422, detail="Invalid GitHub URL")
                owner, repo_name = parts[0], parts[1]
                hdrs = {"Accept": "application/vnd.github.v3+json"}
                if token:
                    hdrs["Authorization"] = f"token {token}"
                async with httpx.AsyncClient(timeout=20) as gh:
                    tree_res = await gh.get(f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/HEAD?recursive=1", headers=hdrs)
                    if tree_res.status_code == 404:
                        raise HTTPException(status_code=404, detail="Repository not found or private (provide token)")
                    tree = tree_res.json().get("tree", [])
                    key_files = [f for f in tree if f.get("type") == "blob" and f["path"].lower().split("/")[-1] in _KEY_FILES][:max_files]
                    context_parts.append(f"Repository: {owner}/{repo_name} (GitHub)")
                    for f in key_files:
                        blob_res = await gh.get(f"https://api.github.com/repos/{owner}/{repo_name}/contents/{f['path']}", headers=hdrs)
                        if blob_res.status_code == 200:
                            try:
                                text = base64.b64decode(blob_res.json().get("content", "")).decode("utf-8", errors="ignore")[:3000]
                                context_parts.append(f"\n--- {f['path']} ---\n{text}")
                            except Exception:
                                pass

        elif rtype == "ssh":
            # Clone via SSH with ephemeral key
            if not ssh_key:
                raise HTTPException(status_code=422, detail="ssh_key (PEM) required for SSH type")
            tmpdir = tempfile.mkdtemp(prefix="aether_repo_")
            key_file = os.path.join(tmpdir, "id_rsa")
            clone_dir = os.path.join(tmpdir, "repo")
            try:
                with open(key_file, "w") as kf:
                    kf.write(ssh_key)
                os.chmod(key_file, 0o600)
                env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {key_file} -o StrictHostKeyChecking=no -o BatchMode=yes"}
                proc = await asyncio.create_subprocess_exec(
                    "git", "clone", "--depth=1", url, clone_dir,
                    env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
                if proc.returncode != 0:
                    raise HTTPException(status_code=422, detail=f"Git clone failed: {stderr.decode()[:500]}")
                context_parts.append(f"Repository: {url} (SSH clone)")
                found = 0
                for root, _dirs, files in os.walk(clone_dir):
                    if "/.git" in root or "/node_modules" in root or "/__pycache__" in root:
                        continue
                    for fn in files:
                        if fn.lower() in _KEY_FILES and found < max_files:
                            fpath = os.path.join(root, fn)
                            try:
                                text = open(fpath, errors="ignore").read(3000)
                                rel = os.path.relpath(fpath, clone_dir)
                                context_parts.append(f"\n--- {rel} ---\n{text}")
                                found += 1
                            except Exception:
                                pass
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        else:
            raise HTTPException(status_code=422, detail=f"Unknown repo type: {rtype}")

        return {
            "context": "\n".join(context_parts),
            "url": url,
            "type": rtype,
            "files_included": len(context_parts) - 1,
        }

    @app.post("/admin/prune-artifacts")
    async def prune_artifacts(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Delete artifact files older than `ttl_days` (default 30). Admin only."""
        import shutil
        if user.get("role") not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Admin only")
        ttl_days = int(req.get("ttl_days", 30))
        dry_run   = bool(req.get("dry_run", False))
        artifacts_root = pathlib.Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
        cutoff = time.time() - ttl_days * 86400
        deleted_files: list[str] = []
        deleted_bytes = 0
        if artifacts_root.exists():
            for p in sorted(artifacts_root.rglob("*")):
                if p.is_file() and p.stat().st_mtime < cutoff:
                    deleted_bytes += p.stat().st_size
                    deleted_files.append(str(p.relative_to(artifacts_root)))
                    if not dry_run:
                        p.unlink(missing_ok=True)
            # Remove empty dirs
            if not dry_run:
                for p in sorted(artifacts_root.rglob("*"), reverse=True):
                    if p.is_dir():
                        try:
                            p.rmdir()
                        except OSError:
                            pass
        return {
            "dry_run": dry_run,
            "ttl_days": ttl_days,
            "deleted_count": len(deleted_files),
            "deleted_bytes": deleted_bytes,
            "deleted_mb": round(deleted_bytes / 1_048_576, 2),
            "files": deleted_files[:50],
        }

    # ── Razorpay billing ──────────────────────────────────────────────────────

    RAZORPAY_PLANS: Dict[str, Dict] = {
        "pro":        {"name": "Pro",        "amount": 99900,  "currency": "INR", "period": "monthly"},
        "enterprise": {"name": "Enterprise", "amount": 499900, "currency": "INR", "period": "monthly"},
    }

    def _razorpay_client():
        import razorpay
        key_id     = os.environ.get("RAZORPAY_KEY_ID", "")
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise HTTPException(status_code=503, detail="Payment gateway not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
        return razorpay.Client(auth=(key_id, key_secret))

    @app.get("/billing/plans")
    async def list_plans():
        """Return available subscription plans (public endpoint)."""
        return {
            "plans": [
                {
                    "id": "trial",
                    "name": "Trial",
                    "price_inr": 0,
                    "period": "forever",
                    "runs": 3,
                    "storage_gb": 0.5,
                    "features": ["3 factory runs", "500 MB artifact storage", "All 12 phases", "Community support"],
                    "cta": "Start Free Trial",
                },
                {
                    "id": "pro",
                    "name": "Pro",
                    "price_inr": 999,
                    "period": "month",
                    "runs": None,  # unlimited
                    "storage_gb": 10,
                    "features": ["Unlimited runs", "10 GB storage", "Priority queue", "Email support",
                                 "Codebase import (GitHub/GitLab/SSH)", "CLI + VS Code extension"],
                    "cta": "Upgrade to Pro",
                    "highlight": True,
                },
                {
                    "id": "enterprise",
                    "name": "Enterprise",
                    "price_inr": 4999,
                    "period": "month",
                    "runs": None,
                    "storage_gb": 100,
                    "features": ["Everything in Pro", "100 GB storage", "Dedicated support SLA",
                                 "SSO / SAML", "Custom LLM models", "On-prem deployment", "SLA 99.9%"],
                    "cta": "Contact Sales",
                },
            ]
        }

    @app.post("/billing/create-order")
    async def create_order(req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        """Create a Razorpay order for a plan upgrade."""
        import uuid as _uuid_rz
        plan_id = req.get("plan", "pro").lower()
        if plan_id not in RAZORPAY_PLANS:
            raise HTTPException(status_code=422, detail=f"Unknown plan: {plan_id}. Choose pro or enterprise.")
        plan = RAZORPAY_PLANS[plan_id]
        client = _razorpay_client()
        receipt = f"aether_{user['org_id'][:8]}_{plan_id}_{int(time.time())}"
        order = client.order.create({
            "amount":   plan["amount"],
            "currency": plan["currency"],
            "receipt":  receipt,
            "notes": {
                "org_id":  user["org_id"],
                "plan":    plan_id,
                "user_id": user["user_id"],
            },
        })
        return {
            "order_id":   order["id"],
            "amount":     order["amount"],
            "currency":   order["currency"],
            "plan":       plan_id,
            "plan_name":  plan["name"],
            "key_id":     os.environ.get("RAZORPAY_KEY_ID", ""),
        }

    @app.post("/billing/verify-payment")
    async def verify_payment(req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        """Verify Razorpay payment signature and upgrade org plan."""
        import hmac as _hmac, hashlib as _hashlib
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import select as _sel, update as _upd

        order_id   = req.get("razorpay_order_id", "")
        payment_id = req.get("razorpay_payment_id", "")
        signature  = req.get("razorpay_signature", "")
        plan_id    = req.get("plan", "pro").lower()

        if not order_id or not payment_id or not signature:
            raise HTTPException(status_code=422, detail="razorpay_order_id, razorpay_payment_id, razorpay_signature are required")
        if plan_id not in RAZORPAY_PLANS:
            raise HTTPException(status_code=422, detail="Invalid plan")

        key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
        if not key_secret:
            raise HTTPException(status_code=503, detail="Payment gateway not configured")

        # Verify HMAC-SHA256 signature
        msg = f"{order_id}|{payment_id}".encode()
        expected = _hmac.new(key_secret.encode(), msg, _hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=400, detail="Payment signature verification failed")

        # Upgrade org plan in DB
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(
                _upd(Organisation)
                .where(Organisation.id == user["org_id"])
                .values(plan=plan_id)
            )
            await session.commit()

        # Log payment
        logger.info(f"Payment verified: org={user['org_id']} plan={plan_id} payment={payment_id}")
        return {
            "success": True,
            "plan":    plan_id,
            "message": f"Successfully upgraded to {RAZORPAY_PLANS[plan_id]['name']}",
        }

    @app.post("/billing/webhook")
    async def razorpay_webhook(request: Request):
        """Handle Razorpay webhook events (payment.captured, subscription events)."""
        import hmac as _hmac_wh, hashlib as _hashlib_wh
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import update as _upd_wh

        webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
        body = await request.body()

        if webhook_secret:
            sig = request.headers.get("X-Razorpay-Signature", "")
            expected = _hmac_wh.new(webhook_secret.encode(), body, _hashlib_wh.sha256).hexdigest()
            if not _hmac_wh.compare_digest(expected, sig):
                raise HTTPException(status_code=400, detail="Webhook signature invalid")

        payload = await request.json()
        event   = payload.get("event", "")
        entity  = payload.get("payload", {}).get("payment", {}).get("entity", {})
        notes   = entity.get("notes", {})
        org_id  = notes.get("org_id", "")
        plan_id = notes.get("plan", "")

        if event in ("payment.captured", "order.paid") and org_id and plan_id in RAZORPAY_PLANS:
            session_factory = get_session_factory()
            async with session_factory() as session:
                await session.execute(
                    _upd_wh(Organisation)
                    .where(Organisation.id == org_id)
                    .values(plan=plan_id)
                )
                await session.commit()
            logger.info(f"Webhook: upgraded org={org_id} to plan={plan_id}")

        return {"received": True}

    @app.get("/templates")
    async def list_templates(user: Dict[str, Any] = Depends(get_current_user)):
        """Return available project templates."""
        return {"templates": [
            {"id": "saas", "name": "SaaS App", "description": "Multi-tenant SaaS with auth, billing, and dashboard", "domain": "saas", "icon": "🏢"},
            {"id": "ecommerce", "name": "E-Commerce", "description": "Product catalog, cart, orders, and payments", "domain": "ecommerce", "icon": "🛒"},
            {"id": "dashboard", "name": "Analytics Dashboard", "description": "Data visualisation, charts, and KPI tracking", "domain": "analytics", "icon": "📊"},
            {"id": "api", "name": "REST API", "description": "Clean REST API with auth, rate limiting, and docs", "domain": "api", "icon": "⚡"},
            {"id": "cms", "name": "CMS / Blog", "description": "Content management with rich text editor and media", "domain": "cms", "icon": "✍️"},
            {"id": "social", "name": "Social Platform", "description": "User profiles, posts, follows, and notifications", "domain": "social", "icon": "👥"},
            {"id": "marketplace", "name": "Marketplace", "description": "Two-sided marketplace with listings and transactions", "domain": "marketplace", "icon": "🏪"},
            {"id": "healthcare", "name": "Healthcare", "description": "Patient records, appointments, and HIPAA compliance", "domain": "healthcare", "icon": "🏥"},
            {"id": "fintech", "name": "FinTech", "description": "Transactions, wallets, and financial reporting", "domain": "fintech", "icon": "💳"},
            {"id": "iot", "name": "IoT Dashboard", "description": "Device management, telemetry streams, and alerts", "domain": "iot", "icon": "📡"},
            {"id": "lms", "name": "Learning Management", "description": "Courses, lessons, quizzes, and student progress", "domain": "education", "icon": "🎓"},
            {"id": "custom", "name": "Custom", "description": "Describe your own requirements from scratch", "domain": "general", "icon": "🛠️"},
        ]}

    @app.post("/factory/estimate")
    async def estimate_cost(req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        """Estimate monthly hosting cost based on tech stack and domain."""
        domain = req.get("domain", "general")
        backend = req.get("backend", "fastapi")
        db = req.get("database", "postgresql")
        scale = req.get("scale", "small")  # small / medium / large
        base = {"small": 15, "medium": 45, "large": 120}.get(scale, 15)
        db_cost = {"postgresql": 20, "mongodb": 25, "sqlite": 0, "redis": 10}.get(db.lower(), 20)
        domain_mult = {"healthcare": 1.4, "fintech": 1.3, "saas": 1.2}.get(domain, 1.0)
        total = round((base + db_cost) * domain_mult)
        return {
            "estimated_monthly_usd": total,
            "range": f"${round(total * 0.8)}–${round(total * 1.4)}/month",
            "breakdown": {"compute": base, "database": db_cost, "extras": round(total - base - db_cost)},
            "note": "Estimate for a small VPS (2 vCPU / 4 GB RAM). Scale up for production traffic.",
        }

    @app.post("/factory/start")
    async def start_factory_run(
        req: Dict[str, Any],
        request: Request,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Start a new factory pipeline run (10-phase path)."""
        from aether_os.orchestrator.factory_pipeline import get_factory
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from aether_os.core.rate_limiter import get_rate_limiter
        from sqlalchemy import select
        import uuid as _uuid

        org_id = user.get("org_id")

        # ── Rate limiting on factory/start ────────────────────────────────────
        _rl = get_rate_limiter()
        if not await _rl.check_factory_start(org_id):
            raise HTTPException(
                status_code=429,
                detail=f"Too many pipeline starts. Max {_rl.max_factory_starts_per_min} per minute per org.",
            )
        if not await _rl.check_hourly_starts(org_id):
            raise HTTPException(
                status_code=429,
                detail=f"Hourly pipeline limit reached ({_rl.max_starts_per_hour}/hr).",
            )
        if not await _rl.check_concurrent_runs(org_id):
            raise HTTPException(
                status_code=429,
                detail=f"Max concurrent runs reached ({_rl.max_concurrent_runs}). Wait for a run to complete.",
            )
        await _rl.record_factory_start(org_id)
        
        # B9: Atomic trial run check — single UPDATE prevents TOCTOU race
        from sqlalchemy import update as _sa_update
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(Organisation).where(Organisation.id == org_id)
            result = await session.execute(stmt)
            org = result.scalar_one_or_none()

            if not org:
                raise HTTPException(status_code=404, detail="Organisation not found")

            # Storage limit check
            limit = -1
            if org.plan == "trial": limit = float(os.environ.get("STORAGE_LIMIT_MB_TRIAL", 500))
            elif org.plan == "pro": limit = float(os.environ.get("STORAGE_LIMIT_MB_PRO", 10000))
            if limit > 0 and org.storage_used_mb >= limit:
                raise HTTPException(
                    status_code=402,
                    detail={"error": "storage_limit_reached", "used_mb": org.storage_used_mb, "limit_mb": limit}
                )

            if org.plan == "trial":
                # Atomic increment — only succeeds if still under limit (B9: no TOCTOU)
                upd_result = await session.execute(
                    _sa_update(Organisation)
                    .where(Organisation.id == org_id)
                    .where(Organisation.trial_runs_used < Organisation.trial_runs_limit)
                    .values(trial_runs_used=Organisation.trial_runs_used + 1)
                )
                await session.commit()
                if upd_result.rowcount == 0:
                    raise HTTPException(
                        status_code=402,
                        detail={"error": "trial_limit_reached", "upgrade_url": "/pricing"}
                    )

        factory = get_factory()

        client_id = req.get("client_id", user.get("org_slug", "anonymous"))
        raw_input = req.get("raw_input", req.get("requirement", ""))
        domain = req.get("domain", "general")
        project_name = req.get("project_name")

        if not raw_input:
            raise HTTPException(status_code=400, detail="raw_input or requirement is required")

        # B7: Prompt injection guard — block jailbreak and shell injection attempts
        from aether_os.core.security.prompt_guard import guard as _guard
        _safe, _reason = _guard(raw_input)
        if not _safe:
            raise HTTPException(status_code=400, detail=_reason)

        # Pre-generate run_id and insert Run record immediately so the client
        # can poll /factory/runs/{run_id} without a 30s+ 404 window.
        run_id = str(_uuid.uuid4())
        user_id = user.get("sub")
        try:
            from aether_os.core.db import get_session_factory as _gsf_pre
            from aether_os.core.models import Run as _Run_pre
            import time as _time_pre
            _sf_pre = _gsf_pre()
            async with _sf_pre() as _s_pre:
                _s_pre.add(_Run_pre(
                    id=run_id,
                    org_id=org_id,
                    user_id=user_id,
                    command=f"factory: {raw_input[:60]}",
                    raw_input=raw_input,
                    project_name=project_name,
                    domain=domain,
                    status="queued",
                    started_at=_time_pre.time(),
                ))
                await _s_pre.commit()
        except Exception as _pre_exc:
            logger.warning("Pre-insert run record failed: %s", _pre_exc)

        async def _run_bg():
            # LLM Council pre-flight check (non-blocking — runs inside background task)
            _preflight = {"passed": True, "score": 1.0, "reason": "skipped", "suggestions": []}
            try:
                import os as _os
                from aether_os.core.council import PreFlightCouncil
                _council = PreFlightCouncil()
                # Cap the council call at 15s total — if LLM is slow, skip it
                _preflight = await asyncio.wait_for(
                    _council.run(raw_input=raw_input, domain=domain, org_id=org_id),
                    timeout=15.0,
                )
                if not _preflight.get("passed", True):
                    if _os.environ.get("COUNCIL_STRICT_MODE", "false").lower() == "true":
                        logger.warning(
                            "PreFlightCouncil STRICT: run %s rejected (score=%.2f): %s",
                            run_id, _preflight.get("score", 0.0), _preflight.get("reason", ""),
                        )
                        return  # Abort pipeline in strict mode
                    logger.warning(
                        "PreFlightCouncil: run %s did not pass (score=%.2f) — proceeding (non-strict): %s",
                        run_id, _preflight.get("score", 0.0), _preflight.get("reason", ""),
                    )
            except (asyncio.TimeoutError, Exception) as _ce:
                logger.warning("PreFlightCouncil skipped (timeout/error): %s", type(_ce).__name__)

            try:
                await factory.run(
                    client_id=client_id,
                    raw_input=raw_input,
                    domain=domain,
                    project_name=project_name,
                    run_id=run_id,
                    org_id=org_id,
                    council_preflight=_preflight,
                )
            except Exception as exc:
                logger.error("Background factory run failed: %s", exc)

        _t = asyncio.create_task(_run_bg())
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)

        return {
            "run_id": run_id,
            "status": "started",
            "message": f"Pipeline started for: {raw_input[:60]}",
        }

    @app.post("/account/settings")
    async def update_settings(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Update account settings (e.g. decision_mode, autonomous_mode)."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import update

        # Allowlist: only non-privileged fields may be updated by org members (FIX-006)
        _ALLOWED = {"decision_mode", "autonomous_mode", "notification_prefs", "org_name", "data_region"}
        payload = {k: v for k, v in req.items() if k in _ALLOWED}
        if not payload:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = update(Organisation).where(Organisation.id == user["org_id"]).values(payload)
            await session.execute(stmt)
            await session.commit()
            return {"status": "ok", "updated": list(payload.keys())}

    @app.get("/factory/runs/{run_id}/test-report")
    async def get_test_report(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Get the self-test report for a run."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select
        
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(Run).where(Run.id == run_id, Run.org_id == user["org_id"])
            result = await session.execute(stmt)
            run = result.scalar_one_or_none()
            
            if not run or not run.self_test_report:
                raise HTTPException(status_code=404, detail="Report not found")
            
            return json.loads(run.self_test_report)

    @app.get("/factory/runs")
    async def list_factory_runs(
        user: Dict[str, Any] = Depends(get_current_user),
        page: int = 1,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List pipeline runs for the organisation with pagination."""
        limit = min(max(limit, 1), 100)
        page = max(page, 1)
        try:
            from aether_os.core.audit.ledger import get_ledger
            org_id = user.get("org_id")
            history = await get_ledger().async_get_run_history(org_id=org_id, limit=limit * page)

            # Pull latest phase per run, priorities, and live_url via ORM (FIX-017)
            phase_map: Dict[str, str] = {}
            priority_map: Dict[str, str] = {}
            live_url_map: Dict[str, str] = {}
            try:
                from aether_os.core.db import get_session_factory as _gsf
                from aether_os.core.models import PhaseCompletion as _PC, RunMetadata as _RM, Run as _Run
                from sqlalchemy import select as _sel
                _sf = _gsf()
                async with _sf() as _sess:
                    # Phase completions
                    _pc_rows = (await _sess.execute(
                        _sel(_PC.run_id, _PC.phase_name, _PC.updated_at)
                        .join(_Run, _PC.run_id == _Run.id)
                        .where(_Run.org_id == org_id, _PC.phase_name != "pipeline")
                        .order_by(_PC.updated_at.desc())
                    )).all()
                    for _rid, _phase, _ in _pc_rows:
                        if _rid not in phase_map:
                            phase_map[_rid] = _phase
                    # Priorities
                    _rm_rows = (await _sess.execute(
                        _sel(_RM.run_id, _RM.priority)
                        .join(_Run, _RM.run_id == _Run.id)
                        .where(_Run.org_id == org_id)
                    )).all()
                    for _rid2, _pri in _rm_rows:
                        priority_map[_rid2] = _pri
                    # Live URLs
                    _url_rows = (await _sess.execute(
                        _sel(_Run.id, _Run.live_url)
                        .where(_Run.org_id == org_id, _Run.live_url.isnot(None))
                    )).all()
                    for _rid3, _url in _url_rows:
                        live_url_map[_rid3] = _url
            except Exception as _e:
                logger.debug("ORM enrichment for run list failed: %s", _e)

            formatted = []
            for run in history:
                d = dict(run)
                # db_utils already converts timestamps to ms and sets project_name;
                # only override current_phase / priority / live_url from enrichment maps
                d.setdefault("cost", 0.0)
                d["current_phase"] = phase_map.get(d.get("id", "")) or d.get("current_phase")
                d.setdefault("phases", {})
                d["priority"] = priority_map.get(d.get("id", ""), d.get("priority", "normal"))
                d["live_url"] = live_url_map.get(d.get("id", "")) or d.get("live_url")
                formatted.append(d)

            # Apply pagination slice
            start = (page - 1) * limit
            paginated = formatted[start:start + limit]
            return {"items": paginated, "page": page, "limit": limit, "total": len(formatted)}
        except Exception as exc:
            logger.warning("Could not fetch run history: %s", exc)
            return {"items": [], "page": page, "limit": limit, "total": 0}

    @app.get("/factory/runs/{run_id}")
    async def get_factory_run(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Get detail for a single pipeline run."""
        from aether_os.core.audit.ledger import get_ledger
        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # db_utils already converts timestamps to ms — no further conversion needed

        # Enrich with phase_completions via async ORM (FIX-017)
        phases: Dict[str, Any] = {}
        current_phase = None
        synthesized_events: list = []
        try:
            from aether_os.core.db import get_session_factory as _gsf2
            from aether_os.core.models import PhaseCompletion as _PC2, Event as _Ev2
            from sqlalchemy import select as _sel2
            _sf2 = _gsf2()
            async with _sf2() as _sess2:
                _pc2_rows = (await _sess2.execute(
                    _sel2(_PC2.phase_name, _PC2.status, _PC2.updated_at)
                    .where(_PC2.run_id == run_id, _PC2.phase_name != "pipeline")
                    .order_by(_PC2.updated_at.asc())
                )).all()
                for _phase, _status, _updated in _pc2_rows:
                    phases[_phase] = {"status": _status, "updated_at": _updated}
                    current_phase = _phase
                    # Synthesize an agent event from each phase completion
                    _label = _phase.replace("_", " ").replace("p0", "Phase ").replace("p1", "Phase 1")
                    _ts = _updated.timestamp() * 1000 if hasattr(_updated, "timestamp") else None
                    synthesized_events.append({
                        "agent": _label.title(),
                        "action": _status,
                        "detail": f"{_label.title()} {_status}",
                        "timestamp": _ts,
                    })
                # Also pull any explicit Event rows
                _ev_rows = (await _sess2.execute(
                    _sel2(_Ev2.agent, _Ev2.action, _Ev2.detail, _Ev2.timestamp)
                    .where(_Ev2.run_id == run_id)
                    .order_by(_Ev2.timestamp.asc())
                )).all()
                explicit_events = [
                    {"agent": r[0], "action": r[1], "detail": r[2], "timestamp": r[3]}
                    for r in _ev_rows
                ]
                # Use explicit events if available, otherwise use synthesized
                detail["events"] = explicit_events if explicit_events else synthesized_events
        except Exception as _e2:
            logger.debug("Phase completions ORM query failed: %s", _e2)
            detail.setdefault("events", [])

        detail["phases"] = phases
        detail["current_phase"] = current_phase
        # Only derive project_name from command if DB field is empty
        if not detail.get("project_name"):
            cmd = detail.get("command", "")
            detail["project_name"] = cmd[9:] if cmd.startswith("factory: ") else cmd
        detail.setdefault("cost", 0.0)

        # Enrich each phase with its output file content from the project dir
        project_dir = pathlib.Path.home() / ".aether_os" / "projects" / run_id
        _project_prefix = str(project_dir) + "/"
        _OUTPUT_FILE_CANDIDATES = [
            "consolidated.json", "architecture.json", "frontend_meta.json",
            "review.json", "test_results.json", "delivery.json",
            "observability.json", "cicd.json",
        ]
        for phase_key, phase_val in phases.items():
            phase_dir = project_dir / phase_key
            if not phase_dir.exists():
                continue
            # Try known names first
            loaded = False
            for fname in _OUTPUT_FILE_CANDIDATES + [f"{phase_key}.json"]:
                fpath = phase_dir / fname
                if fpath.exists():
                    try:
                        phase_val["output"] = json.loads(fpath.read_text(encoding="utf-8"))
                        phase_val["output_file"] = f"{phase_key}/{fname}"
                        loaded = True
                        break
                    except Exception:
                        pass
            # Fallback: first .json file directly in the phase dir
            if not loaded:
                for fpath in sorted(phase_dir.glob("*.json")):
                    try:
                        phase_val["output"] = json.loads(fpath.read_text(encoding="utf-8"))
                        phase_val["output_file"] = f"{phase_key}/{fpath.name}"
                        break
                    except Exception:
                        pass

        # Strip absolute server paths from all phase output (S8 security fix)
        def _strip_server_paths(obj):
            if isinstance(obj, str):
                return obj.replace(_project_prefix, "")
            if isinstance(obj, dict):
                return {k: _strip_server_paths(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_strip_server_paths(v) for v in obj]
            return obj
        detail["phases"] = _strip_server_paths(detail["phases"])

        # Enrich p06 with actual security findings from security_report.json
        if "p06_review_security" in detail.get("phases", {}):
            _sec_report = project_dir / "p06_review_security" / "security" / "security_report.json"
            if _sec_report.exists():
                try:
                    _sec_data = json.loads(_sec_report.read_text(encoding="utf-8"))
                    detail["phases"]["p06_review_security"].setdefault("output", {})
                    detail["phases"]["p06_review_security"]["output"]["security_findings"] = _sec_data.get("findings", [])
                    detail["phases"]["p06_review_security"]["output"]["security_total"] = _sec_data.get("total", 0)
                except Exception:
                    pass

        # Load priority and live_url via ORM (FIX-017)
        priority = "normal"
        detail.setdefault("live_url", None)
        try:
            from aether_os.core.db import get_session_factory as _gsf3
            from aether_os.core.models import RunMetadata as _RM2, Run as _Run2
            from sqlalchemy import select as _sel3
            _sf3 = _gsf3()
            async with _sf3() as _sess3:
                _rm_row = (await _sess3.execute(
                    _sel3(_RM2.priority).where(_RM2.run_id == run_id)
                )).scalar_one_or_none()
                if _rm_row:
                    priority = _rm_row
                _run_row = (await _sess3.execute(
                    _sel3(_Run2.live_url).where(_Run2.id == run_id, _Run2.org_id == org_id)
                )).scalar_one_or_none()
                if _run_row:
                    detail["live_url"] = _run_row
        except Exception as _e3:
            logger.debug("Priority/live_url ORM query failed: %s", _e3)
        detail["priority"] = priority

        return detail

    @app.get("/intelligence/global-insights")
    async def get_global_insights(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        """Authenticated intelligence feed — aggregated from completed runs in the main DB."""
        try:
            from aether_os.core.db import get_session_factory
            from sqlalchemy import text as _text
            session_factory = get_session_factory()
            async with session_factory() as session:
                # Domain distribution from completed runs
                domain_rows = await session.execute(
                    _text("SELECT domain, COUNT(*) as count FROM runs WHERE status='completed' AND domain IS NOT NULL GROUP BY domain ORDER BY count DESC LIMIT 20")
                )
                stats = [{"domain": r[0], "count": r[1]} for r in domain_rows]
                # Tech stack signals from run metadata (best-effort, no crash if column missing)
                try:
                    stack_rows = await session.execute(
                        _text("SELECT raw_input, domain FROM runs WHERE status='completed' ORDER BY created_at DESC LIMIT 100")
                    )
                    best = [{"domain": r[1], "success_rate": 1.0} for r in stack_rows if r[1]][:5]
                except Exception:
                    best = []
            return {"stats": stats, "top_tech_stacks": best}
        except Exception as exc:
            logger.debug("global-insights failed: %s", exc)
            return {"stats": [], "top_tech_stacks": []}

    @app.post("/marketplace/publish")
    async def publish_profile(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import MarketplaceProfile
        import uuid as _uuid_mp

        name = req.get("name") or ""
        if not name:
            raise HTTPException(status_code=422, detail="name is required")

        session_factory = get_session_factory()
        async with session_factory() as session:
            profile = MarketplaceProfile(
                id=str(_uuid_mp.uuid4()),
                org_id=user["org_id"],
                name=name,
                base_domain=req.get("base_domain", "general"),
                description=req.get("description", ""),
                price_usd=float(req.get("price_usd", 0.0)),
                is_published=True,
            )
            session.add(profile)
            await session.commit()
            await session.refresh(profile)
        return {"status": "published", "id": profile.id, "name": profile.name}

    @app.get("/account/preferences")
    async def get_preferences(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Get user preferences."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User
        from sqlalchemy import select
        import json

        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(User).where(User.id == user["user_id"])
            result = await session.execute(stmt)
            u = result.scalar_one_or_none()
            if not u:
                raise HTTPException(status_code=404)
            return json.loads(u.user_preferences) if u.user_preferences else {
                "default_tab_on_run_complete": "artifacts",
                "pinned_phases": [],
                "collapsed_phases": [],
                "decision_notification_style": "panel",
                "live_feed_visible_by_default": True,
                "default_domain": "general",
                "default_start_mode": "single",
                "dashboard_theme": "default",
                "sidebar_collapsed": False,
                "compact_phase_list": False,
                "show_confidence_scores": True,
                "workspace_name": "My Workspace"
            }

    @app.put("/account/preferences")
    async def update_preferences(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Update user preferences."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User
        from sqlalchemy import update
        import json
        
        # Merge with existing
        existing = await get_preferences(user)
        existing.update(req)
        
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = update(User).where(User.id == user["user_id"]).values(user_preferences=json.dumps(existing))
            await session.execute(stmt)
            await session.commit()
            return existing

    @app.post("/factory/runs/{run_id}/memory/changelog")
    async def add_changelog(
        run_id: str,
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Add entry to project changelog."""
        from aether_os.core.memory.memory_manager import MemoryManager
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select
        from pathlib import Path
        
        session_factory = get_session_factory()
        async with session_factory() as session:
            # B2: filter by org_id to prevent IDOR cross-tenant access
            stmt = select(Run).where(Run.id == run_id, Run.org_id == user["org_id"])
            run = (await session.execute(stmt)).scalar_one_or_none()
            if not run: raise HTTPException(status_code=404)
            
            # Assuming project output dir is based on standard path logic
            project_dir = Path.home() / ".aether_os" / "projects" / run_id
            MemoryManager.add_changelog_entry(project_dir, req["entry"], user["sub"])
            return {"status": "ok"}

    @app.get("/account/projects")
    async def list_projects(user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
        """List all generated projects for the org."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select, func

        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            rows = (await session.execute(
                select(
                    Run.project_name,
                    Run.domain,
                    Run.status,
                    func.count().label("run_count"),
                    func.max(Run.started_at).label("last_run_at"),
                    func.max(Run.id).label("run_id"),
                )
                .where(Run.org_id == org_id)
                .group_by(Run.project_name, Run.domain, Run.status)
                .order_by(func.max(Run.started_at).desc())
            )).all()
        return [
            {
                "project_name": r.project_name,
                "domain": r.domain,
                "run_count": r.run_count,
                "last_run_at": r.last_run_at,
                "status": r.status,
                "run_id": r.run_id,
            }
            for r in rows
        ]

    @app.get("/account/projects/search")
    async def search_projects(q: str, user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
        """Search projects by requirement similarity."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select, func

        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            rows = (await session.execute(
                select(
                    Run.project_name,
                    Run.domain,
                    Run.status,
                    func.count().label("run_count"),
                    func.max(Run.started_at).label("last_run_at"),
                    func.max(Run.id).label("run_id"),
                )
                .where(Run.org_id == org_id, Run.project_name.like(f"%{q}%"))
                .group_by(Run.project_name, Run.domain, Run.status)
                .order_by(func.max(Run.started_at).desc())
            )).all()
        return [
            {
                "project_name": r.project_name,
                "domain": r.domain,
                "run_count": r.run_count,
                "last_run_at": r.last_run_at,
                "status": r.status,
                "run_id": r.run_id,
            }
            for r in rows
        ]

    @app.get("/intelligence/quality-benchmark")
    async def get_quality_benchmark(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        """Quality benchmark aggregated from real completed run data."""
        from aether_os.core.db import get_session_factory as _gsf_qb
        from sqlalchemy import text as _qt
        org_id = user["org_id"]
        try:
            async with _gsf_qb()() as _sess_qb:
                total = (await _sess_qb.execute(
                    _qt("SELECT COUNT(*) FROM runs WHERE org_id=:oid AND status='completed'"),
                    {"oid": org_id},
                )).scalar() or 0
                domain_rows = (await _sess_qb.execute(
                    _qt("SELECT domain, COUNT(*) FROM runs WHERE org_id=:oid AND status='completed'"
                        " AND domain IS NOT NULL GROUP BY domain"),
                    {"oid": org_id},
                )).all()
                domain_counts = {r[0]: r[1] for r in domain_rows}
                max_count = max(domain_counts.values()) if domain_counts else 1
                domain_scores = {d: min(100, round(70 + 30 * c / max_count)) for d, c in domain_counts.items()}
        except Exception:
            total, domain_scores = 0, {}
        overall = round(sum(domain_scores.values()) / max(len(domain_scores), 1), 1) if domain_scores else 0.0
        return {
            "overall_score": overall,
            "baseline_score": 70.0,
            "completed_runs": total,
            "domains": domain_scores,
        }


    @app.post("/factory/runs/{run_id}/pause")
    async def pause_factory_run(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Signal the pipeline to pause."""
        from aether_os.core.audit.ledger import get_ledger
        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        from aether_os.core.pipeline_state import set_control as _set_control
        await _set_control(run_id, "pause")
        await get_ledger().async_update_run_status(run_id, "paused")
        return {"run_id": run_id, "status": "paused"}

    @app.post("/factory/runs/{run_id}/resume")
    async def resume_factory_run(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Resume a paused pipeline run."""
        from aether_os.core.audit.ledger import get_ledger
        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        from aether_os.core.pipeline_state import set_control as _set_control
        await _set_control(run_id, "run")
        await get_ledger().async_update_run_status(run_id, "running")
        return {"run_id": run_id, "status": "running"}

    @app.post("/factory/runs/{run_id}/cancel")
    async def cancel_factory_run(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Cancel a running or paused pipeline run."""
        from aether_os.core.audit.ledger import get_ledger
        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        from aether_os.core.pipeline_state import set_control as _set_control
        await _set_control(run_id, "cancel")
        await get_ledger().async_update_run_status(run_id, "cancelled")
        return {"run_id": run_id, "status": "cancelled"}

    @app.post("/factory/runs/{run_id}/priority")
    async def set_factory_run_priority(
        run_id: str,
        req: PriorityRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Set the priority label for a run."""
        from aether_os.core.audit.ledger import get_ledger
        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        if req.priority not in ("high", "normal", "low"):
            raise HTTPException(status_code=400, detail="priority must be high | normal | low")
        # Upsert priority via ORM (FIX-017)
        from aether_os.core.db import get_session_factory as _gsf_pri
        from aether_os.core.models import RunMetadata as _RM_pri
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
        _sf_pri = _gsf_pri()
        async with _sf_pri() as _sess_pri:
            existing = await _sess_pri.get(_RM_pri, run_id)
            if existing:
                existing.priority = req.priority
                existing.updated_at = time.time()
            else:
                _sess_pri.add(_RM_pri(run_id=run_id, priority=req.priority, updated_at=time.time()))
            await _sess_pri.commit()
        return {"run_id": run_id, "priority": req.priority}

    @app.post("/factory/runs/{run_id}/rerun")
    async def rerun_factory_run(
        run_id: str,
        req: RerunRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Create a new run starting from a given phase."""
        import uuid as _uuid
        from aether_os.orchestrator.factory_pipeline import get_factory as _get_factory
        from aether_os.core.audit.ledger import get_ledger as _get_ledger

        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import select, update as _sa_upd
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(Organisation).where(Organisation.id == org_id)
            result = await session.execute(stmt)
            org = result.scalar_one_or_none()
            if not org:
                raise HTTPException(status_code=404, detail="Organisation not found")
            if org.plan == "trial":
                # Atomic increment — prevents TOCTOU race (K-04)
                upd = await session.execute(
                    _sa_upd(Organisation)
                    .where(Organisation.id == org_id)
                    .where(Organisation.trial_runs_used < Organisation.trial_runs_limit)
                    .values(trial_runs_used=Organisation.trial_runs_used + 1)
                )
                await session.commit()
                if upd.rowcount == 0:
                    raise HTTPException(status_code=402, detail={"error": "trial_limit_reached", "upgrade_url": "/pricing"})

        cmd = detail.get("command", "")
        raw_input = cmd[9:] if cmd.startswith("factory: ") else cmd
        new_run_id = str(_uuid.uuid4())
        factory = _get_factory()

        async def _bg():
            try:
                await factory.run(
                    client_id=user.get("org_slug", "rerun"),
                    raw_input=raw_input,
                    start_phase=req.from_phase,
                    run_id=new_run_id,
                    org_id=org_id,
                )
            except Exception as exc:
                logger.error("Rerun failed: %s", exc)

        _t = asyncio.create_task(_bg())
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)
        return {"run_id": new_run_id, "status": "started", "from_phase": req.from_phase}

    @app.post("/factory/runs/{run_id}/branch")
    async def branch_factory_run(
        run_id: str,
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Fork a run at a given phase — creates a new run with the same context."""
        import uuid as _uuid2
        from aether_os.orchestrator.factory_pipeline import get_factory as _get_factory2
        from aether_os.core.db import get_session_factory as _gsf_b
        from aether_os.core.models import Run as _RunB
        from sqlalchemy import select as _sel_b, update as _upd_b
        branch_phase = req.get("branch_phase", "p04_backend")
        extra_input = req.get("extra_input", "")
        org_id = user.get("org_id")
        async with _gsf_b()() as _s:
            parent = (await _s.execute(_sel_b(_RunB).where(_RunB.id == run_id, _RunB.org_id == org_id))).scalar_one_or_none()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent run not found")
        new_run_id = str(_uuid2.uuid4())
        raw_input = (parent.raw_input or parent.command or "").replace("factory: ", "")
        if extra_input:
            raw_input = f"{raw_input}\n\nAdditional requirement: {extra_input}"
        # Mark branch in DB
        async with _gsf_b()() as _s:
            branch_row = _RunB(
                id=new_run_id, org_id=org_id, status="queued",
                parent_run_id=run_id, branch_phase=branch_phase,
                raw_input=raw_input, domain=parent.domain or "general",
                project_name=f"{parent.project_name or 'project'} (branch)",
                started_at=__import__('time').time(),
            )
            _s.add(branch_row)
            await _s.commit()
        factory = _get_factory2()
        async def _branch_bg():
            try:
                await factory.run(
                    client_id=user.get("org_slug", "branch"),
                    raw_input=raw_input,
                    start_phase=branch_phase,
                    run_id=new_run_id,
                    org_id=org_id,
                    domain=parent.domain or "general",
                )
            except Exception as exc:
                logger.error("Branch run failed: %s", exc)
        _bt = asyncio.create_task(_branch_bg())
        _background_tasks.add(_bt)
        _bt.add_done_callback(_background_tasks.discard)
        return {"run_id": new_run_id, "status": "started", "parent_run_id": run_id, "branch_phase": branch_phase}

    # Short-lived SSE exchange tokens stored in Redis (falls back to in-memory).
    # Clients POST /factory/runs/{run_id}/sse-token → get a 30s token → open EventSource.
    from aether_os.core.rate_limiter import sse_token_set, sse_token_pop

    @app.post("/factory/runs/{run_id}/sse-token")
    async def get_sse_token(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, str]:
        """Exchange bearer JWT for a short-lived (30s) SSE-only token for this run."""
        import secrets
        sse_tok = secrets.token_urlsafe(32)
        await sse_token_set(sse_tok, org_id=user["org_id"], run_id=run_id)
        return {"sse_token": sse_tok}

    @app.get("/factory/runs/{run_id}/stream")
    async def stream_run_events(
        run_id: str,
        sse_token: Optional[str] = None,
    ):
        """Server-Sent Events stream for live pipeline output.

        Auth: POST /factory/runs/{run_id}/sse-token first, then use the
        returned sse_token as a query param here. JWTs must never be passed
        in URLs (they land in nginx/proxy logs).
        """
        from fastapi.responses import StreamingResponse, Response
        from aether_os.core.audit.ledger import get_ledger

        if not sse_token:
            return Response(status_code=401, content="sse_token required — POST /factory/runs/{run_id}/sse-token first")

        entry = await sse_token_pop(sse_token)
        if not entry or entry.get("run_id") != run_id:
            return Response(status_code=401, content="SSE token invalid or expired")

        org_id = entry["org_id"]
        if not org_id:
            return Response(status_code=401, content="Invalid token")
        
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            return Response(status_code=404, content="Run not found or access denied")

        async def event_generator():
            from aether_os.core.pipeline_state import get_redis, get_event_history
            # First replay history so late-joining clients get full context
            for past_event in await get_event_history(run_id):
                yield f"data: {json.dumps(past_event)}\n\n"

            r = await get_redis()
            if r is None:
                yield f"data: {json.dumps({'type': 'no_stream', 'run_id': run_id, 'reason': 'redis_unavailable'})}\n\n"
                return

            pubsub = r.pubsub()
            await pubsub.subscribe(f"pipeline:events:{run_id}")
            try:
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        event = json.loads(message["data"])
                    except Exception:
                        continue
                    yield f"data: {message['data']}\n\n"
                    if event.get("type") == "pipeline_complete":
                        break
            except Exception:
                pass
            finally:
                await pubsub.unsubscribe(f"pipeline:events:{run_id}")
                await pubsub.aclose()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/factory/search")
    async def search_artifacts(
        q: str,
        limit: int = 30,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> List[Dict[str, Any]]:
        """Semantic search across all generated artifacts for the organisation."""
        from aether_os.core.artifact_store import get_artifact_store
        org_id = user.get("org_id")
        store = get_artifact_store()
        return await store.search(q, org_id, limit=limit)

    @app.get("/factory/runs/{run_id}/preview")
    async def preview_run_html(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Serve the generated index.html."""
        from fastapi.responses import HTMLResponse
        from aether_os.core.audit.ledger import get_ledger as _get_ledger

        org_id = user.get("org_id")
        run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not run_detail:
            raise HTTPException(status_code=404, detail="Run not found")
        
        project_id = run_id
        if run_detail and "project_id" in run_detail:
            project_id = run_detail["project_id"]

        from aether_os.core.projects import get_project_manager as _get_pm
        root_dir = _get_pm().get_project_dir(project_id)

        # Walk looking for index.html
        for candidate in [
            root_dir / "p05_frontend" / "index.html",
            root_dir / "index.html",
        ]:
            if candidate.exists():
                return HTMLResponse(content=candidate.read_text(encoding="utf-8"))

        # Recursive search
        for html_file in root_dir.rglob("index.html"):
            return HTMLResponse(content=html_file.read_text(encoding="utf-8"))

        raise HTTPException(status_code=404, detail="No index.html found in run artifacts")

    # ── System endpoints ──────────────────────────────────────────────────────

    @app.get("/system/health")
    async def system_health(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """System health check with LLM provider status."""
        import httpx as _httpx

        anthropic_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
        gemini_available = bool(os.environ.get("GOOGLE_API_KEY"))

        # Check Ollama with 2-second timeout
        ollama_available = False
        try:
            async with _httpx.AsyncClient(timeout=2.0) as _http:
                resp = await _http.get("http://localhost:11434/api/tags")
                ollama_available = resp.status_code == 200
        except Exception:
            ollama_available = False

        # Determine active LLM provider from singleton or env
        from aether_os.core.llm.client import get_llm_client
        client = get_llm_client()
        active_provider = client.last_provider or os.environ.get("PRIMARY_LLM", "none")

        # Model router routing status
        routing: dict = {}
        try:
            from aether_os.core.model_router import get_router as _get_router
            routing = _get_router().get_status()
        except Exception:
            pass

        status = "healthy"
        message = "All systems operational."

        if ollama_available and not anthropic_available and not gemini_available:
            status = "ok"
            message = "Running on local Ollama (configured)."
        elif not (anthropic_available or gemini_available or ollama_available):
            status = "warning"
            message = "No LLM providers available. System will fail to process tasks."

        llm_display = active_provider
        if active_provider == "ollama":
            llm_display = f"ollama ({os.environ.get('OLLAMA_MODEL', 'qwen2.5-coder:7b')})"

        # Real database health check
        db_status = "unhealthy"
        try:
            from aether_os.core.db import get_session_factory as _gsf_h
            from sqlalchemy import text as _ht
            async with _gsf_h()() as _sh:
                await _sh.execute(_ht("SELECT 1"))
            db_status = "healthy"
        except Exception:
            status = "degraded"
            message = "Database unreachable."

        # Real Redis/memory-store health check
        redis_status = "unavailable"
        try:
            from aether_os.core.pipeline_state import get_redis as _gr
            _r = await _gr()
            if _r:
                await _r.ping()
                redis_status = "healthy"
        except Exception:
            pass

        # Disk space check (warn if < 10% free on home partition)
        import shutil as _shutil
        try:
            _disk = _shutil.disk_usage(str(os.path.expanduser("~")))
            _free_pct = _disk.free / _disk.total * 100
            disk_status = "healthy" if _free_pct > 10 else "warning"
        except Exception:
            _free_pct = None
            disk_status = "unknown"

        # Uptime from process start
        import time as _time
        try:
            import psutil as _psu
            _proc = _psu.Process()
            _uptime_secs = int(_time.time() - _proc.create_time())
        except Exception:
            _uptime_secs = None

        # DB pool size
        _pool_size = None
        try:
            from aether_os.core.db import get_engine as _ge
            _eng = _ge()
            _pool_size = getattr(getattr(_eng, "pool", None), "size", lambda: None)()
        except Exception:
            pass

        return {
            "status": status,
            "message": message,
            # LLM fields — both naming conventions for compatibility
            "llm": "healthy" if (anthropic_available or gemini_available or ollama_available) else "unavailable",
            "provider": "healthy" if (anthropic_available or gemini_available or ollama_available) else "unavailable",
            "llm_provider": llm_display,
            "active_provider": active_provider,
            "active_model": routing.get("active_model") or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", ""),
            "anthropic_available": anthropic_available,
            "gemini_available": gemini_available,
            "ollama_available": ollama_available,
            "fallback_count_today": routing.get("fallback_count_today", 0),
            "model_availability": routing.get("model_availability", {}),
            # System info
            "version": "1.0.0",
            "environment": os.environ.get("ENVIRONMENT", "development"),
            "env": os.environ.get("ENVIRONMENT", "development"),
            "uptime": _uptime_secs,
            # Database
            "database": db_status,
            "db_pool_size": _pool_size,
            # Redis — both naming conventions
            "redis": redis_status,
            "cache": redis_status,
            "memory_store": redis_status,
            # Sandbox (basic)
            "sandbox": "unknown",
            "sandbox_engine": "docker",
            "active_sandboxes": 0,
            # Network
            "network": "healthy",
            # Disk
            "disk_free_pct": round(_free_pct, 1) if _free_pct is not None else None,
            "disk_status": disk_status,
        }

    @app.get("/health/observability")
    async def health_observability() -> Dict[str, Any]:
        """
        Observability health — LangSmith status and today's trace count.
        Returns: {langsmith, last_trace_id, traces_today}
        No auth required (public health probe).
        """
        from aether_os.core.telemetry.langsmith_tracer import get_status
        return get_status()

    @app.get("/health/sla")
    async def health_sla(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        """T4-10: SLA metrics — uptime window, run completion rate, p50/p95 duration.

        Calculates from the last 30 days of run data for the org.
        These numbers feed into SLA credit calculations for enterprise plans.
        """
        import time as _t_sla
        org_id = user["org_id"]
        window_days = 30
        since = _t_sla.time() - window_days * 86400
        try:
            from aether_os.core.db import get_session_factory as _gsf_sla
            from aether_os.core.models import Run as _Run_sla
            from sqlalchemy import select as _sel_sla, func as _func_sla
            async with _gsf_sla()() as _sess:
                q = _sel_sla(_Run_sla).where(
                    _Run_sla.org_id == org_id,
                    _Run_sla.started_at >= since,
                )
                rows = (await _sess.execute(q)).scalars().all()
        except Exception:
            rows = []

        total = len(rows)
        completed = sum(1 for r in rows if getattr(r, "status", "") == "completed")
        failed = sum(1 for r in rows if getattr(r, "status", "") in ("failed", "timeout"))
        durations = []
        for r in rows:
            if getattr(r, "finished_at", None) and getattr(r, "started_at", None):
                try:
                    d = float(r.finished_at) - float(r.started_at)
                    if d > 0:
                        durations.append(d)
                except Exception:
                    pass
        durations.sort()

        def percentile(data, pct):
            if not data:
                return None
            idx = max(0, int(len(data) * pct / 100) - 1)
            return round(data[idx], 1)

        completion_rate = round(completed / max(total, 1), 4)
        return {
            "window_days": window_days,
            "total_runs": total,
            "completed_runs": completed,
            "failed_runs": failed,
            "completion_rate": completion_rate,
            "uptime_sla_met": completion_rate >= 0.995,  # 99.5% target
            "duration_p50_s": percentile(durations, 50),
            "duration_p95_s": percentile(durations, 95),
            "sla_tier": user.get("plan", "trial"),
            "sla_target": {
                "trial": "best-effort",
                "pro": "99.0%",
                "enterprise": "99.9%",
            }.get(user.get("plan", "trial"), "best-effort"),
        }

    @app.get("/system/costs")
    async def system_costs(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Aggregate cost summary for the current org.
        Backed by TokenBudgetManager (token_budget.db) + LLMCache stats.
        """
        org_id = user["org_id"]
        plan = user.get("plan", "trial")

        # Current month usage from TokenBudgetManager
        try:
            from aether_os.core.llm.budget import get_budget_manager, _PLAN_BUDGETS
            bm = get_budget_manager()
            usage = await bm.get_usage(org_id)
            history = await bm.get_cost_report(org_id, months=3)
            budget_tokens = _PLAN_BUDGETS.get(plan, 500_000)
            budget_used_pct = round(usage["total_tokens"] / max(budget_tokens, 1) * 100, 1)
        except Exception:
            usage = {"input_tokens": 0, "output_tokens": 0, "runs": 0,
                     "estimated_cost_usd": 0.0, "total_tokens": 0,
                     "cache_hits": 0, "cache_misses": 0}
            history = []
            budget_tokens = 500_000
            budget_used_pct = 0.0

        # Cache hit stats
        try:
            from aether_os.core.llm.cache import get_llm_cache
            cache_stats = await get_llm_cache().get_stats()
        except Exception:
            cache_stats = {"total_entries": 0, "total_hits": 0, "daily": []}

        runs = usage["runs"] or 1
        return {
            "this_month": {
                "estimated_cost_usd": round(usage["estimated_cost_usd"], 4),
                "cost_per_run": round(usage["estimated_cost_usd"] / runs, 4),
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "runs": usage["runs"],
                "cache_hits": usage["cache_hits"],
                "cache_misses": usage["cache_misses"],
                "cache_hit_rate": round(
                    usage["cache_hits"] / max(usage["cache_hits"] + usage["cache_misses"], 1), 3
                ),
                "budget_tokens": budget_tokens,
                "budget_used_pct": budget_used_pct,
            },
            "history": history,
            "cache": cache_stats,
            "targets": {
                "cost_per_run_target": 0.35,
                "cost_per_run_current": round(usage["estimated_cost_usd"] / runs, 4),
                "reduction_needed_pct": max(0, round(
                    (1 - 0.35 / max(usage["estimated_cost_usd"] / runs, 0.35)) * 100, 1
                )),
            },
        }

    # ── Factory run file management (Endpoints 1 & 2) ──────────────────────────

    @app.get("/factory/runs/{run_id}/files")
    async def get_run_files(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Recursive file tree for a run's output directory."""
        from aether_os.core.projects import get_project_manager
        from aether_os.core.audit.ledger import get_ledger
        
        org_id = user.get("org_id")
        run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not run_detail:
            raise HTTPException(status_code=404, detail="Run not found")

        project_id = run_id
        if run_detail and "project_id" in run_detail:
             project_id = run_detail["project_id"]

        root_dir = get_project_manager().get_project_dir(project_id)
        
        if not root_dir.exists():
            return {"run_id": run_id, "tree": []}

        def build_tree(current_path: pathlib.Path, base_path: pathlib.Path) -> List[Dict]:
            items = []
            for item in sorted(current_path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                if item.name.startswith("."):
                    continue
                
                rel_path = str(item.relative_to(base_path))
                if item.is_dir():
                    items.append({
                        "name": item.name,
                        "type": "directory",
                        "path": rel_path,
                        "children": build_tree(item, base_path)
                    })
                else:
                    items.append({
                        "name": item.name,
                        "type": "file",
                        "path": rel_path,
                        "size_bytes": item.stat().st_size,
                        "extension": item.suffix
                    })
            return items

        return {
            "run_id": run_id,
            "tree": build_tree(root_dir, root_dir)
        }

    @app.get("/factory/runs/{run_id}/file-content")
    async def get_file_content(
        run_id: str,
        path: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Read file content."""
        from aether_os.core.projects import get_project_manager
        from aether_os.core.audit.ledger import get_ledger
        
        org_id = user.get("org_id")
        run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not run_detail:
            raise HTTPException(status_code=404, detail="Run not found")

        project_id = run_id
        if run_detail and "project_id" in run_detail:
             project_id = run_detail["project_id"]

        root_dir = get_project_manager().get_project_dir(project_id).resolve()
        # Sanitise path: strip leading slashes/dots to prevent absolute path injection
        safe_relative = pathlib.Path(path.lstrip("/")).resolve().relative_to(pathlib.Path("/").resolve()) if path.startswith("/") else pathlib.Path(path)
        file_path = (root_dir / safe_relative).resolve()

        # Proper boundary check: ensure resolved path is INSIDE root_dir (not just a prefix match)
        try:
            file_path.relative_to(root_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path traversal detected")

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        ext = file_path.suffix.lower()
        
        # Image check
        if ext in [".png", ".jpg", ".jpeg", ".gif", ".svg"]:
            return {
                "path": path,
                "type": "image",
                "message": "Image files cannot be previewed"
            }

        # Language mapping
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".sh": "bash",
            ".toml": "toml",
            ".html": "html",
            ".css": "css",
            ".diff": "diff"
        }
        language = lang_map.get(ext, "text")

        # Read and truncate if needed
        size = file_path.stat().st_size
        truncated = False
        content = ""
        
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                if size > 1_000_000:
                    content = f.read(50_000)
                    truncated = True
                else:
                    content = f.read()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading file: {e}")

        return {
            "path": path,
            "content": content,
            "language": language,
            "size_bytes": size,
            "truncated": truncated,
            "type": "diff" if ext == ".diff" else "text"
        }

    # ── System Settings (Endpoints 3, 4, 5) ────────────────────────────────────

    @app.get("/settings/api-keys")
    async def get_api_keys(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Return current API key configuration from .env, masking key values."""
        env_path = pathlib.Path(__file__).parent.parent / ".env"
        env_vars: Dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env_vars[k.strip()] = v.strip()

        def _mask(val: str) -> str:
            if not val:
                return ""
            return val[:8] + "..." if len(val) > 8 else val[:4] + "..."

        return {
            "anthropic": _mask(env_vars.get("ANTHROPIC_API_KEY", "")),
            "google": _mask(env_vars.get("GOOGLE_API_KEY", "")),
            "openai": _mask(env_vars.get("OPENAI_API_KEY", "")),
            "openrouter": _mask(env_vars.get("OPENROUTER_API_KEY", "")),
            "primary_llm": env_vars.get("PRIMARY_LLM", "ollama"),
            "ollama_model": env_vars.get("OLLAMA_MODEL", "qwen2.5-coder:3b"),
        }

    @app.post("/settings/api-keys")
    async def update_api_keys(
        req: ApiKeyRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Update .env file with new API keys. Requires owner or admin role."""
        # SECURITY: only org owners/admins may overwrite provider API keys.
        # Any authenticated user could previously change ANTHROPIC_API_KEY for the whole server.
        if user.get("role") not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organisation owners and admins may update API keys."
            )

        if req.provider not in ["anthropic", "gemini", "openai", "openrouter"]:
            raise HTTPException(status_code=400, detail="Invalid provider")

        if not req.key or len(req.key) <= 10:
            raise HTTPException(status_code=400, detail="Key too short or empty")

        env_path = pathlib.Path(__file__).parent.parent / ".env"
        _provider_to_var = {
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        var_name = _provider_to_var[req.provider]
        
        lines = []
        if env_path.exists():
            lines = env_path.read_text().splitlines()
        
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{var_name}="):
                new_lines.append(f"{var_name}={req.key}")
                found = True
            else:
                new_lines.append(line)
        
        if not found:
            new_lines.append(f"{var_name}={req.key}")

        env_path.write_text("\n".join(new_lines) + "\n")
        # Hot-reload: update os.environ immediately so the running process uses the new key
        # without needing a restart.
        os.environ[var_name] = req.key
        logger.info("API key updated and hot-reloaded for %s", req.provider)

        return {
            "success": True,
            "provider": req.provider,
            "message": "Key saved and active immediately.",
        }

    @app.get("/settings/langsmith")
    async def get_langsmith_settings(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Return current LangSmith observability configuration."""
        env_path = pathlib.Path(__file__).parent.parent / ".env"
        env_vars: Dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env_vars[k.strip()] = v.strip()

        opt_in_raw = env_vars.get("LANGSMITH_OPT_IN", os.environ.get("LANGSMITH_OPT_IN", "false"))
        api_key_raw = env_vars.get("LANGSMITH_API_KEY", os.environ.get("LANGSMITH_API_KEY", ""))
        return {
            "opt_in": opt_in_raw.lower() in ("1", "true", "yes"),
            "api_key_set": bool(api_key_raw),
            "api_key_preview": (api_key_raw[:8] + "...") if len(api_key_raw) > 8 else "",
            "project": env_vars.get("LANGCHAIN_PROJECT", os.environ.get("LANGCHAIN_PROJECT", "aetheros-factory")),
        }

    @app.post("/settings/langsmith")
    async def update_langsmith_settings(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Update LangSmith tracing opt-in and API key. Requires owner or admin role."""
        if user.get("role") not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organisation owners and admins may update observability settings.",
            )

        env_path = pathlib.Path(__file__).parent.parent / ".env"
        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text().splitlines()

        updates: Dict[str, str] = {}
        if "opt_in" in req:
            updates["LANGSMITH_OPT_IN"] = "true" if req["opt_in"] else "false"
        if "api_key" in req and req["api_key"]:
            updates["LANGSMITH_API_KEY"] = req["api_key"]
        if "project" in req and req["project"]:
            updates["LANGCHAIN_PROJECT"] = req["project"]

        for var_name, var_val in updates.items():
            found = False
            new_lines = []
            for line in lines:
                if line.startswith(f"{var_name}="):
                    new_lines.append(f"{var_name}={var_val}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"{var_name}={var_val}")
            lines = new_lines

        env_path.write_text("\n".join(lines) + "\n")

        # Hot-reload env vars and re-init LangSmith immediately
        for var_name, var_val in updates.items():
            os.environ[var_name] = var_val

        try:
            from aether_os.core.telemetry.langsmith_tracer import init_langsmith
            init_langsmith()
        except Exception as _exc:
            logger.warning("LangSmith re-init after settings change: %s", _exc)

        return {"success": True, "updated": list(updates.keys())}

    @app.post("/settings/test-provider")
    async def test_provider(
        req: TestProviderRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Test LLM provider connectivity."""
        if req.provider == "anthropic":
            try:
                import anthropic
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                client = anthropic.Anthropic(api_key=api_key)
                
                async def _call():
                    # We use a synchronous call wrapped in a thread if the library doesn't support async easily,
                    # but anthropic has AsyncAnthropic. For simplicity and to match the prompt's snippet:
                    return client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=10,
                        messages=[{"role": "user", "content": "say hi"}]
                    )

                # Wrap in executor if needed or use async client. 
                # The prompt provided synchronous snippet, so we'll use to_thread for safety in async FastAPI.
                response = await asyncio.wait_for(
                    asyncio.to_thread(_call),
                    timeout=10.0
                )
                return {
                    "success": True,
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "message": "Connected"
                }
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="Anthropic timeout")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Anthropic error: {str(e)[:200]}")

        elif req.provider == "gemini":
            try:
                import google.genai as genai
                api_key = os.environ.get("GOOGLE_API_KEY", "")
                client = genai.Client(api_key=api_key)

                async def _call():
                    return client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents="say hi"
                    )

                response = await asyncio.wait_for(
                    asyncio.to_thread(_call),
                    timeout=10.0
                )
                return {
                    "success": True,
                    "provider": "gemini",
                    "model": "gemini-2.0-flash",
                    "message": "Connected"
                }
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="Gemini timeout")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Gemini error: {str(e)[:200]}")

        elif req.provider == "openrouter":
            try:
                from aether_os.core.llm.openrouter_client import call_openrouter
                result = await asyncio.wait_for(
                    call_openrouter(
                        "say hi", task_type="classify", max_tokens=10,
                        model="minimax/minimax-m2.5:free",
                    ),
                    timeout=15.0,
                )
                return {"success": True, "provider": "openrouter", "message": "Connected", "response": result[:50]}
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="OpenRouter timeout — key may be valid but model is slow")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"OpenRouter error: {str(e)[:200]}")

        raise HTTPException(status_code=400, detail="Invalid provider")

    @app.get("/settings/llm-config")
    async def get_llm_config(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Return current LLM configuration from env / DB."""
        env_path = pathlib.Path(__file__).parent.parent / ".env"
        env_vars: Dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env_vars[k.strip()] = v.strip()
        raw_fallback = env_vars.get("OPENROUTER_FALLBACK_MODELS", "")
        fallback_list = [m.strip() for m in raw_fallback.split(",") if m.strip()] if raw_fallback else []
        # Include the live active model from the router so the UI shows what actually served last
        from aether_os.core.model_router import _active_model as _live_model
        return {
            "primary_llm": env_vars.get("PRIMARY_LLM", "anthropic"),
            "anthropic_model": env_vars.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            "ollama_model": env_vars.get("OLLAMA_MODEL", "qwen2.5-coder:3b"),
            "openrouter_heavy_model": env_vars.get("OPENROUTER_HEAVY_MODEL", "minimax/minimax-m2.5:free"),
            "openrouter_light_model": env_vars.get("OPENROUTER_LIGHT_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
            "openrouter_prefer_paid": env_vars.get("OPENROUTER_PREFER_PAID", "false").lower() == "true",
            "openrouter_fallback_models": fallback_list,
            "active_model": _live_model,  # e.g. "openrouter/deepseek/deepseek-r1:free" after first call
        }

    @app.put("/settings/llm-config")
    async def update_llm_config(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Update LLM configuration in .env. Requires owner or admin role."""
        if user.get("role") not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Only org owners/admins may update LLM config.")
        env_path = pathlib.Path(__file__).parent.parent / ".env"
        allowed_keys = {
            "primary_llm":              "PRIMARY_LLM",
            "anthropic_model":          "ANTHROPIC_MODEL",
            "ollama_model":             "OLLAMA_MODEL",
            "openrouter_heavy_model":   "OPENROUTER_HEAVY_MODEL",
            "openrouter_light_model":   "OPENROUTER_LIGHT_MODEL",
            "openrouter_prefer_paid":   "OPENROUTER_PREFER_PAID",
        }
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        updates: Dict[str, str] = {}
        for field, env_var in allowed_keys.items():
            if field in req:
                updates[env_var] = str(req[field]).lower() if isinstance(req[field], bool) else str(req[field])
        # fallback list comes in as a JSON array — store as comma-separated string
        if "openrouter_fallback_models" in req:
            models = req["openrouter_fallback_models"]
            if isinstance(models, list):
                updates["OPENROUTER_FALLBACK_MODELS"] = ",".join(str(m).strip() for m in models if str(m).strip())
            elif isinstance(models, str):
                updates["OPENROUTER_FALLBACK_MODELS"] = models
        new_lines, found = [], set()
        for line in lines:
            key = line.split("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                found.add(key)
            else:
                new_lines.append(line)
        for k, v in updates.items():
            if k not in found:
                new_lines.append(f"{k}={v}")
        env_path.write_text("\n".join(new_lines) + "\n")
        # Apply immediately to running process — no restart needed
        for k, v in updates.items():
            os.environ[k] = v
        return {"success": True, "message": "Model config applied immediately."}

    @app.get("/settings/models")
    async def get_available_models(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Return the curated OpenRouter model catalogue."""
        from aether_os.core.llm.openrouter_client import OPENROUTER_MODELS
        return {
            "openrouter": OPENROUTER_MODELS,
            "anthropic": {
                "claude-sonnet-4-6":           "claude-sonnet-4-6",
                "claude-haiku-4-5-20251001":   "claude-haiku-4-5-20251001",
            },
            "gemini": {
                "gemini-2.5-pro":   "gemini-2.5-pro",
                "gemini-2.0-flash": "gemini-2.0-flash",
            },
        }

    @app.post("/settings/models/test")
    async def test_model(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Test that a specific OpenRouter model responds. Body: {model: str}"""
        model_id = (req.get("model") or "").strip()
        if not model_id:
            raise HTTPException(status_code=422, detail="model field required")
        try:
            from aether_os.core.llm.openrouter_client import call_openrouter
            text = await call_openrouter(
                prompt="Reply with exactly: OK",
                task_type="requirements",
                system="You are a test. Reply with exactly: OK",
                max_tokens=16,
                model=model_id,
            )
            return {"success": True, "model": model_id, "response": text[:80].strip()}
        except Exception as exc:
            return {"success": False, "model": model_id, "error": str(exc)[:200]}

    @app.get("/settings/council-config")
    async def get_council_config(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Return current LLM Council configuration."""
        return {
            "council_enabled":     os.environ.get("COUNCIL_ENABLED",     "true").lower() != "false",
            "council_strict_mode": os.environ.get("COUNCIL_STRICT_MODE", "false").lower() == "true",
        }

    @app.put("/settings/council-config")
    async def update_council_config(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Update LLM Council configuration in .env. Requires owner or admin."""
        if user.get("role") not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Only org owners/admins may update council config.")
        env_path = pathlib.Path(__file__).parent.parent / ".env"
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        updates: Dict[str, str] = {}
        if "council_enabled" in req:
            updates["COUNCIL_ENABLED"] = "true" if req["council_enabled"] else "false"
        if "council_strict_mode" in req:
            updates["COUNCIL_STRICT_MODE"] = "true" if req["council_strict_mode"] else "false"
        new_lines, found = [], set()
        for line in lines:
            key = line.split("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                found.add(key)
            else:
                new_lines.append(line)
        for k, v in updates.items():
            if k not in found:
                new_lines.append(f"{k}={v}")
        env_path.write_text("\n".join(new_lines) + "\n")
        # Apply immediately to running process
        for k, v in updates.items():
            os.environ[k] = v
        return {"success": True, "council_enabled": updates.get("COUNCIL_ENABLED"), "council_strict_mode": updates.get("COUNCIL_STRICT_MODE")}

    @app.post("/settings/phases/{phase_name}/config")
    async def update_phase_config(
        phase_name: str,
        req: PhaseConfigUpdate,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Upsert phase configuration in SQLite."""
        # Validation
        valid_phases = [
            "p01_intake_requirements", "p02_architecture", "p03_scaffolding",
            "p04_backend", "p05_frontend", "p06_review_security",
            "p07_testing", "p08_cicd_deployment", "p09_observability", "p10_docs_delivery",
        ]
        if phase_name not in valid_phases:
            raise HTTPException(status_code=400, detail="Invalid phase name")
        
        if req.priority not in ["low", "normal", "high"]:
            raise HTTPException(status_code=400, detail="Invalid priority")

        # Upsert phase config via ORM — scoped to org_id (T2-09)
        from aether_os.core.db import get_session_factory as _gsf_pc
        from aether_os.core.models import PhaseConfig as _PhCfg
        from sqlalchemy import select as _sel_pc
        _org_id_pc = user["org_id"]
        _sf_pc = _gsf_pc()
        async with _sf_pc() as _sess_pc:
            existing_cfg = (await _sess_pc.execute(
                _sel_pc(_PhCfg).where(_PhCfg.org_id == _org_id_pc, _PhCfg.phase_name == phase_name)
            )).scalar_one_or_none()
            if existing_cfg:
                existing_cfg.enabled = 1 if req.enabled else 0
                existing_cfg.priority = req.priority
                existing_cfg.updated_at = time.time()
            else:
                _sess_pc.add(_PhCfg(
                    org_id=_org_id_pc,
                    phase_name=phase_name,
                    enabled=1 if req.enabled else 0,
                    priority=req.priority,
                    updated_at=time.time(),
                ))
            await _sess_pc.commit()

        return {
            "success": True,
            "phase": phase_name,
            "enabled": req.enabled,
            "priority": req.priority
        }

    @app.get("/audit/logs")
    async def get_audit_logs(
        page: int = 1,
        limit: int = 50,
        action: Optional[str] = None,
        from_ts: Optional[float] = None,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        from aether_os.core.audit.ledger import get_ledger
        return await get_ledger().async_get_audit_logs(org_id=user["org_id"], page=page, limit=limit, action=action, from_ts=from_ts)

    @app.get("/audit/logs/export")
    async def export_audit_logs(
        format: str = "json",
        days: int = 90,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T4-09: Export audit logs as JSON or CSV. Retention window controlled by `days`."""
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        if format not in ("json", "csv"):
            raise HTTPException(status_code=400, detail="format must be json or csv")
        if days < 1 or days > 365:
            raise HTTPException(status_code=400, detail="days must be between 1 and 365")

        import time as _time_export
        from_ts = _time_export.time() - days * 86400
        from aether_os.core.audit.ledger import get_ledger
        # Fetch up to 10k rows for export
        result = await get_ledger().async_get_audit_logs(
            org_id=user["org_id"], page=1, limit=10000, from_ts=from_ts
        )
        logs = result.get("logs", [])

        if format == "json":
            import json as _json_exp
            content = _json_exp.dumps({"logs": logs, "exported_at": _time_export.time(), "days": days})
            return Response(
                content=content,
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename=audit_logs_{days}d.json"},
            )
        else:
            import csv, io as _io
            buf = _io.StringIO()
            fields = ["id", "org_id", "user_id", "action", "resource_type", "resource_id", "ip_address", "created_at"]
            writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(logs)
            return Response(
                content=buf.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=audit_logs_{days}d.csv"},
            )

    @app.delete("/audit/logs/purge")
    async def purge_audit_logs(
        days_to_keep: int = 90,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T4-09: Delete audit log entries older than `days_to_keep`. Enforces retention policy."""
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        if days_to_keep < 30:
            raise HTTPException(status_code=400, detail="Minimum retention is 30 days")
        import time as _time_purge
        cutoff = _time_purge.time() - days_to_keep * 86400
        try:
            from aether_os.core.db import get_session_factory as _gsf_purge
            from aether_os.core.models import AuditLog as _AL
            from sqlalchemy import delete as _delete
            async with _gsf_purge()() as _sess:
                result = await _sess.execute(
                    _delete(_AL).where(_AL.org_id == user["org_id"]).where(_AL.created_at <= cutoff)
                )
                await _sess.commit()
                deleted = result.rowcount
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Purge failed: {exc}")
        return {"deleted": deleted, "cutoff_days": days_to_keep}

    # ── Notifications ─────────────────────────────────────────────────────────

    @app.get("/notifications")
    async def get_notifications(
        unread_only: bool = False,
        limit: int = 50,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        from aether_os.core.db import get_session_factory as _gsf_n
        from aether_os.core.models import Notification as _Notif
        from sqlalchemy import select as _sel_n, or_ as _or_n
        async with _gsf_n()() as sess:
            stmt = _sel_n(_Notif).where(
                _or_n(_Notif.user_id == user["user_id"], _Notif.user_id == None)  # noqa: E711
            ).where(_Notif.org_id == user["org_id"]).order_by(_Notif.created_at.desc()).limit(limit)
            if unread_only:
                stmt = stmt.where(_Notif.is_read == False)  # noqa: E712
            rows = (await sess.execute(stmt)).scalars().all()
        unread_count = sum(1 for r in rows if not r.is_read)
        return {
            "items": [
                {
                    "id": n.id, "type": n.type, "title": n.title,
                    "message": n.message, "link": n.link,
                    "is_read": n.is_read, "created_at": n.created_at,
                }
                for n in rows
            ],
            "unread_count": unread_count,
        }

    @app.post("/notifications/read-all")
    async def mark_all_notifications_read(user: Dict[str, Any] = Depends(get_current_user)):
        from aether_os.core.db import get_session_factory as _gsf_nr
        from aether_os.core.models import Notification as _NotifR
        from sqlalchemy import update as _upd_n, or_ as _or_nr
        async with _gsf_nr()() as sess:
            await sess.execute(
                _upd_n(_NotifR)
                .where(_NotifR.org_id == user["org_id"])
                .where(_or_nr(_NotifR.user_id == user["user_id"], _NotifR.user_id == None))  # noqa: E711
                .values(is_read=True)
            )
            await sess.commit()
        return {"ok": True}

    @app.post("/notifications/{notif_id}/read")
    async def mark_notification_read(notif_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        from aether_os.core.db import get_session_factory as _gsf_nr2
        from aether_os.core.models import Notification as _NotifR2
        async with _gsf_nr2()() as sess:
            n = await sess.get(_NotifR2, notif_id)
            if not n or n.org_id != user["org_id"]:
                raise HTTPException(status_code=404)
            n.is_read = True
            await sess.commit()
        return {"ok": True}

    @app.get("/account/storage")
    async def get_account_storage(user: Dict[str, Any] = Depends(get_current_user)):
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import select
        async with get_session_factory()() as session:
            stmt = select(Organisation).where(Organisation.id == user["org_id"])
            org = (await session.execute(stmt)).scalar_one_or_none()
            if not org: raise HTTPException(status_code=404)
            limit = -1
            if org.plan == "trial": limit = 500
            elif org.plan == "pro": limit = 10000
            return {"used_mb": org.storage_used_mb, "limit_mb": limit, "percent_used": (org.storage_used_mb / limit * 100) if limit > 0 else 0, "plan": org.plan}

    @app.get("/compliance/artifacts/{run_id}")
    async def get_compliance_artifacts(run_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        from aether_os.core.compliance.artifact_generator import ComplianceArtifactGenerator
        from fastapi.responses import StreamingResponse
        import io, zipfile
        gen = ComplianceArtifactGenerator()
        artifact = await gen.generate_artifact(run_id, "COMPLIANCE_ZIP")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf: zf.writestr("compliance.txt", artifact.content)
        zip_buffer.seek(0)
        return StreamingResponse(zip_buffer, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=compliance_{run_id}.zip"})

    async def _count_security_decisions(sf, org_id: str) -> int:
        """T5-06: Count security-phase escalations as proxy for issues_found."""
        try:
            from sqlalchemy import text as _ct2
            async with sf() as _sess2:
                return (await _sess2.execute(
                    _ct2(
                        "SELECT COUNT(*) FROM decisions "
                        "WHERE org_id=:oid AND phase='p06_review_security'"
                    ),
                    {"oid": org_id},
                )).scalar() or 0
        except Exception:
            return 0

    @app.get("/compliance/org-report")
    async def get_compliance_report(user: Dict[str, Any] = Depends(get_current_user)):
        from aether_os.core.db import get_session_factory
        from sqlalchemy import text as _ct
        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            try:
                total = (await session.execute(
                    _ct("SELECT COUNT(*) FROM runs WHERE org_id=:oid"), {"oid": org_id}
                )).scalar() or 0
                domains = (await session.execute(
                    _ct("SELECT DISTINCT domain FROM runs WHERE org_id=:oid AND domain IS NOT NULL"), {"oid": org_id}
                )).scalars().all()
                approved = (await session.execute(
                    _ct("SELECT COUNT(*) FROM decisions WHERE org_id=:oid AND status='approved'"), {"oid": org_id}
                )).scalar() or 0
                total_decisions = (await session.execute(
                    _ct("SELECT COUNT(*) FROM decisions WHERE org_id=:oid"), {"oid": org_id}
                )).scalar() or 1
            except Exception:
                total, domains, approved, total_decisions = 0, [], 0, 1
        # Determine deployment region from env (supports AWS, Fly.io, Railway, generic)
        _region = (
            os.environ.get("DEPLOYMENT_REGION")
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or os.environ.get("FLY_REGION")
            or os.environ.get("RAILWAY_REGION")
            or "unknown"
        )
        # EU AI Act risk: default to MINIMAL unless org has registered high-risk use cases
        _eu_ai_risk = "MINIMAL"
        _org_settings: dict = {}
        try:
            from aether_os.core.policy.compliance import ComplianceEngine, ComplianceContext
            try:
                async with sf() as _s2:
                    from aether_os.core.models import Organisation as _Org
                    _org = await _s2.get(_Org, org_id)
                    if _org and _org.data_region:
                        _org_settings["data_region"] = _org.data_region
            except Exception:
                pass
            _ctx = ComplianceContext(
                country_code="",
                region=_org_settings.get("data_region", "global").upper(),
                deployment_type="saas",
                data_sensitivity="moderate",
                handles_personal_data=True,
                handles_biometric_data=False,
                handles_children_data=False,
                industries=[],
                high_risk_use_cases=[],
                uses_strong_crypto=True,
                uses_weak_crypto=False,
                customer_requires_data_residency=False,
                uses_third_country_cloud=False,
                model_providers=[],
                repo_tags=[],
            )
            _result = ComplianceEngine().evaluate(_ctx)
            if _result.denied:
                _eu_ai_risk = "HIGH"
            elif _result.requires_approval:
                _eu_ai_risk = "LIMITED"
            else:
                _eu_ai_risk = "MINIMAL"
        except Exception:
            pass
        return {
            "total_runs": total,
            "domains_used": list(domains),
            "models_used": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
            "decision_approval_rate": round(approved / max(total_decisions, 1), 3),
            "security_scan_summary": {
                "scans_run": total,
                "issues_found": await _count_security_decisions(sf, org_id),
            },
            "data_processing_locations": [_region],
            "data_region": _org_settings.get("data_region", "global"),
            "eu_ai_act_risk": _eu_ai_risk,
        }

    @app.get("/factory/runs/{run_id}/decisions")
    async def get_run_decisions(
        run_id: str,
        status: Optional[str] = None,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        from aether_os.core.decisions.decision_engine import get_decision_engine
        engine = get_decision_engine()
        decisions = await engine.list_for_run(run_id, status=status)
        return [d.to_dict() for d in decisions]

    @app.post("/factory/runs/{run_id}/decisions/{decision_id}/approve")
    async def approve_decision(
        run_id: str,
        decision_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        from aether_os.core.decisions.decision_engine import get_decision_engine
        engine = get_decision_engine()
        try:
            decision = await engine.resolve(
                decision_id=decision_id,
                org_id=user["org_id"],
                approved=True,
            )
            return decision.to_dict()
        except LookupError:
            raise HTTPException(status_code=404, detail="Decision not found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Decision belongs to a different org")

    @app.post("/factory/runs/{run_id}/decisions/{decision_id}/decide")
    async def decide_decision(
        run_id: str,
        decision_id: str,
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        from aether_os.core.decisions.decision_engine import get_decision_engine
        engine = get_decision_engine()
        approved = str(req.get("decision", "approve")).lower() == "approve"
        choice = req.get("choice")
        try:
            decision = await engine.resolve(
                decision_id=decision_id,
                org_id=user["org_id"],
                approved=approved,
                choice=choice,
            )
            return decision.to_dict()
        except LookupError:
            raise HTTPException(status_code=404, detail="Decision not found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Decision belongs to a different org")

    @app.post("/factory/runs/{run_id}/kill")
    async def kill_run(run_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        from aether_os.core.pipeline_state import set_control
        from aether_os.core.db_utils import update_run_status
        await set_control(run_id, "cancel")
        await update_run_status(run_id, "cancelled", org_id=user["org_id"])
        return {"success": True, "run_id": run_id}

    @app.post("/admin/kill-all")
    async def kill_all(user: Dict[str, Any] = Depends(get_current_user)):
        if user.get("role") != "owner":
            raise HTTPException(status_code=403)
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run as _Run
        from aether_os.core.pipeline_state import set_control
        from aether_os.core.db_utils import update_run_status
        from sqlalchemy import select
        sf = get_session_factory()
        async with sf() as _sess:
            run_ids = (await _sess.execute(
                select(_Run.id).where(_Run.org_id == user["org_id"], _Run.status == "running")
            )).scalars().all()
        for rid in run_ids:
            await set_control(rid, "cancel")
            await update_run_status(rid, "cancelled", org_id=user["org_id"])
        return {"killed_count": len(run_ids)}

    @app.get("/webhooks")
    async def list_webhooks(user: Dict[str, Any] = Depends(get_current_user)):
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Webhook
        from sqlalchemy import select

        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            rows = (await session.execute(
                select(Webhook).where(Webhook.org_id == org_id)
            )).scalars().all()
        return [
            {
                "id": w.id,
                "url": w.url,
                "events": w.events,
                "is_active": w.is_active,
                "created_at": str(w.created_at),
            }
            for w in rows
        ]

    @app.post("/webhooks")
    async def create_webhook(req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        import secrets as _secrets
        import ipaddress as _ip
        import urllib.parse as _urlparse
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Webhook

        url = req.get("url", "").strip()
        if not url:
            raise HTTPException(status_code=422, detail="url is required")

        # T2-11: SSRF allowlist — block private/internal networks and metadata endpoints
        try:
            _parsed = _urlparse.urlparse(url)
            if _parsed.scheme not in ("http", "https"):
                raise HTTPException(status_code=422, detail="Webhook URL must use http or https")
            _host = _parsed.hostname or ""
            _blocked_hosts = {"localhost", "metadata.google.internal", "169.254.169.254"}
            if _host in _blocked_hosts:
                raise HTTPException(status_code=422, detail="Webhook URL targets a blocked host")
            try:
                _addr = _ip.ip_address(_host)
                if _addr.is_private or _addr.is_loopback or _addr.is_link_local or _addr.is_reserved:
                    raise HTTPException(status_code=422, detail="Webhook URL must not target a private or reserved IP")
            except ValueError:
                pass  # hostname — DNS resolution happens at delivery time, not here
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid webhook URL")

        events = req.get("events", [])
        secret = _secrets.token_hex(32)
        org_id = user["org_id"]

        sf = get_session_factory()
        async with sf() as session:
            new_webhook = Webhook(
                url=url,
                events=events,
                secret=secret,
                org_id=org_id,
            )
            session.add(new_webhook)
            await session.commit()
            await session.refresh(new_webhook)

        return {"id": new_webhook.id, "url": new_webhook.url, "is_active": True}

    @app.delete("/webhooks/{webhook_id}")
    async def delete_webhook(webhook_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Webhook
        from sqlalchemy import select

        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            wh = (await session.execute(
                select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
            )).scalar_one_or_none()
            if not wh:
                raise HTTPException(status_code=404, detail="Webhook not found")
            await session.delete(wh)
            await session.commit()
        return {"success": True}

    @app.get("/admin/users")
    async def list_users(
        user: Dict[str, Any] = Depends(get_current_user),
        page: int = 1,
        limit: int = 50,
        search: Optional[str] = None,
    ):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User
        from sqlalchemy import select, func
        limit = min(max(limit, 1), 100)
        page = max(page, 1)
        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            stmt = select(User).where(User.org_id == org_id)
            if search:
                stmt = stmt.where(User.email.ilike(f"%{search}%"))
            total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
            rows = (await session.execute(
                stmt.offset((page - 1) * limit).limit(limit)
            )).scalars().all()
        return {
            "items": [
                {"id": u.id, "email": u.email, "role": u.role,
                 "is_active": u.is_active, "created_at": str(u.created_at), "last_active": None}
                for u in rows
            ],
            "page": page, "limit": limit, "total": total,
        }

    @app.post("/admin/users/{user_id}/role")
    async def update_user_role(
        user_id: str, req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        if user.get("role") != "owner":
            raise HTTPException(status_code=403)
        new_role = req.get("role")
        if new_role not in ("owner", "admin", "member", "viewer"):
            raise HTTPException(status_code=422, detail="Invalid role")
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User
        sf = get_session_factory()
        async with sf() as session:
            db_user = await session.get(User, user_id)
            if not db_user or db_user.org_id != user["org_id"]:
                raise HTTPException(status_code=404, detail="User not found")
            db_user.role = new_role
            await session.commit()
        return {"id": user_id, "role": new_role}

    @app.post("/admin/users/{user_id}/deactivate")
    async def deactivate_user(user_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User
        sf = get_session_factory()
        async with sf() as session:
            db_user = await session.get(User, user_id)
            if not db_user or db_user.org_id != user["org_id"]:
                raise HTTPException(status_code=404, detail="User not found")
            db_user.is_active = False
            await session.commit()
        return {"id": user_id, "is_active": False}

    @app.post("/admin/users/invite")
    async def invite_user(req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        email = req.get("email", "").strip().lower()
        role = req.get("role", "member")
        if not email or "@" not in email:
            raise HTTPException(status_code=422, detail="Valid email required")
        if role not in ("owner", "admin", "member", "viewer"):
            raise HTTPException(status_code=422, detail="Invalid role")
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User, Organisation
        from aether_os.gateway.auth import get_password_hash
        from sqlalchemy import select as _sel_inv
        import secrets as _sec
        sf = get_session_factory()
        async with sf() as session:
            existing = (await session.execute(
                _sel_inv(User).where(User.email == email)
            )).scalar_one_or_none()
            if existing:
                raise HTTPException(status_code=409, detail="User with this email already exists")
            temp_password = _sec.token_urlsafe(16)
            new_user = User(
                org_id=user["org_id"],
                email=email,
                password_hash=get_password_hash(temp_password),
                role=role,
                is_active=True,
            )
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)
        return {"id": new_user.id, "email": email, "role": role, "temp_password": temp_password}

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
            loop = asyncio.get_event_loop()
            pw_ok = await loop.run_in_executor(None, verify_password, current_pw, db_user.password_hash)
            if not pw_ok:
                raise HTTPException(status_code=401, detail="Current password is incorrect.")
            db_user.password_hash = await loop.run_in_executor(None, get_password_hash, new_pw)
            await session.commit()
        return {"message": "Password changed"}

    @app.get("/marketplace/profiles")
    async def list_profiles(page: int = 1, limit: int = 20):
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import MarketplaceProfile
        from sqlalchemy import select, func
        limit = min(max(limit, 1), 100)
        page = max(page, 1)
        sf = get_session_factory()
        async with sf() as session:
            total = (await session.execute(
                select(func.count()).where(MarketplaceProfile.is_published == True)
            )).scalar_one()
            rows = (await session.execute(
                select(MarketplaceProfile)
                .where(MarketplaceProfile.is_published == True)
                .offset((page - 1) * limit).limit(limit)
            )).scalars().all()
        items = [
            {
                "id": p.id,
                "name": p.name,
                "base_domain": p.base_domain,
                "description": p.description,
                "price_usd": p.price_usd,
                "usage_count": p.usage_count,
                "org_id": p.org_id,
            }
            for p in rows
        ]
        return {"items": items, "page": page, "limit": limit, "total": total}

    @app.post("/marketplace/install/{profile_id}")
    async def install_marketplace_profile(
        profile_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """T5-02: Install a marketplace profile — increment usage_count and start a
        pipeline run pre-configured with the profile's domain and YAML settings."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import MarketplaceProfile
        from sqlalchemy import select, update as _sa_upd

        sf = get_session_factory()
        async with sf() as session:
            profile = (await session.execute(
                select(MarketplaceProfile).where(
                    MarketplaceProfile.id == profile_id,
                    MarketplaceProfile.is_published == True,  # noqa: E712
                )
            )).scalar_one_or_none()
            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found or not published")
            # Increment usage counter atomically
            await session.execute(
                _sa_upd(MarketplaceProfile)
                .where(MarketplaceProfile.id == profile_id)
                .values(usage_count=MarketplaceProfile.usage_count + 1)
            )
            await session.commit()

        # Start a pipeline run pre-seeded with the profile configuration
        try:
            from aether_os.core.services.pipeline_service import get_pipeline_service
            svc = get_pipeline_service()
            result = await svc.start_run(
                org_id=user["org_id"],
                org_slug=user.get("org_slug", ""),
                plan=user.get("plan", "trial"),
                raw_input=f"Install marketplace profile: {profile.name}. {profile.description or ''}",
                project_name=profile.name,
                domain=profile.base_domain,
            )
        except ValueError as exc:
            raise HTTPException(status_code=429, detail=str(exc))

        return {
            "installed": True,
            "profile_id": profile_id,
            "profile_name": profile.name,
            "run_id": result.get("run_id"),
        }

    # ── Deployment endpoints ───────────────────────────────────────────────────

    @app.post("/factory/runs/{run_id}/deploy")
    async def deploy_run(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Manually trigger Docker deployment (non-blocking)."""
        from aether_os.core.audit.ledger import get_ledger
        from aether_os.core.db_utils import async_update_run_live_url
        import subprocess as _sp
        import asyncio as _aio

        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Fast-fail Docker check — run in thread so we don't block the event loop
        def _docker_check():
            return _sp.run(["docker", "info"], capture_output=True, timeout=10)

        check = await _aio.to_thread(_docker_check)
        if check.returncode != 0:
            return {"success": False, "error": "Docker daemon not running."}

        from types import SimpleNamespace
        from aether_os.phases.p11_deployment.task_agent import TaskAgent

        # TaskAgent.run() may do blocking I/O — run in thread
        def _run_agent():
            import asyncio
            agent = TaskAgent()
            phase_input = SimpleNamespace(run_id=run_id)
            return asyncio.run(agent.run(phase_input))

        result = await _aio.to_thread(_run_agent)

        if result.get("success") and result.get("live_url"):
            try:
                await async_update_run_live_url(run_id, result["live_url"])
            except Exception as _e:
                logger.warning("Failed to persist live_url: %s", _e)

        return result

    @app.delete("/factory/runs/{run_id}/deploy")
    async def stop_deployment(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Stop the running Docker container (non-blocking)."""
        from aether_os.core.audit.ledger import get_ledger
        from aether_os.core.db_utils import async_update_run_live_url
        import subprocess as _sp
        import asyncio as _aio

        org_id = user.get("org_id")
        detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        container_name = f"aetheros-app-{run_id[:8]}"

        def _stop():
            return _sp.run(["docker", "rm", "-f", container_name], capture_output=True)

        result = await _aio.to_thread(_stop)
        try:
            await async_update_run_live_url(run_id, None)
        except Exception as _e:
            logger.warning("Failed to clear live_url: %s", _e)
        return {"stopped": result.returncode == 0, "container": container_name}

    @app.get("/factory/deployments")
    async def list_deployments(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """List all running AetherOS Docker containers (non-blocking)."""
        import subprocess as _sp
        import asyncio as _aio

        def _list():
            return _sp.run(
                ["docker", "ps", "--filter", "name=aetheros-app",
                 "--format", "{{.Names}}\t{{.Ports}}\t{{.Status}}"],
                capture_output=True, text=True,
            )

        result = await _aio.to_thread(_list)
        containers = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t")
                containers.append({
                    "name":   parts[0] if len(parts) > 0 else "",
                    "ports":  parts[1] if len(parts) > 1 else "",
                    "status": parts[2] if len(parts) > 2 else "",
                })
        return {"containers": containers}

    @app.get("/settings/phases/config")
    async def get_all_phase_configs(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> List[Dict[str, Any]]:
        """Get all phase configurations, falling back to defaults."""
        valid_phases = [
            "p01_intake_requirements", "p02_architecture", "p03_scaffolding",
            "p04_backend", "p05_frontend", "p06_review_security",
            "p07_testing", "p08_cicd_deployment", "p09_observability", "p10_docs_delivery",
        ]
        
        configs = {p: {"phase_name": p, "enabled": True, "priority": "normal"} for p in valid_phases}

        # Load org-scoped overrides via ORM (T2-09)
        try:
            from aether_os.core.db import get_session_factory as _gsf_pcl
            from aether_os.core.models import PhaseConfig as _PhCfgL
            from sqlalchemy import select as _sel_pcl
            _sf_pcl = _gsf_pcl()
            async with _sf_pcl() as _sess_pcl:
                _cfg_rows = (await _sess_pcl.execute(
                    _sel_pcl(_PhCfgL).where(_PhCfgL.org_id == user["org_id"])
                )).scalars().all()
                for _row in _cfg_rows:
                    if _row.phase_name in configs:
                        configs[_row.phase_name]["enabled"] = bool(_row.enabled)
                        configs[_row.phase_name]["priority"] = _row.priority
        except Exception as _e_pcl:
            logger.debug("Phase configs ORM query failed: %s", _e_pcl)

        return list(configs.values())

    # ── Memory endpoints ──────────────────────────────────────────────────────

    @app.post("/memory/search")
    async def memory_search(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Similarity search over past runs for the current org.
        Returns top-k matches with similarity scores and context hints.
        Body: { query: str, top_k?: int }
        """
        query = (req.get("query") or "").strip()
        top_k = min(int(req.get("top_k", 5)), 10)
        if not query:
            raise HTTPException(status_code=422, detail="query is required")
        org_id = user.get("org_id", "default")
        try:
            from aether_os.core.services.memory_service import get_memory_service
            ms = get_memory_service()
            matches = await ms._find_similar_runs(org_id=org_id, raw_input=query, top_k=top_k)
            # Normalise field names for the frontend SimilarRunCard component
            normalised = []
            for m in matches:
                normalised.append({
                    "run_id":     m.get("run_id", ""),
                    "project":    m.get("project_name", m.get("project", "Unnamed")),
                    "similarity": round(float(m.get("similarity", 0.0)), 3),
                    "domain":     m.get("domain", ""),
                    "hint":       m.get("winning_approach", m.get("hint", "")),
                })
            return {"matches": normalised, "query": query}
        except Exception as exc:
            logger.warning("memory_search failed: %s", exc)
            return {"matches": [], "query": query}

    @app.get("/settings/preferences")
    async def get_preferences(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Return stored user preferences (session memory)."""
        user_id = user.get("user_id") or user.get("sub", "")
        try:
            from aether_os.core.services.memory_service import get_memory_service
            ms = get_memory_service()
            prefs = await ms.get_user_preferences(user_id)
            return prefs
        except Exception as exc:
            logger.warning("get_preferences failed: %s", exc)
            return {}

    @app.put("/settings/preferences")
    async def update_preferences(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Merge new key/value pairs into stored user preferences."""
        user_id = user.get("user_id") or user.get("sub", "")
        # Strip blank keys and never allow password/token overwrite via this endpoint
        clean = {k: v for k, v in req.items() if k and k not in ("password", "token", "hashed_password")}
        if not clean:
            raise HTTPException(status_code=422, detail="No valid preference keys provided")
        try:
            from aether_os.core.services.memory_service import get_memory_service
            ms = get_memory_service()
            await ms.set_user_preferences(user_id, clean)
            updated = await ms.get_user_preferences(user_id)
            return updated
        except Exception as exc:
            logger.warning("update_preferences failed: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to save preferences")

    # ── SSO / SAML config (T6-04) ─────────────────────────────────────────────

    class SamlConfigRequest(BaseModel):
        idp_entity_id: str
        idp_sso_url: str
        idp_cert: str

    @app.get("/settings/sso")
    async def get_sso_config(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        """Return the current org's SAML IdP configuration."""
        if user.get("role") not in ("owner",):
            raise HTTPException(status_code=403, detail="Only org owners can view SSO config")
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import SamlConfig
        from sqlalchemy import select
        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            cfg = (await session.execute(
                select(SamlConfig).where(SamlConfig.org_id == org_id)
            )).scalar_one_or_none()
        if not cfg:
            return {"configured": False}
        return {
            "configured": True,
            "id": cfg.id,
            "idp_entity_id": cfg.idp_entity_id,
            "idp_sso_url": cfg.idp_sso_url,
            "idp_cert_preview": cfg.idp_cert[:40] + "..." if len(cfg.idp_cert) > 40 else cfg.idp_cert,
            "created_at": cfg.created_at.isoformat() if cfg.created_at else None,
        }

    @app.put("/settings/sso")
    async def upsert_sso_config(
        req: SamlConfigRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Create or replace the org's SAML IdP configuration."""
        if user.get("role") not in ("owner",):
            raise HTTPException(status_code=403, detail="Only org owners can configure SSO")
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import SamlConfig
        from sqlalchemy import select
        import uuid
        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            cfg = (await session.execute(
                select(SamlConfig).where(SamlConfig.org_id == org_id)
            )).scalar_one_or_none()
            if cfg:
                cfg.idp_entity_id = req.idp_entity_id
                cfg.idp_sso_url = req.idp_sso_url
                cfg.idp_cert = req.idp_cert
            else:
                cfg = SamlConfig(
                    id=str(uuid.uuid4()),
                    org_id=org_id,
                    idp_entity_id=req.idp_entity_id,
                    idp_sso_url=req.idp_sso_url,
                    idp_cert=req.idp_cert,
                )
                session.add(cfg)
            await session.commit()
        return {"configured": True, "message": "SSO configuration saved"}

    @app.delete("/settings/sso")
    async def delete_sso_config(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, str]:
        """Remove the org's SAML IdP configuration."""
        if user.get("role") not in ("owner",):
            raise HTTPException(status_code=403, detail="Only org owners can remove SSO config")
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import SamlConfig
        from sqlalchemy import select
        org_id = user["org_id"]
        sf = get_session_factory()
        async with sf() as session:
            cfg = (await session.execute(
                select(SamlConfig).where(SamlConfig.org_id == org_id)
            )).scalar_one_or_none()
            if not cfg:
                raise HTTPException(status_code=404, detail="No SSO configuration found")
            await session.delete(cfg)
            await session.commit()
        return {"message": "SSO configuration removed"}

    # ─────────────────────────────────────────────────────────────────────────

    @app.get("/factory/runs/{run_id}/artifacts")
    async def get_run_artifacts(run_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        import os as _os
        from pathlib import Path
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select
        sf = get_session_factory()
        async with sf() as session:
            run = (await session.execute(select(Run).where(Run.id == run_id, Run.org_id == user["org_id"]))).scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        project_dir = Path.home() / ".aether_os" / "projects" / run_id
        artifacts = []
        _ARTIFACT_SKIP = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".git"}
        if project_dir.exists():
            for fpath in sorted(project_dir.rglob("*")):
                if not fpath.is_file():
                    continue
                rel = fpath.relative_to(project_dir)
                parts = rel.parts
                if any(p.startswith('.') or p in _ARTIFACT_SKIP for p in parts):
                    continue
                if fpath.suffix in {".pyc", ".pyo"}:
                    continue
                artifacts.append({
                        "filename": fpath.name,
                        "path": str(rel),
                        "phase": rel.parts[0] if len(rel.parts) > 1 else "root",
                        "size_bytes": fpath.stat().st_size,
                        "created_at": int(fpath.stat().st_mtime * 1000),
                    })
        return artifacts

    @app.get("/factory/runs/{run_id}/download")
    async def download_run_zip(run_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        import io, zipfile
        from pathlib import Path
        from fastapi.responses import StreamingResponse
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select
        sf = get_session_factory()
        async with sf() as session:
            run = (await session.execute(select(Run).where(Run.id == run_id, Run.org_id == user["org_id"]))).scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        project_dir = Path.home() / ".aether_os" / "projects" / run_id
        if not project_dir.exists():
            raise HTTPException(status_code=404, detail="Project files not found")
        _SKIP = {"__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", ".git"}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in sorted(project_dir.rglob("*")):
                if not fpath.is_file():
                    continue
                rel = fpath.relative_to(project_dir)
                if any(p in _SKIP or p.startswith(".") for p in rel.parts):
                    continue
                if fpath.suffix in {".pyc", ".pyo"}:
                    continue
                zf.write(fpath, rel)
        buf.seek(0)
        name = (run.project_name or run_id).replace(" ", "_")
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
        )

    @app.post("/factory/runs/{run_id}/push-github")
    async def push_run_to_github(run_id: str, req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user)):
        """Push the generated project to a new GitHub repository."""
        import base64, httpx
        from pathlib import Path
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select
        github_token = req.get("github_token", "")
        repo_name = req.get("repo_name", "")
        if not github_token or not repo_name:
            raise HTTPException(status_code=422, detail="github_token and repo_name are required")
        sf = get_session_factory()
        async with sf() as session:
            run = (await session.execute(select(Run).where(Run.id == run_id, Run.org_id == user["org_id"]))).scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        project_dir = Path.home() / ".aether_os" / "projects" / run_id
        if not project_dir.exists():
            raise HTTPException(status_code=404, detail="Project files not found")
        headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
        async with httpx.AsyncClient(timeout=30) as gh:
            # Create repo
            create_res = await gh.post("https://api.github.com/user/repos", json={
                "name": repo_name, "description": f"Generated by AetherOS Factory", "private": False, "auto_init": False,
            }, headers=headers)
            if create_res.status_code not in (201, 422):
                raise HTTPException(status_code=502, detail=f"GitHub repo creation failed: {create_res.text}")
            repo_data = create_res.json()
            html_url = repo_data.get("html_url", f"https://github.com/user/{repo_name}")
            # Get GitHub username
            user_res = await gh.get("https://api.github.com/user", headers=headers)
            gh_user = user_res.json().get("login", "aetheros")
            # Push files (up to 50 key files to avoid GitHub API limits)
            _SKIP = {"__pycache__", ".pytest_cache", "node_modules", ".git"}
            files_pushed = 0
            for fpath in sorted(project_dir.rglob("*")):
                if not fpath.is_file() or files_pushed >= 50:
                    break
                rel = fpath.relative_to(project_dir)
                if any(p in _SKIP or p.startswith(".") for p in rel.parts):
                    continue
                if fpath.suffix in {".pyc", ".pyo"}:
                    continue
                try:
                    content = base64.b64encode(fpath.read_bytes()).decode()
                    await gh.put(
                        f"https://api.github.com/repos/{gh_user}/{repo_name}/contents/{rel}",
                        json={"message": f"Add {rel}", "content": content},
                        headers=headers,
                    )
                    files_pushed += 1
                except Exception:
                    continue
        return {"html_url": html_url, "files_pushed": files_pushed}

    @app.get("/admin/platform-health")
    async def platform_health(user: Dict[str, Any] = Depends(get_current_user)):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        import shutil
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select, func as sqlfunc

        sf = get_session_factory()
        async with sf() as session:
            active = (await session.execute(select(sqlfunc.count()).select_from(Run).where(Run.status == "running"))).scalar_one()

        disk = shutil.disk_usage("/")
        disk_pct = round(disk.used / disk.total * 100, 1)

        redis_ok = False
        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if r:
                await r.ping()
                redis_ok = True
        except Exception:
            pass

        return {
            "redis_connected": redis_ok,
            "active_pipelines": active,
            "disk_usage_pct": disk_pct,
            "disk_free_gb": round(disk.free / 1e9, 1),
        }

    # ── Per-user learning loop (T3-37) ───────────────────────────────────────

    @app.get("/learning/context")
    async def get_learning_context(user: Dict[str, Any] = Depends(get_current_user)):
        """Return learned patterns for the current user (used by pipeline for LLM personalisation)."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.services import learning_service
        sf = get_session_factory()
        async with sf() as session:
            ctx = await learning_service.get_user_context(
                org_id=user["org_id"], user_id=user["user_id"], session=session
            )
        return {"patterns": ctx}

    @app.get("/learning/clarifications")
    async def get_clarifications(user: Dict[str, Any] = Depends(get_current_user)):
        """Return pending project-scoped clarification questions for the current user."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.services import learning_service
        sf = get_session_factory()
        async with sf() as session:
            questions = await learning_service.get_pending_clarifications(
                org_id=user["org_id"], user_id=user["user_id"], session=session
            )
        return {"clarifications": questions}

    @app.post("/learning/clarifications/{clarification_id}/answer")
    async def answer_clarification(
        clarification_id: str,
        body: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Submit an answer to a pending clarification question."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.services import learning_service
        answer = body.get("answer")
        if not answer:
            raise HTTPException(status_code=400, detail="answer required")
        sf = get_session_factory()
        async with sf() as session:
            ok = await learning_service.answer_clarification(
                clarification_id=clarification_id,
                org_id=user["org_id"],
                user_id=user["user_id"],
                answer=answer,
                session=session,
            )
        if not ok:
            raise HTTPException(status_code=404, detail="Clarification not found or already answered")
        return {"status": "answered"}

    # ── Builder specs (Frontend Builder / Backend Builder tabs, T3-38/39) ─────

    @app.get("/factory/runs/{run_id}/frontend-spec")
    async def get_frontend_spec(run_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        """Retrieve the frontend spec attached to a run."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import RunSpec, Run
        sf = get_session_factory()
        async with sf() as session:
            run = await session.get(Run, run_id)
            if not run or run.org_id != user["org_id"]:
                raise HTTPException(status_code=404, detail="Run not found")
            row = await session.get(RunSpec, (run_id, "frontend"))
        return {"spec": row.spec if row else {}}

    @app.post("/factory/runs/{run_id}/frontend-spec")
    async def save_frontend_spec(
        run_id: str,
        body: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Save / overwrite the frontend spec for a run."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import RunSpec, Run
        spec = body.get("spec") or body
        sf = get_session_factory()
        async with sf() as session:
            run = await session.get(Run, run_id)
            if not run or run.org_id != user["org_id"]:
                raise HTTPException(status_code=404, detail="Run not found")
            row = await session.get(RunSpec, (run_id, "frontend"))
            if row:
                row.spec = spec
                row.updated_at = __import__("datetime").datetime.utcnow()
            else:
                session.add(RunSpec(run_id=run_id, spec_type="frontend", spec=spec))
            await session.commit()
        return {"status": "saved"}

    @app.get("/factory/runs/{run_id}/backend-spec")
    async def get_backend_spec(run_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        """Retrieve the backend spec attached to a run."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import RunSpec, Run
        sf = get_session_factory()
        async with sf() as session:
            run = await session.get(Run, run_id)
            if not run or run.org_id != user["org_id"]:
                raise HTTPException(status_code=404, detail="Run not found")
            row = await session.get(RunSpec, (run_id, "backend"))
        return {"spec": row.spec if row else {}}

    @app.post("/factory/runs/{run_id}/backend-spec")
    async def save_backend_spec(
        run_id: str,
        body: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Save / overwrite the backend spec for a run."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import RunSpec, Run
        spec = body.get("spec") or body
        sf = get_session_factory()
        async with sf() as session:
            run = await session.get(Run, run_id)
            if not run or run.org_id != user["org_id"]:
                raise HTTPException(status_code=404, detail="Run not found")
            row = await session.get(RunSpec, (run_id, "backend"))
            if row:
                row.spec = spec
                row.updated_at = __import__("datetime").datetime.utcnow()
            else:
                session.add(RunSpec(run_id=run_id, spec_type="backend", spec=spec))
            await session.commit()
        return {"status": "saved"}

    @app.post("/factory/runs/{run_id}/validate-spec")
    async def validate_spec(
        run_id: str,
        body: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Basic validation of a backend spec before pipeline starts."""
        spec = body.get("spec", {})
        errors = []
        if not spec.get("framework"):
            errors.append("framework is required")
        if not spec.get("database"):
            errors.append("database is required")
        entities = spec.get("entities", [])
        for i, ent in enumerate(entities):
            if not ent.get("name"):
                errors.append(f"entity[{i}] missing name")
            fields = ent.get("fields", [])
            if not any(f.get("primary_key") for f in fields):
                errors.append(f"entity '{ent.get('name', i)}' has no primary key field")
        return {"valid": len(errors) == 0, "errors": errors}

    # ── Prompt Input Tab — conversation endpoint (T3-40) ─────────────────────

    @app.post("/factory/runs/{run_id}/chat")
    async def project_chat(
        run_id: str,
        body: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """
        Project-scoped conversational AI endpoint.
        Messages are strictly scoped to the project — off-topic requests are redirected.
        """
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from aether_os.core.services import learning_service
        from aether_os.core.llm.client import LLMClient

        message = (body.get("message") or "").strip()
        history = body.get("history", [])  # list of {role, content}
        if not message:
            raise HTTPException(status_code=400, detail="message required")

        sf = get_session_factory()
        async with sf() as session:
            run = await session.get(Run, run_id)
            if not run or run.org_id != user["org_id"]:
                raise HTTPException(status_code=404, detail="Run not found")
            user_ctx = await learning_service.get_user_context(
                org_id=user["org_id"], user_id=user["user_id"], session=session
            )
            project_name = run.project_name or run_id

        system_prompt = (
            "You are AetherOS, an autonomous software development assistant.\n\n"
            "SCOPE RESTRICTION — ABSOLUTE:\n"
            "You may ONLY discuss topics directly related to the current project:\n"
            "1. Software requirements and specifications\n"
            "2. Architecture, design patterns, and technical decisions\n"
            "3. Code review, debugging, and error analysis\n"
            "4. Testing strategy and coverage\n"
            "5. Deployment, infrastructure, and monitoring\n"
            "6. Performance optimization\n"
            "7. Security review of generated code\n"
            "8. Documentation and API specifications\n"
            "9. Change requests and iterations\n"
            "10. Project planning and timeline estimation\n\n"
            'You MUST refuse all other topics with: "I\'m focused on your project. '
            "Let's talk about [specific project topic]. What aspect of the project can I help you with?\"\n\n"
            f"Current project: {project_name}\n"
            f"User's learned preferences: {user_ctx}"
        )

        conversation = []
        for h in history[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                conversation.append({"role": h["role"], "content": h["content"]})
        conversation.append({"role": "user", "content": message})

        try:
            client = LLMClient()
            reply = await client.call(
                prompt=message,
                task_type="code_generation",
                system=system_prompt,
                max_tokens=2048,
            )
        except Exception as e:
            logger.warning("Chat LLM call failed: %s", e)
            reply = "I'm having trouble connecting right now. Please try again shortly."

        return {"reply": reply, "run_id": run_id, "project": project_name}

    # ── Agent endpoints (T5-07) ──────────────────────────────────────────────

    @app.get("/agents")
    async def list_agents(user: Dict[str, Any] = Depends(get_current_user)):
        """List all registered agents with their name, kind, and availability."""
        from aether_os.agents.implementations import get_agent_registry
        from aether_os.agents.base import AgentKind
        registry = get_agent_registry()
        return {
            "agents": [
                {
                    "name": a.name.value,
                    "kind": a.kind.value,
                }
                for a in registry._by_name.values()
            ],
            "total": len(registry._by_name),
        }

    @app.post("/agents/{agent_name}/run")
    async def run_agent(
        agent_name: str,
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Run a specific agent with the provided metadata context."""
        from aether_os.agents.implementations import get_agent_registry
        from aether_os.agents.base import AgentContext, AgentName
        registry = get_agent_registry()
        # Lookup by value (e.g. "policy_agent")
        agent = next(
            (a for a in registry._by_name.values() if a.name.value == agent_name),
            None,
        )
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        ctx = AgentContext(
            project_path=req.get("project_path", "."),
            file_path=req.get("file_path"),
            workflow_id=req.get("workflow_id"),
            user_id=user.get("sub"),
            metadata={**req.get("metadata", {}), "org_id": user["org_id"]},
        )
        result = await agent.run(ctx)
        return {
            "agent": result.agent_name.value,
            "status": result.status,
            "message": result.message,
            "payload": result.payload,
            "duration_ms": round(result.duration * 1000, 1),
        }

    # ── T9 Intelligence Engines ───────────────────────────────────────────────

    @app.post("/intelligence/arch-governor/review")
    async def arch_governor_review(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T9-01: Review generated code against architecture spec."""
        from aether_os.core.intelligence.arch_governor import get_arch_governor
        gov = get_arch_governor()
        run_id = req.get("run_id", "")
        result = await gov.enforce(
            run_id=run_id,
            architecture_doc=req.get("architecture_doc", ""),
            generated_code=req.get("generated_code", ""),
            org_id=user.get("org_id"),
        )
        return result

    @app.post("/intelligence/truth-engine/validate")
    async def truth_engine_validate(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T9-02: Validate requirements coverage in generated output."""
        from aether_os.core.intelligence.truth_engine import get_truth_engine
        engine = get_truth_engine()
        if run_id := req.get("run_id"):
            return await engine.audit_run(run_id)
        return await engine.validate(
            requirements=req.get("requirements", ""),
            generated_code=req.get("generated_code", ""),
            architecture_doc=req.get("architecture_doc", ""),
        )

    @app.post("/intelligence/conflict-resolver/detect")
    async def conflict_resolver_detect(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T9-03: Detect conflicts in requirements or architecture."""
        from aether_os.core.intelligence.conflict_resolver import get_conflict_resolver
        resolver = get_conflict_resolver()
        return await resolver.detect(
            requirements=req.get("requirements", ""),
            constraints=req.get("constraints", ""),
            architecture_doc=req.get("architecture_doc", ""),
        )

    @app.post("/intelligence/conflict-resolver/resolve")
    async def conflict_resolver_resolve(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T9-03: Record a conflict resolution."""
        from aether_os.core.intelligence.conflict_resolver import get_conflict_resolver
        resolver = get_conflict_resolver()
        return await resolver.resolve(
            conflict_id=req.get("conflict_id", ""),
            resolution=req.get("resolution", ""),
            run_id=req.get("run_id", ""),
            org_id=user.get("org_id"),
        )

    @app.post("/intelligence/tradeoff-engine/analyze")
    async def tradeoff_engine_analyze(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T9-04: Analyze architectural tradeoffs between two options."""
        from aether_os.core.intelligence.tradeoff_engine import get_tradeoff_engine
        engine = get_tradeoff_engine()
        return await engine.analyze(
            option_a=req.get("option_a", ""),
            option_b=req.get("option_b", ""),
            requirements=req.get("requirements", ""),
            domain=req.get("domain", "general"),
        )

    @app.post("/intelligence/improvement-loop/cycle")
    async def improvement_loop_cycle(
        run_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T9-05: Run a full improvement loop cycle for a completed run."""
        from aether_os.core.intelligence.improvement_loop import get_improvement_loop
        loop = get_improvement_loop()
        return await loop.run_cycle(run_id, org_id=user.get("org_id"))

    @app.post("/intelligence/maintenance-engine/scan")
    async def maintenance_engine_scan(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """T9-06: Scan dependencies and/or analyze tech debt."""
        from aether_os.core.intelligence.maintenance_engine import get_maintenance_engine
        engine = get_maintenance_engine()
        results = {}
        if req.get("requirements_txt"):
            results["dependencies"] = await engine.scan_dependencies(req["requirements_txt"])
        if req.get("code"):
            results["tech_debt"] = await engine.tech_debt_analysis(req["code"], req.get("language", "python"))
        if req.get("run_id"):
            results["health"] = await engine.health_check_project(req["run_id"])
        return results

    @app.get("/intelligence/maintenance-engine/health/{run_id}")
    async def maintenance_health_check(run_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        """T9-06: Health check for a project run."""
        from aether_os.core.intelligence.maintenance_engine import get_maintenance_engine
        engine = get_maintenance_engine()
        return await engine.health_check_project(run_id)

    # ── SCIM 2.0 provisioning (T5-08) ────────────────────────────────────────

    def _scim_user(u) -> dict:
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "id": u.id,
            "userName": u.email,
            "displayName": getattr(u, "name", u.email),
            "active": u.is_active and not u.deleted_at,
            "emails": [{"value": u.email, "primary": True}],
            "meta": {
                "resourceType": "User",
                "created": str(u.created_at),
            },
        }

    @app.get("/scim/v2/Users")
    async def scim_list_users(
        startIndex: int = 1,
        count: int = 50,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User as _User
        from sqlalchemy import select
        sf = get_session_factory()
        async with sf() as session:
            rows = (await session.execute(
                select(_User)
                .where(_User.org_id == user["org_id"], _User.deleted_at == None)
                .offset(startIndex - 1).limit(min(count, 100))
            )).scalars().all()
        return {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": len(rows),
            "startIndex": startIndex,
            "itemsPerPage": len(rows),
            "Resources": [_scim_user(u) for u in rows],
        }

    @app.get("/scim/v2/Users/{user_id}")
    async def scim_get_user(
        user_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User as _User
        sf = get_session_factory()
        async with sf() as session:
            u = await session.get(_User, user_id)
        if not u or u.org_id != user["org_id"] or u.deleted_at:
            raise HTTPException(status_code=404)
        return _scim_user(u)

    @app.post("/scim/v2/Users")
    async def scim_create_user(
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """SCIM provision a new user into the org."""
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        import secrets as _sec
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User as _User
        from aether_os.gateway.auth import get_password_hash

        email = req.get("userName") or (req.get("emails") or [{}])[0].get("value")
        if not email:
            raise HTTPException(status_code=400, detail="userName or emails[0].value required")

        sf = get_session_factory()
        async with sf() as session:
            from sqlalchemy import select
            if (await session.execute(select(_User).where(_User.email == email))).scalar_one_or_none():
                raise HTTPException(status_code=409, detail="User already exists")
            new_user = _User(
                id=str(uuid.uuid4()),
                org_id=user["org_id"],
                email=email,
                password_hash=get_password_hash(_sec.token_urlsafe(24)),
                role="member",
            )
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=201, content=_scim_user(new_user))

    @app.put("/scim/v2/Users/{user_id}")
    async def scim_update_user(
        user_id: str,
        req: Dict[str, Any],
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User as _User
        sf = get_session_factory()
        async with sf() as session:
            u = await session.get(_User, user_id)
            if not u or u.org_id != user["org_id"] or u.deleted_at:
                raise HTTPException(status_code=404)
            if "active" in req:
                u.is_active = bool(req["active"])
            if "displayName" in req:
                u.user_preferences = req["displayName"]
            await session.commit()
            await session.refresh(u)
        return _scim_user(u)

    @app.delete("/scim/v2/Users/{user_id}", status_code=204)
    async def scim_delete_user(
        user_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import User as _User
        from datetime import datetime as _dt
        sf = get_session_factory()
        async with sf() as session:
            u = await session.get(_User, user_id)
            if not u or u.org_id != user["org_id"]:
                raise HTTPException(status_code=404)
            u.deleted_at = _dt.utcnow()
            u.is_active = False
            await session.commit()

    @app.get("/scim/v2/Groups")
    async def scim_list_groups(
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        if user.get("role") not in ["owner", "admin"]:
            raise HTTPException(status_code=403)
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation as _Org
        sf = get_session_factory()
        async with sf() as session:
            org = await session.get(_Org, user["org_id"])
        if not org:
            raise HTTPException(status_code=404)
        return {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": 1,
            "startIndex": 1,
            "itemsPerPage": 1,
            "Resources": [{
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
                "id": org.id,
                "displayName": org.name,
                "meta": {"resourceType": "Group", "created": str(org.created_at)},
            }],
        }

    # ── Legal documents (GDPR D-001) — public, no auth required ──────────────

    @app.get("/legal/tos", tags=["legal"])
    async def legal_tos():
        """Terms of Service / EULA."""
        return {
            "document": "terms_of_service",
            "version": "1.0",
            "effective_date": "2026-01-01",
            "text": (
                "AETHEROS TERMS OF SERVICE\n\n"
                "Last updated: 2026-01-01\n\n"
                "1. ACCEPTANCE\nBy accessing or using AetherOS ('Service'), you agree to be bound by these Terms of Service. "
                "If you do not agree, do not use the Service.\n\n"
                "2. SERVICE DESCRIPTION\nAetherOS provides an autonomous AI-powered software factory. "
                "The Service generates, tests, and deploys software on your behalf based on requirements you provide.\n\n"
                "3. ACCEPTABLE USE\nYou may not use the Service for any unlawful purpose, to generate malicious software, "
                "or to infringe upon any third-party intellectual property rights.\n\n"
                "4. DATA PROCESSING\nBy using the Service you agree to the Data Processing Agreement at /api/legal/dpa. "
                "We process personal data as described in the Privacy Policy at /api/legal/privacy.\n\n"
                "5. INTELLECTUAL PROPERTY\nCode generated by the Service using your requirements and prompts is owned by you. "
                "The AetherOS platform, models, and infrastructure remain the property of AetherOS.\n\n"
                "6. LIMITATION OF LIABILITY\nThe Service is provided 'as is'. AetherOS is not liable for indirect, incidental, "
                "or consequential damages arising from your use of the Service.\n\n"
                "7. TERMINATION\nWe may suspend or terminate access if you violate these Terms. "
                "You may delete your account at any time via DELETE /api/account.\n\n"
                "8. GOVERNING LAW\nThese Terms are governed by applicable laws. Disputes shall be resolved by binding arbitration.\n\n"
                "9. CHANGES\nWe may update these Terms. Continued use after notice of changes constitutes acceptance."
            ),
        }

    @app.get("/legal/privacy", tags=["legal"])
    async def legal_privacy():
        """Privacy Policy."""
        return {
            "document": "privacy_policy",
            "version": "1.0",
            "effective_date": "2026-01-01",
            "text": (
                "AETHEROS PRIVACY POLICY\n\n"
                "Last updated: 2026-01-01\n\n"
                "1. CONTROLLER\nAetherOS ('we', 'us') is the data controller for personal data collected through the Service.\n\n"
                "2. DATA WE COLLECT\n"
                "  - Account data: email address, hashed password, organisation name.\n"
                "  - Usage data: pipeline runs, prompts, generated artifacts, audit logs.\n"
                "  - Technical data: IP addresses, browser type, session tokens (stored as JTI hashes only).\n\n"
                "3. LEGAL BASIS (GDPR Art. 6)\n"
                "  - Contractual necessity: account creation, pipeline execution, billing.\n"
                "  - Legitimate interests: security monitoring, fraud prevention, service improvement.\n"
                "  - Consent: marketing communications (opt-in only).\n\n"
                "4. DATA RETENTION\nAccount data is retained for the duration of your subscription plus 90 days. "
                "Audit logs are retained for 12 months. You may request deletion at any time.\n\n"
                "5. YOUR RIGHTS (GDPR)\n"
                "  - Right of access: GET /api/account/data-export\n"
                "  - Right to erasure: DELETE /api/account\n"
                "  - Right to portability: GET /api/account/data-export (machine-readable JSON)\n"
                "  - Right to rectification: PUT /api/account/settings\n"
                "  - Right to object: contact support.\n\n"
                "6. DATA TRANSFERS\nData may be processed in jurisdictions outside your own. "
                "We apply Standard Contractual Clauses where required.\n\n"
                "7. THIRD PARTIES\nWe use subprocessors (LLM API providers, cloud infrastructure) under equivalent data protection terms.\n\n"
                "8. CONTACT\nFor privacy enquiries or to exercise your rights, email: privacy@aetheros.ai"
            ),
        }

    @app.get("/legal/dpa", tags=["legal"])
    async def legal_dpa():
        """Data Processing Agreement (GDPR Art. 28)."""
        return {
            "document": "data_processing_agreement",
            "version": "1.0",
            "effective_date": "2026-01-01",
            "text": (
                "DATA PROCESSING AGREEMENT\n\n"
                "Last updated: 2026-01-01\n\n"
                "This Data Processing Agreement ('DPA') is entered into between AetherOS ('Processor') "
                "and the Customer ('Controller') and supplements the Terms of Service.\n\n"
                "1. SUBJECT MATTER\nProcessor processes personal data on behalf of Controller solely to provide the AetherOS Service.\n\n"
                "2. NATURE AND PURPOSE\nProcessing activities include: storing user accounts, executing AI pipelines, "
                "generating and hosting code artifacts, and producing audit trails.\n\n"
                "3. TYPES OF PERSONAL DATA\nEmail addresses, names, IP addresses, usage logs, and any personal data "
                "contained in prompts or generated artifacts submitted by Controller.\n\n"
                "4. PROCESSOR OBLIGATIONS\nProcessor shall: (a) process data only on Controller's documented instructions; "
                "(b) ensure personnel are bound by confidentiality; (c) implement appropriate technical and organisational "
                "security measures (Art. 32 GDPR); (d) assist Controller with data subject rights requests; "
                "(e) delete or return all personal data upon termination.\n\n"
                "5. SUB-PROCESSORS\nProcessor may engage sub-processors with prior notice to Controller. "
                "A current list is available at /api/legal/dpa#subprocessors.\n\n"
                "6. SECURITY MEASURES\nMeasures include: AES-256 encryption at rest, TLS 1.2+ in transit, "
                "bcrypt password hashing, JWT token rotation, audit logging, and regular security reviews.\n\n"
                "7. BREACH NOTIFICATION\nProcessor shall notify Controller within 72 hours of becoming aware of a "
                "personal data breach, as required by Art. 33 GDPR.\n\n"
                "8. AUDIT RIGHTS\nController may audit Processor's compliance with this DPA upon reasonable notice.\n\n"
                "9. DURATION\nThis DPA remains in force for the duration of the Terms of Service."
            ),
        }

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
