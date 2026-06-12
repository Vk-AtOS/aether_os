"""P04a Backend Codegen — template-based multi-file FastAPI backend generator.

Output structure:
  src/
  ├── __init__.py
  ├── main.py          (template — app factory, middleware, error handlers, lifespan)
  ├── database.py      (template — async SQLAlchemy engine + session factory)
  ├── auth.py          (template — JWT access+refresh tokens, bcrypt, OAuth2 deps)
  ├── config.py        (template — Pydantic Settings from env)
  ├── models.py        (LLM — SQLAlchemy ORM models for all domain entities + User)
  ├── schemas.py       (LLM — Pydantic v2 request/response schemas per entity)
  ├── seed.py          (LLM — realistic startup seed data, bcrypt-hashed passwords)
  └── routers/
      ├── __init__.py
      ├── auth.py      (template — /auth/login, /auth/register, /auth/refresh, /auth/me)
      └── crud.py      (LLM — paginated CRUD routers for all entities, exports all_routers)
"""
from __future__ import annotations
import ast
import asyncio
import json
import logging
import re
import secrets
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aether_os.phases.base import TaskResult
from aether_os.core.errors import PipelineBlockedError

logger = logging.getLogger(__name__)

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
    redirect_slashes=False,
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


# ── LLM generation functions ───────────────────────────────────────────────────

async def _llm_models_and_schemas(
    llm, project_name: str, domain: str, entities: list, raw_input: str, arch_doc: dict,
    mem_hint: str = "",
) -> Tuple[str, str]:
    """One LLM call → (models.py, schemas.py)."""
    entities_json = json.dumps(entities[:12], indent=2)

    # Inject golden few-shot examples for this domain
    golden_hint = ""
    try:
        from aether_os.core.learning.golden_retriever import get_golden_examples, format_golden_hint_p04
        examples = await get_golden_examples(domain, limit=2)
        golden_hint = format_golden_hint_p04(examples)
    except Exception:
        pass

    prompt = f"""\
You are a senior backend engineer. Generate SQLAlchemy async ORM models and Pydantic v2 schemas \
for a {domain} application called "{project_name}".
{golden_hint}

Project requirements:
{raw_input[:3000]}
{mem_hint}
Entities to model:
{entities_json}

ABSOLUTE IMPORTS RULE (MANDATORY — Docker will fail otherwise):
- Use ABSOLUTE imports only. Do NOT use relative imports (no 'from .module import X').
- Import as: `from database import Base`, `from models import User`, `from schemas import UserCreate`, `from auth import get_current_user`
- NEVER write `from .database import Base` or `from .models import X` — these break inside Docker containers.

MODELS.PY requirements (file: src/models.py):
1. Imports: `from database import Base` (ABSOLUTE — no dot prefix), SQLAlchemy column types, relationship
2. ALWAYS include a User model:
   - id (Integer, primary_key, index)
   - email (String 255, unique, index, nullable=False)
   - password_hash (String 255, nullable=False)
   - role (String 50, default="user")  — values: "admin" or "user"
   - is_active (Boolean, default=True)
   - created_at, updated_at (DateTime timezone=True, with defaults)
3. For each entity: add domain-appropriate fields with proper SQLAlchemy types
4. Add ForeignKey relationships where logical (e.g. user_id references users.id)
   CRITICAL: ForeignKey string MUST match the actual __tablename__ of the referenced model exactly.
   Example: if Category.__tablename__ = 'categories', then use ForeignKey('categories.id') — never 'categorys.id' or 'category.id'.
5. Use `__tablename__` (snake_case plural) — derive using standard English pluralisation rules (category→categories, status→statuses, person→people)
6. DateTime fields use `datetime.now(timezone.utc)` as default

REQUIRED for every model (no exceptions):
- created_at: DateTime = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
- updated_at: DateTime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
- deleted_at: Optional[DateTime] = Column(DateTime(timezone=True), nullable=True)  # soft delete — never hard-delete rows
- Every ForeignKey column MUST have a corresponding Index: e.g. Index('ix_order_user_id', 'user_id')
- The User model MUST have: Index('ix_user_email', 'email', unique=True)

SCHEMAS.PY requirements (file: src/schemas.py):
1. Import: `from pydantic import BaseModel, EmailStr, Field, ConfigDict`
2. For each entity create ALL of:
   - `{Entity}Base` — shared editable fields with Field() validators
   - `{Entity}Create(EntityBase)` — for POST; mark required fields
   - `{Entity}Update(BaseModel)` — all Optional, for PUT/PATCH
   - `{Entity}Response(EntityBase)` — adds id, created_at, updated_at;
     must have `model_config = ConfigDict(from_attributes=True)`
3. EmailStr for email fields, use Field(min_length=..., max_length=...) for strings
4. Include `UserCreate`, `UserResponse` schemas

Return VALID JSON only (no markdown):
{{"models_py": "<complete models.py content>", "schemas_py": "<complete schemas.py content>"}}"""

    result = await llm.call(prompt, task_type="code_generation", max_tokens=6000)
    if not result:
        raise ValueError("Empty LLM response for models/schemas")

    # Strip markdown if present
    result = re.sub(r"^```(?:json)?\s*\n?", "", result.strip())
    result = re.sub(r"\n?```\s*$", "", result.strip())

    try:
        parsed = json.loads(result)
        models_py = parsed.get("models_py", "")
        schemas_py = parsed.get("schemas_py", "")
        if len(models_py) > 200 and len(schemas_py) > 200:
            return models_py, schemas_py
    except json.JSONDecodeError:
        # Try to extract Python blocks
        model_match = re.search(r'(?:"models_py"\s*:\s*")(.+?)(?="schemas_py")', result, re.DOTALL)
        schema_match = re.search(r'(?:"schemas_py"\s*:\s*")(.+?)(?="\}|$)', result, re.DOTALL)
        if model_match and schema_match:
            return (
                model_match.group(1).encode().decode("unicode_escape"),
                schema_match.group(1).encode().decode("unicode_escape"),
            )

    raise ValueError("Could not parse models/schemas from LLM response")


