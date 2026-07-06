"""Fixed production file templates for the generated FastAPI backend.

These are static strings written verbatim into the generated app's src/ directory.
No LLM involvement — pure deterministic output.

Larger application-level templates (main.py, alembic, Dockerfile, requirements)
and their builder functions live in templates_main.py and are re-exported here
so all existing imports continue to work.
"""
from __future__ import annotations

# Re-export everything from templates_main so callers can import from either module.
from phases.p04a_backend_codegen.templates_main import (  # noqa: F401
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

# PostgreSQL is first-class default; SQLite is local-dev fallback only.
_RAW_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/appdb")

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
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
        poolclass=_NullPool,
    )
else:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=int(os.environ.get("DB_POOL_SIZE", str(max(4, (os.cpu_count() or 1) * 2)))),
        max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "20")),
        pool_recycle=300,
        connect_args={"options": "-c statement_timeout=30000"},
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

# Default .env content for generated apps — PostgreSQL first-class, SQLite as local-dev fallback.
# Exported so task_agent.py and helpers.py can import a single canonical template.
_ENV_TEMPLATE = """\
# Database — PostgreSQL is the production default.
# For local development without PostgreSQL, set to: sqlite+aiosqlite:///./app.db
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/appdb
# For local SQLite fallback (development only): DATABASE_URL=sqlite:///./app.db
# JWT uses RS256. Keys are auto-generated as private_key.pem / public_key.pem on first run.
# Override paths with RSA_PRIVATE_KEY_PATH / RSA_PUBLIC_KEY_PATH env vars.
# INVITE_SECRET is used only for org invite tokens (HS256, short-lived).
INVITE_SECRET={secret_key}
ACCESS_TOKEN_EXPIRE_MINUTES=60
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
ENVIRONMENT=development
DEBUG=false
ADMIN_PASSWORD=Admin1234!
# Connection pool tuning — defaults to cpu_count*2 (min 4). Increase for high traffic.
# DB_POOL_SIZE=20
# DB_MAX_OVERFLOW=40
"""

# Docker-compose template — adds a postgres:15-alpine service alongside the app.
_DOCKER_COMPOSE_TEMPLATE = """\
version: '3.9'
services:
  db:
    image: postgres:15-alpine
    restart: always
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: appdb
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    restart: always
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/appdb
      SECRET_KEY: ${SECRET_KEY:-changeme-set-in-env}
      CORS_ORIGINS: ${CORS_ORIGINS:-http://localhost:3000}
      ENVIRONMENT: production
    depends_on:
      db:
        condition: service_healthy

volumes:
  pgdata:
"""

_AUTH_PY = '''\
"""JWT access + refresh tokens (RS256), bcrypt password hashing, FastAPI dependencies.

RS256 keypair is auto-generated on first startup if the PEM files are absent.
Set RSA_PRIVATE_KEY_PATH / RSA_PUBLIC_KEY_PATH env vars to use pre-existing keys.
"""
from __future__ import annotations
import os
import logging
import bcrypt as _bcrypt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt; JWTError = jwt.exceptions.PyJWTError

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = 7

_PRIVATE_KEY_PATH = os.environ.get("RSA_PRIVATE_KEY_PATH", "private_key.pem")
_PUBLIC_KEY_PATH = os.environ.get("RSA_PUBLIC_KEY_PATH", "public_key.pem")


def _ensure_rsa_keys() -> None:
    """Auto-generate a 2048-bit RSA keypair on first run if the PEM files are missing."""
    if os.path.exists(_PRIVATE_KEY_PATH) and os.path.exists(_PUBLIC_KEY_PATH):
        return
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with open(_PRIVATE_KEY_PATH, "wb") as f:
            f.write(private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
        with open(_PUBLIC_KEY_PATH, "wb") as f:
            f.write(private_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
        logger.info("auth: generated RSA-2048 keypair (%s, %s)", _PRIVATE_KEY_PATH, _PUBLIC_KEY_PATH)
    except Exception as exc:
        logger.error("auth: RSA keypair generation failed: %s", exc)
        raise RuntimeError(f"Cannot generate RSA keys for JWT signing: {exc}") from exc


def _load_private_key():
    _ensure_rsa_keys()
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    with open(_PRIVATE_KEY_PATH, "rb") as f:
        return load_pem_private_key(f.read(), password=None)


def _load_public_key():
    _ensure_rsa_keys()
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    with open(_PUBLIC_KEY_PATH, "rb") as f:
        return load_pem_public_key(f.read())


# Load keys once at module import (auto-generates if missing)
_ensure_rsa_keys()
_PRIVATE_KEY = _load_private_key()
_PUBLIC_KEY = _load_public_key()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def get_password_hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def create_access_token(user_id: int | str, email: str, role: str, org_id: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict = {"sub": str(user_id), "email": email, "role": role, "exp": expire, "type": "access"}
    if org_id:
        payload["org_id"] = str(org_id)
    return jwt.encode(payload, _PRIVATE_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: int | str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "refresh"},
        _PRIVATE_KEY,
        algorithm=ALGORITHM,
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _PUBLIC_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise exc
        sub = payload.get("sub")
        if not sub:
            raise exc
        return {"id": sub, "email": payload.get("email", ""), "role": payload.get("role", "user"), "org_id": payload.get("org_id")}
    except JWTError:
        raise exc


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
'''

