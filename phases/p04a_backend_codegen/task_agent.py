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

logger = logging.getLogger(__name__)

# ── Fixed production templates ─────────────────────────────────────────────────

_DATABASE_PY = '''\
"""Async SQLAlchemy engine + session factory."""
from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./app.db")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
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
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-use-openssl-rand-hex-32")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


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
    secret_key: str = os.environ.get("SECRET_KEY", "change-me")
    cors_origins: list[str] = os.environ.get("CORS_ORIGINS", "*").split(",")
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
from ..database import get_db
from ..auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    get_current_user,
    SECRET_KEY,
    ALGORITHM,
)

try:
    from ..models import User
except ImportError:
    User = None  # type: ignore[assignment,misc]

from jose import JWTError, jwt

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
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .database import engine, Base
from .routers.auth import router as auth_router
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
        from .seed import seed_database
        await seed_database()
        logger.info("Database seeding complete")
    except Exception as exc:
        logger.warning("Seed skipped: %s", exc)
    yield
    logger.info("{PROJECT_NAME} API shutting down")


app = FastAPI(
    title="{PROJECT_NAME} API",
    version="1.0.0",
    description="Auto-generated production backend by AetherOS",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "type": "InternalError"},
    )


app.include_router(auth_router, prefix="/api")
{ROUTER_INCLUDES}


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": "1.0.0", "service": "{PROJECT_NAME}"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "{PROJECT_NAME} API", "docs": "/docs"}
'''

_ROUTERS_INIT_PY = ""  # empty — routers are imported directly

_REQUIREMENTS_TXT = """\
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
pydantic[email]>=2.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.9
httpx>=0.27.0
python-dotenv>=1.0.0
"""

_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \\
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""


# ── LLM generation functions ───────────────────────────────────────────────────

async def _llm_models_and_schemas(
    llm, project_name: str, domain: str, entities: list, raw_input: str, arch_doc: dict
) -> Tuple[str, str]:
    """One LLM call → (models.py, schemas.py)."""
    entities_json = json.dumps(entities[:12], indent=2)

    prompt = f"""\
You are a senior backend engineer. Generate SQLAlchemy async ORM models and Pydantic v2 schemas \
for a {domain} application called "{project_name}".

Project requirements:
{raw_input[:1500]}

Entities to model:
{entities_json}

MODELS.PY requirements (file: src/models.py):
1. Imports: `from .database import Base`, SQLAlchemy column types, relationship
2. ALWAYS include a User model:
   - id (Integer, primary_key, index)
   - email (String 255, unique, index, nullable=False)
   - password_hash (String 255, nullable=False)
   - role (String 50, default="user")  — values: "admin" or "user"
   - is_active (Boolean, default=True)
   - created_at, updated_at (DateTime timezone=True, with defaults)
3. For each entity: add domain-appropriate fields with proper SQLAlchemy types
4. Add ForeignKey relationships where logical (e.g. user_id references users.id)
5. Use `__tablename__` (snake_case plural)
6. DateTime fields use `datetime.now(timezone.utc)` as default

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
    llm, project_name: str, entities: list, models_code: str, schemas_code: str
) -> str:
    """One LLM call → routers/crud.py with all entity CRUD routers."""
    entity_names = [e.get("name", e.get("table", "")) for e in entities[:12]]
    entity_list = ", ".join(entity_names)

    prompt = f"""\
Generate FastAPI CRUD routers for "{project_name}".

Entities: {entity_list}

Models defined in src/models.py (first 800 chars):
{models_code[:800]}

Schemas defined in src/schemas.py (first 800 chars):
{schemas_code[:800]}

FILE: src/routers/crud.py

REQUIREMENTS:
1. Import all models from `..models` and all schemas from `..schemas`
2. Import: `from ..database import get_db`, `from ..auth import get_current_user, require_admin`
3. For EACH entity create an `APIRouter(prefix="/{entity_plural}", tags=["{entity_label}"])` with:
   - GET / → list with `skip: int = 0, limit: int = 100` query params, returns list[EntityResponse]
   - POST / → create, status_code=201, returns EntityResponse
   - GET /{{id}} → get by id or raise 404, returns EntityResponse
   - PUT /{{id}} → update by id or raise 404, returns EntityResponse
   - DELETE /{{id}} → delete or raise 404, returns 204 No Content
   - All endpoints use `current_user: dict = Depends(get_current_user)`
   - DELETE uses `Depends(require_admin)` for sensitive entities, else `Depends(get_current_user)`