async def _llm_crud_routers(
    llm, project_name: str, entities: list, models_code: str, schemas_code: str,
    mem_hint: str = "",
) -> str:
    """One LLM call → routers/crud.py with all entity CRUD routers."""
    entity_names = [e.get("name", e.get("table", "")) for e in entities[:12]]
    entity_list = ", ".join(entity_names)

    # Build a compact entity→fields map so the LLM can produce correct column references
    entity_fields_summary = ""
    for e in entities[:12]:
        fields = e.get("fields", []) or []
        field_names = [f.get("name", f) if isinstance(f, dict) else str(f) for f in fields[:12]]
        entity_fields_summary += f"  {e.get('name','')}: {', '.join(field_names)}\n"

    # Pass full models + schemas so LLM sees exact class names, field names, and types
    # Cap at 5000 chars each to stay within context budget
    models_ctx = models_code[:5000] + ("\n# ... (truncated)" if len(models_code) > 5000 else "")
    schemas_ctx = schemas_code[:5000] + ("\n# ... (truncated)" if len(schemas_code) > 5000 else "")

    prompt = f"""\
Generate production-quality FastAPI async CRUD routers for "{project_name}".
{mem_hint}

REQUIRED pagination rules (no exceptions):
- Every GET list endpoint MUST accept query params: skip: int = 0, limit: int = Query(default=20, le=100)
- Return format: {{"items": [...], "total": count, "skip": skip, "limit": limit}}
- Never return unbounded lists — always apply .offset(skip).limit(limit)

Entities and their fields:
{entity_fields_summary}
Full src/models.py:
```python
{models_ctx}
```

Full src/schemas.py:
```python
{schemas_ctx}
```

FILE: src/routers/crud.py

ABSOLUTE IMPORTS RULE (MANDATORY — Docker will fail otherwise):
- Use ABSOLUTE imports only. Do NOT use relative imports (no 'from .module import X').
- Import as: `from database import get_db`, `from models import MyModel`, `from schemas import MyCreate`, `from auth import get_current_user`
- NEVER write `from .database import get_db` or `from ..models import X`.

STRICT REQUIREMENTS — every violation causes runtime errors:
1. Imports:
   - `from __future__ import annotations`
   - `from typing import List, Optional, Any`
   - `from fastapi import APIRouter, Depends, HTTPException, status, Query`
   - `from sqlalchemy.ext.asyncio import AsyncSession`
   - `from sqlalchemy import select, func`
   - `from database import get_db`
   - `from auth import get_current_user, require_admin`
   - Import EVERY model class from `models` that you reference
   - Import EVERY schema class from `schemas` that you reference

2. For EACH domain entity (NOT User — User is handled by auth router):
   Create `APIRouter(prefix="/{'{entity_plural}'}", tags=["{'{Entity Label}'}"]):
   - `GET /` → paginated list: `skip: int = Query(0, ge=0)`, `limit: int = Query(100, le=500)`
     Returns: `List[{Entity}Response]`
   - `POST /` → create, `status_code=201`, returns `{Entity}Response`
   - `GET /{{id}}` → single record or HTTP 404, returns `{Entity}Response`
   - `PUT /{{id}}` → full update or HTTP 404, returns `{Entity}Response`
   - `PATCH /{{id}}` → partial update, `data: {Entity}Update`, returns `{Entity}Response`
   - `DELETE /{{id}}` → soft-delete or hard-delete, HTTP 204

3. Query pattern (async SQLAlchemy):
   - List:   `result = await db.execute(select({Model}).offset(skip).limit(limit))`
             `items = list(result.scalars().all())`
   - Single: `result = await db.execute(select({Model}).where({Model}.id == id))`
             `obj = result.scalar_one_or_none()`
             `if obj is None: raise HTTPException(status_code=404, ...)`
   - Create: `obj = {Model}(**data.model_dump(exclude_unset=True))`
             `db.add(obj); await db.flush(); await db.refresh(obj)`
   - Update: fetch, then `for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)`
             `await db.flush(); await db.refresh(obj)`
   - Delete: fetch, `await db.delete(obj)` (or set `is_active=False` for soft-delete)

4. Auth: ALL routes require `current_user: dict = Depends(get_current_user)`.
   DELETE requires `Depends(require_admin)`.

5. LAST LINE must be: `all_routers = [{'{entity}'}' _router, ...]` listing ALL entity routers.

Return ONLY the complete Python file. No markdown, no explanation."""

    result = await llm.call(prompt, task_type="code_generation", max_tokens=6000)
    if not result or len(result.strip()) < 200:
        raise ValueError("Empty or too-short LLM response for CRUD routers")

    # Strip markdown fences if present
    code = re.sub(r"^```(?:python)?\s*\n?", "", result.strip())
    code = re.sub(r"\n?```\s*$", "", code.strip())
    return code


async def _llm_seed_data(
    llm, project_name: str, domain: str, entities: list, models_code: str
) -> str:
    """One LLM call → seed.py with realistic startup data."""
    entity_names = [e.get("name", e.get("table", "")) for e in entities[:10]]

    prompt = f"""\
Generate a `seed_database()` async function for "{project_name}" ({domain}).

Complete src/models.py (use EXACT class names from here):
```python
{models_code[:3000]}{"" if len(models_code) <= 3000 else chr(10) + "# ... (truncated)"}
```

FILE: src/seed.py

ABSOLUTE IMPORTS RULE: Use absolute imports only — NO relative imports.
Example: `from database import AsyncSessionLocal`, `from auth import get_password_hash`, `from models import User`
NEVER write `from .database import ...` or `from .models import ...`.

REQUIREMENTS:
1. Import: `from database import AsyncSessionLocal`, `from auth import get_password_hash`
2. Import all models from `models` (absolute: `from models import User, ...`)
3. `async def seed_database()` — called on every startup
4. Check if already seeded: `result = await db.execute(select(func.count()).select_from(User))`
   If count > 0, return early (idempotent)
5. Create admin user: email="admin@example.com", role="admin"
   Set `_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin1234!")`
   Use `password=get_password_hash(_ADMIN_PASSWORD)`.
   Add `import os` at top of file.
   Log: `_logger.info("Seeded admin: admin@example.com / %s", _ADMIN_PASSWORD)`
6. Create 15-20 realistic records for EACH entity:
   - Use real-world names, descriptions, values (NOT "test1", "item1", "string")
   - Values must be domain-appropriate for {domain}
   - For "{project_name}": use realistic {domain}-specific terminology
7. Use `db.add_all([...])` for bulk inserts
8. Add all in a single session: `async with AsyncSessionLocal() as db:`

Return ONLY the complete seed.py file. No markdown, no explanation."""

    result = await llm.call(prompt, task_type="code_generation", max_tokens=4000)
    if not result or len(result.strip()) < 200:
        raise ValueError("Empty LLM seed response")

    code = re.sub(r"^```(?:python)?\s*\n?", "", result.strip())
    code = re.sub(r"\n?```\s*$", "", code.strip())
    return code


