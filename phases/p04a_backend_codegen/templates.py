"""Fixed production file templates for the generated FastAPI backend.

These are static strings written verbatim into the generated app's src/ directory.
No LLM involvement — pure deterministic output.
"""
from __future__ import annotations

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

_MAIN_PY_TEMPLATE = '''\
"""
{PROJECT_NAME} API — Generated by AetherOS
Production-ready FastAPI backend with async SQLAlchemy, JWT auth, CORS, structured logging.
"""
from __future__ import annotations
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure this file's directory is on sys.path so absolute imports work whether
# uvicorn is invoked as "main:app" (cwd=src/) or "src.main:app" (cwd=parent/).
_self_dir = Path(__file__).resolve().parent
if str(_self_dir) not in sys.path:
    sys.path.insert(0, str(_self_dir))

# Load .env before importing anything that reads os.environ
try:
    from dotenv import load_dotenv
    try:
        _here = Path(__file__).resolve().parent
    except NameError:
        _here = Path(os.getcwd())  # fallback when __file__ not available (e.g. exec context)
    load_dotenv(dotenv_path=_here.parent / ".env", override=False)
    load_dotenv(dotenv_path=_here.parent.parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed; env vars must be set externally

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from database import engine, Base
from routers.auth import router as auth_router
{ROUTER_IMPORTS}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting {PROJECT_NAME} API …")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        from seed import seed_database
        await seed_database()
        logger.info("Database seeding complete")
    except Exception as exc:
        logger.warning("Seed skipped: %s", exc)
    yield
    await engine.dispose()
    logger.info("{PROJECT_NAME} API shutting down")


app = FastAPI(
    title="{PROJECT_NAME} API",
    version="1.0.0",
    description="Auto-generated production backend by AetherOS",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    root_path=os.environ.get("ROOT_PATH", ""),
)

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start = time.time()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    duration_ms = int((time.time() - start) * 1000)
    logger.info(
        "method=%s path=%s status=%d duration_ms=%d request_id=%s",
        request.method, request.url.path, response.status_code, duration_ms, request_id,
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "type": "InternalError"},
    )


app.include_router(auth_router, prefix="/api")
{ROUTER_INCLUDES}

# Stats router (generated when Domain IR is available)
try:
    from routers.stats import router as _stats_router
    app.include_router(_stats_router, prefix="/api")
except ImportError:
    pass


@app.get("/health", tags=["system"])
async def health():
    return {"status": "healthy", "version": "1.0.0", "service": "{PROJECT_NAME}"}


@app.get("/ready", tags=["system"])
async def ready():
    try:
        from database import engine as _engine
        async with _engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ready", "db": "ok"}
    except Exception as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"status": "not_ready", "db": str(exc)})


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "{PROJECT_NAME} API", "docs": "/docs"}
'''

_ROUTERS_INIT_PY = "from .crud import all_routers\n\n__all__ = ['all_routers']\n"

_REQUIREMENTS_TXT = """\
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
asyncpg>=0.29.0
psycopg2-binary>=2.9.0
alembic>=1.13.0
pydantic[email]>=2.0.0
PyJWT>=2.8.0
bcrypt>=4.0.0
python-multipart>=0.0.9
httpx>=0.27.0
python-dotenv>=1.0.0
slowapi>=0.1.9
email-validator>=2.1.0
"""

_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \\
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

_ALEMBIC_INI = """\
[alembic]
script_location = alembic
prepend_sys_path = .
[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""

_ALEMBIC_ENV_PY = """\
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.database import Base
from src import models  # noqa: F401 — ensures all models are registered

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url", "sqlite:///./app.db"))
    from sqlalchemy import create_engine
    connectable = create_engine(url.replace("+aiosqlite", "").replace("+asyncpg", "").replace("+aiomysql", ""),
                                poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
"""

_ALEMBIC_SCRIPT_PY_MAKO = """\
\"\"\"${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
\"\"\"
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
"""

_SERVICES_INIT_PY = ""


def _build_main_py(project_name: str, routers_have_all_routers: bool) -> str:
    """Render the main.py template with router wiring."""
    if routers_have_all_routers:
        router_imports = "from routers.crud import all_routers"
        router_includes = "for _router in all_routers:\n    app.include_router(_router, prefix='/api')"
    else:
        router_imports = "# No CRUD routers"
        router_includes = ""
    return _MAIN_PY_TEMPLATE.replace("{PROJECT_NAME}", project_name).replace(
        "{ROUTER_IMPORTS}", router_imports
    ).replace("{ROUTER_INCLUDES}", router_includes)


def _generate_makefile(project_name: str) -> str:
    slug = project_name.lower().replace(" ", "-")
    return f"""\
.PHONY: dev test lint migrate seed install clean

install:
\tpip install -r requirements.txt

dev:
\tuvicorn src.main:app --reload --host 0.0.0.0 --port 8000

test:
\tpytest tests/ -v --tb=short

lint:
\truff check src/ && ruff format --check src/

migrate:
\talembic upgrade head

migration:
\t@read -p "Migration name: " name; alembic revision --autogenerate -m "$$name"

seed:
\tpython3 -c "import asyncio; from src.seed import seed_database; asyncio.run(seed_database())"

docker:
\tdocker-compose up --build

clean:
\tfind . -type d -name __pycache__ -exec rm -rf {{}} + 2>/dev/null || true
\tfind . -name "*.pyc" -delete
\trm -f test_*.db
"""


def _generate_backend_readme(project_name: str, entities: list) -> str:
    entity_list = "\n".join(
        f"- {e.get('name', e.get('table', ''))} — `/api/{e.get('table', '')}`"
        for e in entities[:10]
    )
    return f"""\
# {project_name} API

Auto-generated production backend by AetherOS.

## Quick Start

```bash
cp .env.example .env
make install
make migrate
make seed
make dev
```

API docs: http://localhost:8000/docs

## Auth

POST /api/auth/login     — email + password → access_token + refresh_token
POST /api/auth/register  — email + password + name → tokens
POST /api/auth/refresh   — refresh_token → new access_token
GET  /api/auth/me        — current user (requires Bearer token)

## Entities

{entity_list}

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| DATABASE_URL | sqlite+aiosqlite:///./app.db | DB connection |
| SECRET_KEY | change-me | JWT signing key |
| CORS_ORIGINS | * | Comma-separated allowed origins |
| ENVIRONMENT | development | development / production |

## Tests

```bash
make test
```

## Migrations

```bash
make migrate          # Apply all pending
make migration        # Create a new migration
```
"""