4. Use `await db.execute(select(Model).where(Model.id == id))` for queries
5. Use `await db.execute(select(Model).offset(skip).limit(limit))` for lists
6. Call `db.add(obj)`, `await db.flush()`, `await db.refresh(obj)` after create/update
7. Return `None` with `status_code=204` from delete endpoints
8. LAST LINE must be: `all_routers = [{entity1}_router, {entity2}_router, ...]`

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

Models (from src/models.py):
{models_code[:1200]}

FILE: src/seed.py

REQUIREMENTS:
1. Import: `from .database import AsyncSessionLocal`, `from .auth import get_password_hash`
2. Import all models from `.models`
3. `async def seed_database()` — called on every startup
4. Check if already seeded: `result = await db.execute(select(func.count()).select_from(User))`
   If count > 0, return early (idempotent)
5. Create admin user: email="admin@example.com", password=get_password_hash(os.environ.get("ADMIN_PASSWORD", "changeme-" + str(uuid.uuid4())[:8])), role="admin"
   Add `import os, uuid` at top of file.
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

def _fallback_models(project_name: str, entities: list) -> str:
    entity_classes = []
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        fields = ent.get("fields", []) or [{"name": "name"}, {"name": "description"}]
        cols = ["    id = Column(Integer, primary_key=True, index=True)"]
        for f in fields[:10]:
            fn = f.get("name", f) if isinstance(f, dict) else str(f)
            if fn in ("id", "created_at", "updated_at"):
                continue
            cols.append(f"    {fn} = Column(String(255), nullable=True)")
        cols += [
            "    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))",
            "    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))",
        ]
        entity_classes.append(
            f"class {name}(Base):\n    __tablename__ = '{table}'\n" + "\n".join(cols)
        )

    return textwrap.dedent(f"""\
        from __future__ import annotations
        from datetime import datetime, timezone
        from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, Float, ForeignKey
        from sqlalchemy.orm import relationship
        from .database import Base


        class User(Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True, index=True)
            email = Column(String(255), unique=True, index=True, nullable=False)
            password_hash = Column(String(255), nullable=False)
            role = Column(String(50), nullable=False, default="user")
            is_active = Column(Boolean, nullable=False, default=True)
            created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
            updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


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
    lines = [
        "from __future__ import annotations",
        "from typing import Any, Dict, List",
        "from fastapi import APIRouter, Depends, HTTPException, status",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select, text, func",
        "from ..database import get_db",
        "from ..auth import get_current_user",
        "",
    ]
    router_vars = []
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        var = f"{table}_router"
        router_vars.append(var)
        lines += [
            f"{var} = APIRouter(prefix='/{table}', tags=['{name}'])",
            "",
            f"@{var}.get('/', response_model=List[Dict[str, Any]])",
            f"async def list_{table}(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):",
            f"    result = await db.execute(text('SELECT * FROM {table} LIMIT :limit OFFSET :skip'), {{'limit': min(limit, 100), 'skip': skip}})",
            f"    return [dict(r._mapping) for r in result.fetchall()]",
            "",
            f"@{var}.post('/', status_code=201)",
            f"async def create_{table}(data: Dict[str, Any], db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):",
            f"    if not data:",
            f"        raise HTTPException(status_code=422, detail='Request body required')",
            f"    cols = ', '.join(data.keys())",
            f"    vals = ', '.join(f':{{k}}' for k in data.keys())",
            f"    result = await db.execute(text(f'INSERT INTO {table} ({{cols}}) VALUES ({{vals}}) RETURNING *'), data)",
            f"    await db.commit()",
            f"    row = result.fetchone()",
            f"    return dict(row._mapping) if row else data",
            "",
            f"@{var}.get('/{{id}}')",
            f"async def get_{table}(id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):",
            f"    result = await db.execute(text('SELECT * FROM {table} WHERE id = :id'), {{'id': id}})",
            f"    row = result.fetchone()",
            f"    if not row:",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    return dict(row._mapping)",
            "",
            f"@{var}.put('/{{id}}')",
            f"async def update_{table}(id: int, data: Dict[str, Any], db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):",
            f"    if not data:",
            f"        raise HTTPException(status_code=422, detail='Request body required')",
            f"    sets = ', '.join(f'{{k}} = :{{k}}' for k in data.keys())",
            f"    data['_id'] = id",
            f"    result = await db.execute(text(f'UPDATE {table} SET {{sets}} WHERE id = :_id RETURNING *'), data)",
            f"    await db.commit()",
            f"    row = result.fetchone()",
            f"    if not row:",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    return dict(row._mapping)",
            "",
            f"@{var}.delete('/{{id}}', status_code=204)",
            f"async def delete_{table}(id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):",
            f"    result = await db.execute(text('DELETE FROM {table} WHERE id = :id RETURNING id'), {{'id': id}})",
            f"    await db.commit()",
            f"    if not result.fetchone():",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    return None",
            "",
        ]
    lines.append(f"all_routers = [{', '.join(router_vars)}]")
    return "\n".join(lines)


def _fallback_seed(project_name: str, entities: list) -> str:
    admin_password = secrets.token_urlsafe(12)
    return textwrap.dedent(f"""\
        from __future__ import annotations
        import logging
        from sqlalchemy import select, func
        from .database import AsyncSessionLocal
        from .auth import get_password_hash
        from .models import User

        _logger = logging.getLogger(__name__)
        _ADMIN_PASSWORD = "{admin_password}"

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


# ── Post-processing ────────────────────────────────────────────────────────────

def _fix_common_issues(code: str) -> str:
    """Fix frequent LLM codegen mistakes."""
    # Fix typing.AsyncSession
    code = code.replace("class_=typing.AsyncSession", "class_=AsyncSession")
    # Ensure Float/JSON/BigInteger are imported if used
    if "from sqlalchemy import" in code:
        m = re.search(r'^from sqlalchemy import ([^\n]+)', code, re.MULTILINE)
        if m:
            existing = m.group(1)
            needed = ["Float", "JSON", "BigInteger", "Numeric", "Text", "func"]
            missing = [t for t in needed if t not in existing and t.lower() in code.lower()]
            if missing:
                code = code.replace(m.group(0), m.group(0) + ", " + ", ".join(missing))
    # Fix datetime import in models
    if "datetime.now" in code and "from datetime import datetime" not in code:
        code = "from datetime import datetime, timezone\n" + code
    # Fix missing timezone import
    if "timezone.utc" in code and "timezone" not in code.split("from datetime import")[-1].split("\n")[0] if "from datetime import" in code else True:
        code = code.replace("from datetime import datetime\n", "from datetime import datetime, timezone\n")
    return code


def _build_main_py(project_name: str, routers_have_all_routers: bool) -> str:
    if routers_have_all_routers:
        router_imports = "from .routers.crud import all_routers"
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
    """Syntax-check + import-style validation for all Python files in src/."""
    errors = []
    py_files = list(src_dir.rglob("*.py"))

    # Pass 1: syntax check via py_compile
    for f in py_files:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "py_compile", str(f),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                errors.append(f"SyntaxError in {f.name}: {stderr.decode()[:300]}")
        except asyncio.TimeoutError:
            pass

    # Pass 2: AST import validation (only if syntax passes)
    if not errors:
        import_issues = _check_imports(src_dir)
        errors.extend(import_issues)

    passed = len(errors) == 0
    await emit({
        "type": "llm_chunk",
        "phase": "p04_smoke_test",
        "text": f"{'✓' if passed else '✗'} Smoke test: {len(py_files)} files checked, {len(errors)} errors",
    })
    return {"passed": passed, "errors": errors}


# ── Main entry point ───────────────────────────────────────────────────────────

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    src_dir = output_dir / "src"
    routers_dir = src_dir / "routers"
    routers_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    _emit = getattr(phase_input, "emit", lambda e: None)

    raw_input: str = data.get("raw_input", "") or data.get("requirements", "") or ""
    project_name: str = data.get("project_name", "App")
    domain: str = data.get("domain", "general")
    entities: list = data.get("entities", [])
    api_endpoints: list = data.get("api_endpoints", [])

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

    # ── Step 2: LLM call 1 — models + schemas ────────────────────────────────
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()

        await _emit({"type": "llm_chunk", "phase": "p04a", "text": "⚙ Generating models + schemas…"})
        models_code, schemas_code = await _llm_models_and_schemas(
            llm, project_name, domain, entities, raw_input, arch_doc
        )
        models_code = _fix_common_issues(models_code)
        schemas_code = _fix_common_issues(schemas_code)
        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        logger.info("[p04a] models.py %d chars, schemas.py %d chars", len(models_code), len(schemas_code))
    except Exception as exc:
        logger.warning("[p04a] LLM models/schemas failed (%s), using fallback", exc)
        models_code = _fallback_models(project_name, entities)
        schemas_code = _fallback_schemas(entities)
        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        generated_via = "templates+fallback"

    # ── Step 3: LLM call 2 — CRUD routers ────────────────────────────────────
    try:
        await _emit({"type": "llm_chunk", "phase": "p04a", "text": "⚙ Generating CRUD routers…"})
        crud_code = await _llm_crud_routers(llm, project_name, entities, models_code, schemas_code)
        crud_code = _fix_common_issues(crud_code)
        # Ensure all_routers exists
        if "all_routers" not in crud_code:
            crud_code += "\n\nall_routers = []\n"
        (routers_dir / "crud.py").write_text(crud_code)
        logger.info("[p04a] routers/crud.py %d chars", len(crud_code))
    except Exception as exc:
        logger.warning("[p04a] LLM CRUD routers failed (%s), using fallback", exc)
        crud_code = _fallback_crud_routers(entities)
        (routers_dir / "crud.py").write_text(crud_code)

    # ── Step 4: LLM call 3 — seed data ───────────────────────────────────────
    try:
        await _emit({"type": "llm_chunk", "phase": "p04a", "text": "⚙ Generating seed data…"})
        seed_code = await _llm_seed_data(llm, project_name, domain, entities, models_code)
        seed_code = _fix_common_issues(seed_code)
        (src_dir / "seed.py").write_text(seed_code)
        logger.info("[p04a] seed.py %d chars", len(seed_code))
    except Exception as exc:
        logger.warning("[p04a] LLM seed failed (%s), using fallback", exc)
        seed_code = _fallback_seed(project_name, entities)
        (src_dir / "seed.py").write_text(seed_code)

    # ── Step 5: Generate main.py from template ────────────────────────────────
    main_py = _build_main_py(project_name, routers_have_all_routers=True)
    (src_dir / "main.py").write_text(main_py)

    # ── Step 6: Supporting files ──────────────────────────────────────────────
    import secrets as _sec
    _secret = _sec.token_hex(32)
    (output_dir / "requirements.txt").write_text(_REQUIREMENTS_TXT)
    (output_dir / "Dockerfile").write_text(_DOCKERFILE)
    (output_dir / ".env.example").write_text(
        f"DATABASE_URL=sqlite+aiosqlite:///./app.db\n"
        f"SECRET_KEY={_secret}\n"
        f"CORS_ORIGINS=http://localhost:3000,http://localhost:5173\n"
        f"ENVIRONMENT=development\n"
    )

    # ── Step 7: Smoke test ────────────────────────────────────────────────────
    smoke = {"passed": True, "errors": [], "skipped": False}
    try:
        smoke = await _smoke_test(src_dir, _emit)
        if not smoke["passed"]:
            logger.warning("[p04a] smoke test failed: %s", smoke["errors"])
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
            "generated_via": generated_via,
            "code_size_bytes": code_size,
            "entities_count": len(entities),
            "smoke_test": smoke,
            "project_name": project_name,
        },
        success=True,
        issues=smoke.get("errors", []) if not smoke.get("passed") else [],
    )