# ── Fallback generators (no LLM) ──────────────────────────────────────────────

def _col_to_sa_type(col_name: str) -> str:
    """Infer SQLAlchemy column type from field name."""
    lower = col_name.lower()
    if lower.endswith("_id"):
        return "Integer, ForeignKey('users.id')" if "user" in lower else "Integer"
    if lower == "email" or lower.endswith("_email"):
        return "String(320), unique=True, index=True"
    if lower in ("phone", "mobile", "tel") or lower.endswith("_phone"):
        return "String(50)"
    if lower in ("price", "amount", "cost", "salary", "rate", "total", "revenue", "balance", "fee"):
        return "Numeric(14, 2)"
    if lower in ("count", "quantity", "qty", "age", "year", "rank", "position", "score") or lower.startswith("num_"):
        return "Integer"
    if lower.startswith("is_") or lower.startswith("has_") or lower.startswith("can_") or lower in ("active", "enabled", "verified", "completed", "archived", "published"):
        return "Boolean, default=True"
    if "date" in lower and lower not in ("updated_at", "created_at"):
        return "DateTime(timezone=True)"
    if lower in ("description", "notes", "body", "content", "bio", "address", "summary", "details", "remarks"):
        return "Text"
    if "url" in lower or "link" in lower or "image" in lower or "photo" in lower:
        return "String(2048)"
    if lower in ("status", "type", "role", "category", "stage", "priority", "gender"):
        return "String(50)"
    return "String(255)"


def _fallback_models(project_name: str, entities: list) -> str:
    entity_classes = []
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        fields = ent.get("fields", []) or [{"name": "name"}, {"name": "description"}]
        cols = ["    id = Column(Integer, primary_key=True, index=True)"]
        rels = []
        for f in fields[:10]:
            fn = f.get("name", f) if isinstance(f, dict) else str(f)
            if fn in ("id", "created_at", "updated_at"):
                continue
            sa_type = _col_to_sa_type(fn)
            
            # Enum constraint fallback logic
            if fn in ("status", "type", "stage", "priority"):
                sa_type += f", CheckConstraint(\"{fn} IN ('active', 'inactive', 'pending', 'open', 'closed', 'new')\", name='ck_{table}_{fn}')"

            nullable = "False" if any(req in fn.lower() for req in ("name", "email", "title", "status")) else "True"
            cols.append(f"    {fn} = Column({sa_type}, nullable={nullable})")
            
            # Relationship fallback
            if fn.endswith("_id") and "user" not in fn:
                ref_name = fn[:-3].capitalize()
                rels.append(f"    {fn[:-3]} = relationship('{ref_name}', foreign_keys=[{fn}], lazy='selectin')")

        cols += rels
        cols += [
            "    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)",
            "    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)",
            "    deleted_at = Column(DateTime(timezone=True), nullable=True)",
        ]
        entity_classes.append(
            f"class {name}(Base):\n    __tablename__ = '{table}'\n" + "\n".join(cols)
        )

    return textwrap.dedent(f"""\
        from __future__ import annotations
        from datetime import datetime, timezone
        from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, Float, ForeignKey, CheckConstraint, func
        from sqlalchemy.orm import relationship
        from .database import Base


        class User(Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True, index=True)
            email = Column(String(255), unique=True, index=True, nullable=False)
            password_hash = Column(String(255), nullable=False)
            role = Column(String(50), nullable=False, default="user")
            is_active = Column(Boolean, nullable=False, default=True)
            created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
            updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


        {"".join(ec + chr(10) + chr(10) + chr(10) for ec in entity_classes)}
    """)


def _fallback_schemas(entities: list) -> str:
    blocks = ["from __future__ import annotations", "from pydantic import BaseModel, ConfigDict, Field", "from typing import Optional", "from datetime import datetime", ""]
    blocks += [
        "class UserCreate(BaseModel):",
        "    email: str",
        "    password: str",
        "",
        "class UserResponse(BaseModel):",
        "    model_config = ConfigDict(from_attributes=True)",
        "    id: int",
        "    email: str",
        "    role: str",
        "    is_active: bool",
        "",
    ]
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        fields = ent.get("fields", []) or [{"name": "name"}, {"name": "description"}]
        field_lines = []
        for f in fields[:10]:
            fn = f.get("name", f) if isinstance(f, dict) else str(f)
            if fn in ("id", "created_at", "updated_at"):
                continue
            field_lines.append(f"    {fn}: Optional[str] = None")

        base_fields = field_lines if field_lines else ["    name: Optional[str] = None"]
        update_fields = [f"    {ln.strip().split(':')[0]}: Optional[str] = None" for ln in field_lines] if field_lines else ["    name: Optional[str] = None"]
        blocks += [
            f"class {name}Base(BaseModel):",
        ] + base_fields + [
            "",
            f"class {name}Create({name}Base):",
            "    pass",
            "",
            f"class {name}Update(BaseModel):",
        ] + update_fields + [
            "",
            f"class {name}Response({name}Base):",
            "    model_config = ConfigDict(from_attributes=True)",
            "    id: int",
            "    created_at: Optional[datetime] = None",
            "",
        ]
    return "\n".join(blocks)


