"""A small, correct FastAPI + React project used by the rule-pack tests.

The clean project must produce zero findings (the shared negative case); each positive test overrides one file
with a single defect and expects exactly that rule to fire. Fake credentials are assembled at runtime so the
repository's own secret scan does not see a literal key.
"""
from pathlib import Path

from aether_os.core.rulepacks import generate_tokens, scan_project

FAKE_AWS = "AKIA" + "Q" * 16
FAKE_STRIPE_LIVE = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"
FAKE_HEX = "a8f9c2b1" + "7d3e4f60"
FAKE_HEX_SHORT = "9f8e7d" + "6c5b4a"
FAKE_WEBHOOK = "Zq8vR2xL" + "9mT4kP7w" + "N3bY6cH1"
FAKE_PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK\n-----END " + "RSA PRIVATE KEY-----\n"

MAIN = '''import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.routers import auth, tasks

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

app = FastAPI(title="Tasks")
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.include_router(auth.router, prefix="/api/auth")
app.include_router(tasks.router, prefix="/api/tasks")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready"}
'''

CONFIG = '''from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    DATABASE_URL: str
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    SEED_DEMO: bool = False


settings = Settings()
'''

DATABASE = '''from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''

MODELS = '''from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
'''

SECURITY = '''from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=30)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user
'''

AUTH_ROUTER = '''from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import create_access_token, verify_password

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, form: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.email).first()
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}
'''

TASKS_ROUTER = '''from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task, User
from app.security import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/")
def list_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Task).filter(Task.owner_id == user.id).all()


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == user.id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
'''

MIGRATION = '''"""initial schema"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.create_table("users", sa.Column("id", sa.Integer, primary_key=True))


def downgrade():
    op.drop_table("users")
'''

DOCKERFILE = '''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -r app
USER app
HEALTHCHECK CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
'''

COMPOSE = '''services:
  api:
    build: ./backend
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
'''

ENV_EXAMPLE = '''DATABASE_URL=postgresql://app:change-me@db:5432/app
SECRET_KEY=change-me-to-64-random-characters
JWT_ALGORITHM=HS256
LOG_LEVEL=INFO
CORS_ORIGINS=["http://localhost:5173"]
SEED_DEMO=false
POSTGRES_PASSWORD=change-me
VITE_API_URL=http://localhost:8000
'''

PAGE = '''import { useQuery } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { listTasks } from '../lib/api';

export default function TasksPage() {
  const { data: tasks, isLoading, isError, refetch } = useQuery({ queryKey: ['tasks'], queryFn: listTasks });
  if (isLoading) return <p className="p-4 text-muted-foreground">Loading tasks</p>;
  if (isError) return <button className="text-destructive" onClick={() => refetch()}>Could not load tasks. Retry</button>;
  if (!tasks || tasks.length === 0) return <p className="p-4">No tasks yet. Add your first task above.</p>;
  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="font-heading text-3xl">Tasks</h1>
      <img src="/team.webp" alt="The support team at work" width={640} height={320} />
      <label htmlFor="search">Search</label>
      <input id="search" className="border-input rounded-md px-3 py-2 focus-visible:ring-2 focus-visible:ring-ring" />
      <ul className="mt-4 space-y-2">
        {tasks.map((t) => (
          <li key={t.id} className="flex items-center justify-between rounded-lg bg-card p-4">
            {t.title}
            <button aria-label={`Delete ${t.title}`} className="text-destructive"><Trash2 className="h-4 w-4" /></button>
          </li>
        ))}
      </ul>
      <a href="https://status.tasks.app" target="_blank" rel="noopener noreferrer">Status</a>
    </main>
  );
}
'''

API = '''const API = import.meta.env.VITE_API_URL;

export async function listTasks() {
  const res = await fetch(`${API}/api/tasks/`, { credentials: 'include' });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}
'''

INDEX_HTML = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Tasks</title>
  </head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
'''

README = '''# Tasks

## Run locally

```
cp .env.example .env
docker compose up --build
```

## Deploy

Build the images and run them with docker compose on the server; set every variable from .env.example.
'''


def clean_files() -> dict[str, str]:
    return {
        "backend/app/__init__.py": "",
        "backend/app/main.py": MAIN,
        "backend/app/config.py": CONFIG,
        "backend/app/database.py": DATABASE,
        "backend/app/models.py": MODELS,
        "backend/app/security.py": SECURITY,
        "backend/app/routers/__init__.py": "",
        "backend/app/routers/auth.py": AUTH_ROUTER,
        "backend/app/routers/tasks.py": TASKS_ROUTER,
        "backend/alembic.ini": "[alembic]\nscript_location = alembic\n",
        "backend/alembic/env.py": "from alembic import context\n",
        "backend/alembic/versions/0001_init.py": MIGRATION,
        "backend/requirements.txt": "fastapi==0.115.0\nsqlalchemy==2.0.36\npasslib[argon2]==1.7.4\npyjwt==2.9.0\nslowapi==0.1.9\n",
        "backend/Dockerfile": DOCKERFILE,
        "docker-compose.yml": COMPOSE,
        ".env.example": ENV_EXAMPLE,
        ".gitignore": ".env\nnode_modules\n",
        ".github/workflows/ci.yml": "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        "README.md": README,
        "frontend/index.html": INDEX_HTML,
        "frontend/package.json": '{"dependencies": {"react": "^18.3.1", "@tanstack/react-query": "^5.59.0"}}',
        "frontend/src/index.css": generate_tokens("internal_tool", "Tasks", ["calm"]).to_css(),
        "frontend/src/pages/TasksPage.tsx": PAGE,
        "frontend/src/lib/api.ts": API,
    }


def write_project(root: Path, overrides: dict[str, str | None] | None = None) -> Path:
    files = clean_files()
    for k, v in (overrides or {}).items():
        if v is None:
            files.pop(k, None)
        else:
            files[k] = v
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def rule_ids(root: Path, overrides=None, packs=("design", "security", "prodready"), public_routes=None) -> list[str]:
    report = scan_project(write_project(root, overrides), public_routes=public_routes, packs=packs)
    return [f.rule_id for f in report.findings]


def findings(root: Path, overrides=None, packs=("design", "security", "prodready"), public_routes=None):
    return scan_project(write_project(root, overrides), public_routes=public_routes, packs=packs).findings
