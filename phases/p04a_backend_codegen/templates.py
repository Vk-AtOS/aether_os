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
)

# ── Fixed production templates ─────────────────────────────────────────────────

_DATABASE_PY = '''\
"""Async SQLAlchemy engine + session factory."""
from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./app.db")

_is_sqlite = "sqlite" in DATABASE_URL
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
        pool_size=10,
        max_overflow=20,
        pool_recycle=300,
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

_AUTH_PY = '''\
"""JWT access + refresh tokens, bcrypt password hashing, FastAPI dependencies."""
from __future__ import annotations
import os
import bcrypt as _bcrypt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt; JWTError = jwt.exceptions.PyJWTError

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    import secrets as _secrets_mod
    SECRET_KEY = _secrets_mod.token_hex(32)  # ephemeral; set SECRET_KEY env var for persistence
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = 7

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def get_password_hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def create_access_token(user_id: int | str, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "email": email, "role": role, "exp": expire, "type": "access"},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_refresh_token(user_id: int | str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "refresh"},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise exc
        sub = payload.get("sub")
        if not sub:
            raise exc
        return {"id": sub, "email": payload.get("email", ""), "role": payload.get("role", "user")}
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
from fastapi import APIRouter, Depends, HTTPException, status
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
    SECRET_KEY,
    ALGORITHM,
)

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
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
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
        access_token=create_access_token(user.id, user.email, getattr(user, "role", "user")),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
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
        payload = jwt.decode(data.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
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