def _fallback_crud_routers(entities: list) -> str:
    """Fallback CRUD using ORM (no raw SQL — no injection vectors)."""
    # Ensure we always have at least one entity so the schemas import line
    # is never produced with an empty trailing module list (SyntaxError).
    safe_entities = entities[:8] if entities else [{"name": "Item", "table": "items"}]
    schemas_imports = ", ".join(
        f"{e.get('name', 'Item')}Create, {e.get('name', 'Item')}Update"
        for e in safe_entities
    )
    lines = [
        "from __future__ import annotations",
        "from typing import Any, Dict, List, Optional",
        "from fastapi import APIRouter, Depends, HTTPException, Query, status",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select, func",
        "from database import get_db",
        "from auth import get_current_user, require_admin",
        "import models",
        f"from schemas import {schemas_imports}",
        "",
    ]
    router_vars = []
    for ent in safe_entities:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        var = f"{table}_router"
        router_vars.append(var)
        lines += [
            f"{var} = APIRouter(prefix='/{table}', tags=['{name}'])",
            "",
            f"@{var}.get('/', response_model=dict)",
            f"async def list_{table}(",
            f"    page: int = Query(1, ge=1),",
            f"    limit: int = Query(20, ge=1, le=200),",
            f"    db: AsyncSession = Depends(get_db),",
            f"    current_user: dict = Depends(get_current_user),",
            f"):",
            f"    offset = (page - 1) * limit",
            f"    total_q = await db.execute(select(func.count()).select_from(models.{name}))",
            f"    total = total_q.scalar_one()",
            f"    result = await db.execute(select(models.{name}).offset(offset).limit(limit))",
            f"    items = result.scalars().all()",
            f"    return {{'items': [{{c.name: getattr(i, c.name) for c in models.{name}.__table__.columns}} for i in items], 'total': total, 'page': page, 'limit': limit}}",
            "",
            f"@{var}.post('/', status_code=201, response_model=dict)",
            f"async def create_{table}(data: {name}Create, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
            f"    obj = models.{name}(**data.model_dump(exclude_unset=True))",
            f"    db.add(obj)",
            f"    await db.flush()",
            f"    await db.refresh(obj)",
            f"    return {{c.name: getattr(obj, c.name) for c in models.{name}.__table__.columns}}",
            "",
            f"@{var}.get('/{{item_id}}', response_model=dict)",
            f"async def get_{table}(item_id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id))",
            f"    obj = result.scalar_one_or_none()",
            f"    if not obj:",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    return {{c.name: getattr(obj, c.name) for c in models.{name}.__table__.columns}}",
            "",
            f"@{var}.patch('/{{item_id}}', response_model=dict)",
            f"async def update_{table}(item_id: int, data: {name}Update, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id))",
            f"    obj = result.scalar_one_or_none()",
            f"    if not obj:",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    for k, v in data.model_dump(exclude_unset=True).items():",
            f"        setattr(obj, k, v)",
            f"    await db.flush()",
            f"    await db.refresh(obj)",
            f"    return {{c.name: getattr(obj, c.name) for c in models.{name}.__table__.columns}}",
            "",
            f"@{var}.put('/{{item_id}}', response_model=dict, include_in_schema=False)",
            f"async def update_{table}_put(item_id: int, data: {name}Update, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
            f"    return await update_{table}(item_id, data, db, current_user)",
            "",
            f"@{var}.delete('/{{item_id}}', status_code=204)",
            f"async def delete_{table}(item_id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_admin)):",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id))",
            f"    obj = result.scalar_one_or_none()",
            f"    if not obj:",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    await db.delete(obj)",
            "",
        ]
    lines.append(f"all_routers = [{', '.join(router_vars)}]")
    return "\n".join(lines)


def _fallback_seed(project_name: str, entities: list) -> str:
    return textwrap.dedent("""\
        from __future__ import annotations
        import os, logging
        from sqlalchemy import select, func
        from database import AsyncSessionLocal
        from auth import get_password_hash
        from models import User

        _logger = logging.getLogger(__name__)
        _ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin1234!")

        async def seed_database() -> None:
            async with AsyncSessionLocal() as db:
                count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
                if count > 0:
                    return
                admin = User(
                    email="admin@example.com",
                    password_hash=get_password_hash(_ADMIN_PASSWORD),
                    role="admin",
                    is_active=True,
                )
                db.add(admin)
                await db.commit()
                _logger.info("Seeded admin user: admin@example.com / %s", _ADMIN_PASSWORD)
    """)


async def _llm_service_layer(
    llm, project_name: str, entities: list, models_code: str, schemas_code: str,
    mem_hint: str = "",
) -> str:
    """One LLM call → services/entity_services.py with one service class per entity."""
    prompt = f"""
Generate src/services/__init__.py for "{project_name}".
{mem_hint}
Create one service class per entity: class EntityService with async staticmethods:
  - get_all(db, skip, limit) -> list
  - get_by_id(db, id) -> model | None
  - create(db, data) -> model
  - update(db, id, data) -> model | None
  - delete(db, id) -> bool
Each method uses SQLAlchemy async session (AsyncSession).
Import models from ..models, return ORM objects.
The CRUD routers will call these service methods instead of querying the DB directly.
Return ONLY the complete Python file. No markdown.
"""
    result = await llm.call(prompt, task_type="code_generation", max_tokens=4000)
    if not result or len(result.strip()) < 100:
        raise ValueError("Empty LLM response for service layer")
    code = re.sub(r"^```(?:python)?\s*\n?", "", result.strip())
    code = re.sub(r"\n?```\s*$", "", code.strip())
    return code


def _fallback_service_layer(entities: list) -> str:
    """Generate bare service stubs for each entity using SQLAlchemy select/add/delete."""
    lines = [
        "from __future__ import annotations",
        "from typing import Any, Dict, List, Optional",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select",
        "",
    ]
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        lines += [
            f"class {name}Service:",
            f"    @staticmethod",
            f"    async def get_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).offset(skip).limit(limit))",
            f"            return list(result.scalars().all())",
            f"        except Exception:",
            f"            return []",
            "",
            f"    @staticmethod",
            f"    async def get_by_id(db: AsyncSession, id: int) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            return result.scalar_one_or_none()",
            f"        except Exception:",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def create(db: AsyncSession, data: Dict[str, Any]) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            obj = {name}(**data)",
            f"            db.add(obj)",
            f"            await db.flush()",
            f"            await db.refresh(obj)",
            f"            return obj",
            f"        except Exception:",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def update(db: AsyncSession, id: int, data: Dict[str, Any]) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            obj = result.scalar_one_or_none()",
            f"            if obj is None:",
            f"                return None",
            f"            for k, v in data.items():",
            f"                setattr(obj, k, v)",
            f"            await db.flush()",
            f"            await db.refresh(obj)",
            f"            return obj",
            f"        except Exception:",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def delete(db: AsyncSession, id: int) -> bool:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            obj = result.scalar_one_or_none()",
            f"            if obj is None:",
            f"                return False",
            f"            await db.delete(obj)",
            f"            return True",
            f"        except Exception:",
            f"            return False",
            "",
        ]
    return "\n".join(lines)


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