_CONFIG_PY = '''\
"""Application settings loaded from environment variables."""
from __future__ import annotations
import os
from functools import lru_cache


class Settings:
    app_name: str = os.environ.get("APP_NAME", "API")
    environment: str = os.environ.get("ENVIRONMENT", "development")
    database_url: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./app.db")
    secret_key: str = os.environ.get("SECRET_KEY", "")
    # CORS_ORIGINS must be set explicitly — no wildcard default (security hardening)
    cors_origins: list[str] = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]
    debug: bool = os.environ.get("DEBUG", "false").lower() == "true"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
'''

_AUTH_ROUTER_PY = '''\
"""Auth endpoints — login, register, refresh token, current user."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    get_current_user,
    ALGORITHM,
    _PUBLIC_KEY,
)

try:
    from rate_limiter import limiter as _limiter
    _limit = _limiter.limit
except Exception:
    def _limit(s):  # no-op when slowapi not available
        def _d(f): return f
        return _d

try:
    from models import User
except ImportError:
    User = None  # type: ignore[assignment,misc]

import jwt; JWTError = jwt.exceptions.PyJWTError

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
@_limit("10/minute")
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    if User is None:
        raise HTTPException(status_code=503, detail="User model not available")
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return TokenResponse(
        access_token=create_access_token(user.id, user.email, getattr(user, "role", "user"), org_id=str(getattr(user, "org_id", "") or "")),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@_limit("5/minute")
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if User is None:
        raise HTTPException(status_code=503, detail="User model not available")
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        email=data.email,
        password_hash=get_password_hash(data.password),
        role="user",
        **({"name": data.name} if data.name and hasattr(User, "name") else {}),
    )
    db.add(user)
    await db.flush()
    return TokenResponse(
        access_token=create_access_token(user.id, user.email, getattr(user, "role", "user")),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    if User is None:
        raise HTTPException(status_code=503, detail="User model not available")
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    try:
        payload = jwt.decode(data.refresh_token, _PUBLIC_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise exc
        user_id = payload.get("sub")
        if not user_id:
            raise exc
    except JWTError:
        raise exc
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise exc
    return TokenResponse(
        access_token=create_access_token(user.id, user.email, getattr(user, "role", "user")),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return current_user
'''

_RATE_LIMITER_PY = '''\
"""Shared SlowAPI rate limiter — imported by main.py and any router that needs limits.

Key function: per-user (hashed JWT token prefix) on authenticated endpoints so
limits are per-account rather than per-IP.  Falls back to the source IP for
unauthenticated requests so the /auth/login brute-force limit still works.
"""
import hashlib
from fastapi import Request
from slowapi import Limiter


def _get_rate_limit_key(request: Request) -> str:
    # Per-user limiting on authenticated endpoints — prevents one busy user
    # from burning the shared IP quota for all users behind a NAT/proxy.
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        # Hash the first 40 chars of the token (enough entropy, avoids storing the token)
        return f"user:{hashlib.md5(auth[7:47].encode()).hexdigest()}"
    # Unauthenticated — fall back to source IP so brute-force limits still apply
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_rate_limit_key, default_limits=["200/minute"])
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
'''