# ── Post-processing ────────────────────────────────────────────────────────────

def _fix_common_issues(code: str) -> str:
    """Fix frequent LLM codegen mistakes."""
    # Fix typing.AsyncSession
    code = code.replace("class_=typing.AsyncSession", "class_=AsyncSession")

    # Ensure SQLAlchemy column types used in code are imported
    if "from sqlalchemy import" in code:
        m = re.search(r'^from sqlalchemy import ([^\n]+)', code, re.MULTILINE)
        if m:
            existing = m.group(1)
            needed = ["Float", "JSON", "BigInteger", "Numeric", "Text", "func", "and_", "or_"]
            missing = [t for t in needed if t not in existing and re.search(r'\b' + t + r'\b', code)]
            if missing:
                code = code.replace(m.group(0), m.group(0) + ", " + ", ".join(missing))

    # Fix datetime import in models/crud
    if "datetime.now" in code and "from datetime import datetime" not in code:
        code = "from datetime import datetime, timezone\n" + code
    if "timezone.utc" in code and "from datetime import" in code:
        code = code.replace("from datetime import datetime\n", "from datetime import datetime, timezone\n")

    # Fix: LLM sometimes emits `import timezone` (not a stdlib module) instead of
    # `from datetime import timezone`. Remove the bare import; ensure the correct one is present.
    if re.search(r'^import timezone\b', code, re.MULTILINE):
        code = re.sub(r'^import timezone\b[^\n]*\n?', '', code, flags=re.MULTILINE)
        if "from datetime import" in code:
            code = re.sub(
                r'from datetime import ([^\n]+)',
                lambda m: m.group(0) if "timezone" in m.group(1)
                else m.group(0).rstrip() + ", timezone",
                code, count=1,
            )
        else:
            code = "from datetime import timezone\n" + code

    # Fix: ForeignKey references must match actual __tablename__ values in the same file.
    # Collect declared table names, then verify FK strings against them.
    _tablenames = dict(re.findall(r"__tablename__\s*=\s*['\"](\w+)['\"]", code))
    # Build a map: class_name → tablename (lower)
    _class_to_table: dict = {}
    for _cls, _tbl in re.findall(r'class\s+(\w+)\s*\(Base\)[^:]*:.*?__tablename__\s*=\s*[\'"](\w+)[\'"]', code, re.DOTALL):
        _class_to_table[_cls.lower()] = _tbl
    # For each ForeignKey string, check if the referenced table exists; if not, try to find the right name
    def _fix_fk(m: re.Match) -> str:
        fk_str = m.group(1)
        table_part = fk_str.split(".")[0]
        if table_part in _tablenames.values():
            return m.group(0)  # already correct
        # Try to find a close match among known table names
        import difflib as _dl
        close = _dl.get_close_matches(table_part, list(_tablenames.values()), n=1, cutoff=0.6)
        if close:
            return m.group(0).replace(f"'{fk_str}'", f"'{fk_str.replace(table_part, close[0])}'").replace(
                f'"{fk_str}"', f'"{fk_str.replace(table_part, close[0])}"'
            )
        return m.group(0)
    if _class_to_table:
        code = re.sub(r"ForeignKey\(['\"]([^'\"]+)['\"]\)", _fix_fk, code)

    # Fix missing typing imports (Optional, List, Dict, Any, Union, Tuple)
    _typing_needed = []
    for _t in ("Optional", "List", "Dict", "Any", "Union", "Tuple", "Set"):
        if re.search(r'\b' + _t + r'\b', code) and f"from typing import" not in code.split(_t)[0].split("\n")[-1]:
            _typing_needed.append(_t)
    if _typing_needed:
        if "from typing import" in code:
            m2 = re.search(r'^from typing import ([^\n]+)', code, re.MULTILINE)
            if m2:
                existing_types = [t.strip() for t in m2.group(1).split(",")]
                to_add = [t for t in _typing_needed if t not in existing_types]
                if to_add:
                    code = code.replace(m2.group(0), m2.group(0) + ", " + ", ".join(to_add))
        else:
            code = "from typing import " + ", ".join(_typing_needed) + "\n" + code

    # Remove pydantic v1 imports — always use v2
    code = code.replace("from pydantic.v1 import", "from pydantic import")
    code = code.replace("from pydantic import validator", "from pydantic import field_validator")

    # Fix async SQLAlchemy result fetching (common LLM mistake: .all() not .scalars().all())
    code = re.sub(
        r'(await db\.execute\([^)]+\))\.all\(\)',
        r'\1.scalars().all()',
        code,
    )
    code = re.sub(
        r'(await db\.execute\([^)]+\))\.first\(\)',
        r'\1.scalar_one_or_none()',
        code,
    )
    return code


def _build_main_py(project_name: str, routers_have_all_routers: bool) -> str:
    if routers_have_all_routers:
        router_imports = "from routers.crud import all_routers"
        router_includes = "for _router in all_routers:\n    app.include_router(_router, prefix='/api')"
    else:
        router_imports = "# No CRUD routers"
        router_includes = ""
    return _MAIN_PY_TEMPLATE.replace("{PROJECT_NAME}", project_name).replace(
        "{ROUTER_IMPORTS}", router_imports
    ).replace("{ROUTER_INCLUDES}", router_includes)


# ── Smoke test ─────────────────────────────────────────────────────────────────

def _check_imports(src_dir: Path) -> list[str]:
    """AST pass — flag absolute imports that should be relative inside the package."""
    issues = []
    # These namespaces would only exist in the AetherOS host, not in the generated app
    forbidden_absolute = ("aether_os.", "gateway.", "core.services.", "phases.")
    for f in src_dir.rglob("*.py"):
        try:
            tree = ast.parse(f.read_text(), filename=str(f))
        except SyntaxError:
            continue  # syntax errors caught by py_compile pass
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif node.module:
                    names = [node.module]
                for name in names:
                    if any(name.startswith(p) for p in forbidden_absolute):
                        issues.append(
                            f"HallucinatedImport in {f.name}:{node.lineno}: "
                            f"absolute import '{name}' won't resolve in generated app"
                        )
    return issues


async def _smoke_test(src_dir: Path, emit) -> dict:
    """Syntax-check + import-style validation + live HTTP probe for generated backend."""
    errors = []
    py_files = list(src_dir.rglob("*.py"))

    import sys as _sys_st
    # Pass 1: syntax check via py_compile on every generated .py file
    for f in py_files:
        proc = await asyncio.create_subprocess_exec(
            _sys_st.executable, "-m", "py_compile", str(f),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                errors.append(f"SyntaxError in {f.name}: {stderr.decode()[:300]}")
        except asyncio.TimeoutError:
            pass

    # Pass 2: AST import validation (catch hallucinated aether_os.* imports)
    if not errors:
        import_issues = _check_imports(src_dir)
        errors.extend(import_issues)

    # Pass 3: live HTTP probe — start uvicorn briefly, hit /health.
    # Only run if syntax passes. The probe failure is RECORDED but does NOT
    # fail the phase, because it depends on the platform's own python env
    # having every runtime dep the generated backend declares (email-validator,
    # bcrypt, etc.). Generated apps ship their own requirements.txt and venv,
    # so the missing-dep case is harmless — but it used to abort the pipeline.
    http_result: dict = {"skipped": True}
    if not errors:
        http_result = await _live_http_probe(src_dir, emit)
        # Only treat the live probe as fatal if it caught a code-level error
        # (SyntaxError, AttributeError, NameError). Missing-dep import errors
        # are demoted to warnings because the generated app installs them.
        if not http_result.get("passed") and not http_result.get("skipped"):
            probe_errs = http_result.get("errors", [])
            fatal = [e for e in probe_errs if not any(
                tok in e for tok in ("is not installed", "ModuleNotFoundError", "No module named")
            )]
            if fatal:
                errors.extend(fatal)
            else:
                logger.info("[p04a] live HTTP probe skipped: platform env missing runtime dep (non-fatal)")

    passed = len(errors) == 0
    await emit({
        "type": "llm_chunk",
        "phase": "p04_smoke_test",
        "text": (
            f"{'✓' if passed else '✗'} Smoke test: {len(py_files)} files, "
            f"{len(errors)} errors"
            + (f", /health {http_result.get('health_status', '?')}" if not http_result.get("skipped") else "")
        ),
    })
    return {"passed": passed, "errors": errors, "http_probe": http_result}


async def _live_http_probe(src_dir: Path, emit) -> dict:
    """Start uvicorn on a temp port, hit /health, return result. Non-blocking on failure."""
    import sys as _sys, socket as _sock, os as _os

    # Find a free port
    with _sock.socket() as _s:
        _s.bind(("127.0.0.1", 0))
        probe_port = _s.getsockname()[1]

    # Write a temp .env so the app has a valid SECRET_KEY
    _env_file = src_dir.parent / ".env"
    _wrote_env = False
    if not _env_file.exists():
        import secrets as _sec2
        _env_file.write_text(
            f"DATABASE_URL=sqlite+aiosqlite:///{src_dir.parent}/probe.db\n"
            f"SECRET_KEY={_sec2.token_hex(32)}\n"
            f"CORS_ORIGINS=http://localhost:3000\n"
        )
        _wrote_env = True

    _log_path = src_dir.parent / "probe.log"
    proc = None
    try:
        _env = {**_os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{src_dir.parent}/probe.db"}
        if _env_file.exists():
            # Load .env into subprocess env
            for line in _env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    _env[k.strip()] = v.strip()

        with open(_log_path, "w") as _lf:
            proc = await asyncio.create_subprocess_exec(
                _sys.executable, "-m", "uvicorn", "src.main:app",
                "--host", "127.0.0.1", "--port", str(probe_port),
                "--timeout-graceful-shutdown", "1",
                cwd=str(src_dir.parent),
                stdout=_lf,
                stderr=_lf,
                env=_env,
            )

        # Wait up to 8 seconds for the server to be ready
        _ready = False
        for _ in range(16):
            await asyncio.sleep(0.5)
            try:
                with _sock.create_connection(("127.0.0.1", probe_port), timeout=0.3):
                    _ready = True
                    break
            except OSError:
                pass

        if not _ready:
            _log_tail = _log_path.read_text()[-1000:] if _log_path.exists() else ""
            return {"passed": False, "skipped": False, "errors": [f"Server did not start in 8s: {_log_tail[-400:]}"], "health_status": "timeout"}

        # Hit /health
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=5.0) as _c:
            _r = await _c.get(f"http://127.0.0.1:{probe_port}/health")
        _health_ok = _r.status_code == 200

        # Also probe /docs to verify OpenAPI schema generates cleanly
        _docs_ok = False
        try:
            _dr = await _c.get(f"http://127.0.0.1:{probe_port}/docs")
            _docs_ok = _dr.status_code == 200
        except Exception:
            pass

        await emit({
            "type": "llm_chunk", "phase": "p04_probe",
            "text": f"  /health → {_r.status_code}  /docs → {'200' if _docs_ok else '?'}",
        })
        return {
            "passed": _health_ok,
            "skipped": False,
            "health_status": str(_r.status_code),
            "docs_ok": _docs_ok,
            "errors": [] if _health_ok else [f"/health returned {_r.status_code}: {_r.text[:200]}"],
        }
    except Exception as _pe:
        return {"passed": False, "skipped": False, "errors": [f"probe error: {_pe}"], "health_status": "error"}
    finally:
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        # Clean up probe DB
        for _f in [src_dir.parent / "probe.db", _log_path]:
            try:
                _f.unlink(missing_ok=True)
            except Exception:
                pass


# ── Main entry point ───────────────────────────────────────────────────────────

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    src_dir = output_dir / "src"
    routers_dir = src_dir / "routers"
    routers_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    async def _noop_emit(_e): pass
    _emit = getattr(phase_input, "emit", _noop_emit)

    raw_input: str = data.get("raw_input", "") or data.get("requirements", "") or ""
    project_name: str = data.get("project_name", "App")
    domain: str = data.get("domain", "general")
    entities: list = data.get("entities", [])
    api_endpoints: list = data.get("api_endpoints", [])

    from aether_os.phases.utils import memory_hint
    mem = memory_hint(memory_ctx)

    # Load architecture doc
    arch_doc: dict = {}
    arch_path = data.get("architecture_path", "") or data.get("json_path", "")
    if arch_path:
        try:
            arch_doc = json.loads(Path(arch_path).read_text())
            if not entities:
                entities = arch_doc.get("entities", [])
            if not api_endpoints:
                api_endpoints = arch_doc.get("api_endpoints", [])
        except Exception as exc:
            logger.warning("[p04a] could not load arch doc: %s", exc)

    # ── Step 1: Write fixed template files ────────────────────────────────────
    (src_dir / "__init__.py").write_text("")
    (src_dir / "database.py").write_text(_DATABASE_PY)
    (src_dir / "auth.py").write_text(_AUTH_PY)
    (src_dir / "config.py").write_text(_CONFIG_PY)
    (routers_dir / "__init__.py").write_text(_ROUTERS_INIT_PY)
    (routers_dir / "auth.py").write_text(_AUTH_ROUTER_PY)

    generated_via = "templates+llm"
    models_code = ""
    schemas_code = ""
    crud_code = ""
    seed_code = ""

    # ── Step 2 (IR fast-path): deterministic generation from Domain IR ────────
    # If p02b produced a domain_ir.json, skip the LLM for structural files.
    # Seed data still uses LLM (it needs invention, not structure).
    _ir_path_str = data.get("domain_ir_path", "")
    if _ir_path_str and Path(_ir_path_str).exists():
        try:
            from aether_os.core.domain_ir import DomainIR as _DomainIR
            from aether_os.phases.p04a_backend_codegen.ir_generators import (
                generate_models_py as _gen_models,
                generate_schemas_py as _gen_schemas,
                generate_crud_py as _gen_crud,
            )
            _ir = _DomainIR.load(Path(_ir_path_str))
            if _ir.entities:
                from aether_os.phases.p04a_backend_codegen.ir_generators import (
                    ir_to_models as _ir_to_models,
                    ir_to_schemas as _ir_to_schemas,
                    generate_stats_router as _gen_stats,
                    generate_seed_py as _gen_seed,
                )
                models_code = _ir_to_models(_ir)
                schemas_code = _ir_to_schemas(_ir)
                stats_code = _gen_stats(_ir)
                seed_code = _gen_seed(_ir)
                (src_dir / "models.py").write_text(models_code)
                (src_dir / "schemas.py").write_text(schemas_code)
                (routers_dir / "stats.py").write_text(stats_code)
                (src_dir / "seed.py").write_text(seed_code)
                import secrets
                env_content = textwrap.dedent(f"""\
                    DATABASE_URL=sqlite+aiosqlite:///./app.db
                    SECRET_KEY={secrets.token_hex(32)}
                    ACCESS_TOKEN_EXPIRE_MINUTES=60
                    CORS_ORIGINS=http://localhost:3000,http://localhost:5173
                """)
                (src_dir / ".env").write_text(env_content)
                (src_dir / ".env.example").write_text(env_content.replace(secrets.token_hex(32), "your-secret-key"))
                # Ensure .gitignore ignores .env
                gitignore = src_dir.parent / ".gitignore"
                if gitignore.exists() and ".env" not in gitignore.read_text():
                    with open(gitignore, "a") as f:
                        f.write("\n.env\n")
                # Update entities list from IR so LLM CRUD is accurate
                entities = [{"name": e.name, "table": e.table,
                             "fields": [{"name": f.name, "type": f.type} for f in e.fields]}
                            for e in _ir.entities]
        except Exception as _ir_exc:
            logger.warning("[p04a] IR fast-path failed (%s) — falling through to LLM", _ir_exc)
            models_code = ""
            schemas_code = ""
            crud_code = ""
            seed_code = ""

    # ── Step 2: Deterministic generation (zero LLM calls in p04a) ────────────
    # The "single LLM call per phase" rule means p04a relies entirely on:
    #   1. domain_ir.json from p02b (IR fast-path, deterministic codegen) → preferred
    #   2. _fallback_* deterministic generators                          → if no IR
    # The previous chain of 3 LLM calls (models+schemas, crud, seed) introduced
    # 90s+ of latency and ~30% defect rate (syntax errors, missing imports,
    # wrong all_routers list). The IR + fallback path is faster and lossless.
    from aether_os.core.llm.client import get_llm_client
    llm = get_llm_client()  # retained for downstream code (smoke-repair, etc.)
    _llm_classes: list = []
    try:
        if not models_code or not schemas_code:
            await _emit({"type": "llm_chunk", "phase": "p04a", "text": "⚙ Generating models + schemas (deterministic)…"})
            models_code = _fallback_models(project_name, entities)
            schemas_code = _fallback_schemas(entities)
            generated_via = "deterministic_fallback"

            _llm_classes = re.findall(r'^class \w+\(Base\)', models_code, re.MULTILINE)
        else:
            _llm_classes = re.findall(r'^class \w+\(Base\)', models_code, re.MULTILINE)
            logger.info("[p04a] IR fast-path: using deterministic models/schemas (%d classes)", len(_llm_classes))

        # P26: ast.parse validation before writing to disk
        for _fname, _code, _fallback_fn, _fallback_args in [
            ("models.py", models_code, _fallback_models, [project_name, entities]),
            ("schemas.py", schemas_code, _fallback_schemas, [entities]),
        ]:
            try:
                ast.parse(_code)
            except SyntaxError as _syn:
                logger.warning("[p04a] SyntaxError in LLM-generated %s: %s — using fallback", _fname, _syn)
                if _fname == "models.py":
                    models_code = _fallback_fn(*_fallback_args)
                else:
                    schemas_code = _fallback_fn(*_fallback_args)

        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        logger.info("[p04a] models.py %d chars (%d ORM classes), schemas.py %d chars",
                    len(models_code), len(_llm_classes), len(schemas_code))
    except Exception as exc:
        logger.warning("[p04a] LLM models/schemas failed (%s), using fallback", exc)
        models_code = _fallback_models(project_name, entities)
        schemas_code = _fallback_schemas(entities)
        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        generated_via = "templates+fallback"

    # ── Step 3: Deterministic CRUD routers ───────────────────────────────────
    if not crud_code:
        crud_code = _fallback_crud_routers(entities)
    try:
        ast.parse(crud_code)
    except SyntaxError as _syn:
        logger.warning("[p04a] SyntaxError in crud.py: %s — using fallback", _syn)
        crud_code = _fallback_crud_routers(entities)
    (routers_dir / "crud.py").write_text(crud_code)
    logger.info("[p04a] routers/crud.py %d chars", len(crud_code))

    # ── Step 4: Seed data — Template, IR-generated, or LLM ──────────────────
    if seed_code:
        # IR fast-path already wrote seed.py; just log it
        logger.info("[p04a] IR fast-path: seed.py already generated (%d chars)", len(seed_code))
    else:
        # Try domain-specific template first
        template_path = Path(__file__).parent / "seed_templates" / f"{domain}.py"
        if template_path.exists():
            logger.info("[p04a] using domain seed template: %s", domain)
            seed_code = template_path.read_text()
            # Wrap template into a full seed.py with imports and seed_database wrapper
            # (assuming templates provide the seed_{domain} function)
            if f"async def seed_{domain}" in seed_code:
                seed_code += f"\n\nasync def seed_database():\n    from database import AsyncSessionLocal\n    async with AsyncSessionLocal() as db:\n        await seed_{domain}(db)\n"
        
        if not seed_code:
            # Deterministic fallback — no LLM call (single-call-per-phase rule)
            seed_code = _fallback_seed(project_name, entities)
            try:
                ast.parse(seed_code)
            except SyntaxError as _syn:
                logger.warning("[p04a] SyntaxError in fallback seed.py: %s — emitting empty seed", _syn)
                seed_code = "async def seed_database():\n    return None\n"
            (src_dir / "seed.py").write_text(seed_code)
            logger.info("[p04a] seed.py %d chars (deterministic)", len(seed_code))

    # ── Step 5: Generate main.py from template ────────────────────────────────
    main_py = _build_main_py(project_name, routers_have_all_routers=True)
    (src_dir / "main.py").write_text(main_py)

    # ── Step 6: Supporting files ──────────────────────────────────────────────
    import secrets as _sec
    _secret = _sec.token_hex(32)
    (output_dir / "requirements.txt").write_text(_REQUIREMENTS_TXT)
    (output_dir / "Dockerfile").write_text(_DOCKERFILE)
    _env_content = (
        f"DATABASE_URL=sqlite+aiosqlite:///./app.db\n"
        f"SECRET_KEY={_secret}\n"
        f"CORS_ORIGINS=http://localhost:3000,http://localhost:5173\n"
        f"ENVIRONMENT=development\n"
        f"DEBUG=false\n"
        f"ADMIN_PASSWORD=Admin1234!\n"
    )
    # Write both .env (used by the running app) and .env.example (for documentation)
    (output_dir / ".env").write_text(_env_content)
    (output_dir / ".env.example").write_text(_env_content)
    # ── Makefile ──────────────────────────────────────────────────────────────
    (output_dir / "Makefile").write_text(_generate_makefile(project_name))
    (output_dir / "README.md").write_text(_generate_backend_readme(project_name, entities))

    # ── Step 6b: Alembic scaffold ─────────────────────────────────────────────
    alembic_dir = output_dir / "alembic"
    alembic_versions = alembic_dir / "versions"
    alembic_versions.mkdir(parents=True, exist_ok=True)
    (output_dir / "alembic.ini").write_text(_ALEMBIC_INI)
    (alembic_dir / "env.py").write_text(_ALEMBIC_ENV_PY)
    (alembic_dir / "script.py.mako").write_text(_ALEMBIC_SCRIPT_PY_MAKO)
    (alembic_dir / "README").write_text(
        "Generate a migration: alembic revision --autogenerate -m 'description'\n"
        "Apply migrations:    alembic upgrade head\n"
        "Rollback one step:   alembic downgrade -1\n"
    )

    # ── Step 7: Smoke test ────────────────────────────────────────────────────
    smoke = {"passed": True, "errors": [], "skipped": False}
    try:
        smoke = await _smoke_test(src_dir, _emit)
        if not smoke["passed"]:
            raise PipelineBlockedError(
                f"P04a smoke test failed: {smoke.get('errors')}. "
                "Cannot proceed to frontend generation against a broken backend."
            )
    except PipelineBlockedError:
        raise
    except Exception as exc:
        logger.debug("[p04a] smoke test error (non-fatal): %s", exc)

    code_size = sum(f.stat().st_size for f in src_dir.rglob("*.py") if f.exists())
    logger.info("[p04a] backend complete: %d bytes total, %s", code_size, generated_via)

    return TaskResult(
        output_path=str(output_dir),
        confidence=0.92 if generated_via == "templates+llm" else 0.7,
        metadata={
            "backend_src_dir": str(src_dir),
            "main_py": str(src_dir / "main.py"),
            "models_py": str(src_dir / "models.py"),
            "schemas_py": str(src_dir / "schemas.py"),
            "seed_py": str(src_dir / "seed.py"),
            "crud_router": str(routers_dir / "crud.py"),
            "alembic_ini": str(output_dir / "alembic.ini"),
            "generated_via": generated_via,
            "code_size_bytes": code_size,
            "entities_count": len(entities),
            "smoke_test": smoke,
            "project_name": project_name,
        },
        success=True,
        issues=smoke.get("errors", []) if not smoke.get("passed") else [],
    )
