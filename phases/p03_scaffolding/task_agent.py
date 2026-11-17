"""P03 Task Agent — scaffold project with cookiecutter and local fallback."""
from __future__ import annotations
import asyncio
import ast
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.p03_scaffolding.validation import safe_project_name, validate_clone_url
from aether_os.core.llm.client import get_llm_client
from aether_os.core.context_helpers import record_decision

logger = logging.getLogger(__name__)


async def _write_python_file_validated(
    file_path: Path,
    code: str,
    description: str = "file",
    llm=None,
    max_retries: int = 2,
) -> None:
    """
    Problem 49 fix: Write a Python file after validating its syntax with ast.parse().
    If validation fails, retry the LLM with the syntax error message.
    If llm is None or retries exhausted, write the best available code anyway.
    """
    current_code = code
    for attempt in range(max_retries + 1):
        try:
            ast.parse(current_code)
            # Syntax is valid — write and return
            file_path.write_text(current_code)
            if attempt > 0:
                logger.info("p03: %s passed ast.parse() on attempt %d", description, attempt + 1)
            return
        except SyntaxError as exc:
            logger.warning(
                "p03: SyntaxError in generated %s (attempt %d/%d): %s",
                description, attempt + 1, max_retries + 1, exc,
            )
            if llm is None or attempt >= max_retries:
                logger.warning("p03: writing %s despite SyntaxError (no more retries)", description)
                file_path.write_text(current_code)
                return
            # Retry with correction prompt
            correction_prompt = (
                f"The following Python code for {description} has a SyntaxError:\n\n"
                f"Error: {exc}\n"
                f"  Line {exc.lineno}: {exc.text}\n\n"
                f"Here is the code:\n\n{current_code}\n\n"
                f"IMPORTANT RULES:\n"
                f"- The @asynccontextmanager decorator MUST be on the line IMMEDIATELY before "
                f"async def lifespan. Do NOT place any function calls between the decorator "
                f"and the function definition. setup_logging() must be called INSIDE the "
                f"lifespan function body.\n"
                f"- Return ONLY corrected, parseable Python. No explanation. No markdown fences."
            )
            try:
                fixed = await llm.call(correction_prompt, task_type="code_generation", max_tokens=4096)
                fixed = fixed.strip()
                # Strip markdown fences if present
                if fixed.startswith("```"):
                    lines = fixed.splitlines()
                    fixed = "\n".join(ln for ln in lines if not ln.startswith("```"))
                current_code = fixed
            except Exception as llm_exc:
                logger.warning("p03: LLM correction call failed: %s", llm_exc)
                file_path.write_text(current_code)
                return


def _write_devcontainer(project_dir: Path, project_name: str) -> None:
    """Write .devcontainer/devcontainer.json for one-click VS Code / Codespaces."""
    dc_dir = project_dir / ".devcontainer"
    dc_dir.mkdir(exist_ok=True)

    devcontainer = {
        "name": project_name,
        "image": "mcr.microsoft.com/devcontainers/python:3.11",
        "features": {
            "ghcr.io/devcontainers/features/node:1": {"version": "20"},
            "ghcr.io/devcontainers/features/docker-in-docker:2": {}
        },
        "postCreateCommand": "pip install -r requirements.txt && echo 'Ready! Run: uvicorn src.main:app --reload'",
        "forwardPorts": [8000, 3000, 5432],
        "portsAttributes": {
            "8000": {"label": "API Server", "onAutoForward": "openBrowser"},
            "3000": {"label": "Frontend Dev Server", "onAutoForward": "openBrowser"}
        },
        "customizations": {
            "vscode": {
                "extensions": [
                    "ms-python.python",
                    "ms-python.vscode-pylance",
                    "esbenp.prettier-vscode",
                    "dbaeumer.vscode-eslint",
                    "bradlc.vscode-tailwindcss",
                    "ms-azuretools.vscode-docker"
                ],
                "settings": {
                    "python.defaultInterpreterPath": "/usr/local/bin/python",
                    "editor.formatOnSave": True,
                    "editor.defaultFormatter": "esbenp.prettier-vscode"
                }
            }
        }
    }

    (dc_dir / "devcontainer.json").write_text(json.dumps(devcontainer, indent=2))


def _write_scale_architecture(project_dir: Path) -> None:
    """Upgrade generated app with production-scale connection pooling + Redis cache.

    Writes / upgrades:
      src/services/cache_service.py  — async Redis cache with @cached decorator
    Also upgrades docker-compose.yml to add a Redis service.
    """
    services_dir = project_dir / "src" / "services"
    services_dir.mkdir(parents=True, exist_ok=True)

    cache_service_py = '''\
"""Async Redis cache service — generated by AetherOS."""
from __future__ import annotations
import hashlib
import json
import logging
import os
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis  # type: ignore[import]
    _REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False

_redis_client: Optional[Any] = None


async def get_redis():
    """Return a shared async Redis client, creating it on first call."""
    global _redis_client
    if not _REDIS_AVAILABLE:
        return None
    if _redis_client is None:
        url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            _redis_client = redis.from_url(url, decode_responses=True)
        except Exception as exc:
            logger.warning("Redis connection failed: %s", exc)
            return None
    return _redis_client


def cached(ttl: int = 300):
    """Decorator: cache the return value of an async function in Redis.

    Falls back gracefully when Redis is unavailable — the function is called normally.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            r = await get_redis()
            if r is None:
                return await func(*args, **kwargs)
            key = f"cache:{func.__module__}.{func.__name__}:{hashlib.md5(str(args).encode()).hexdigest()}"
            try:
                cached_val = await r.get(key)
                if cached_val is not None:
                    return json.loads(cached_val)
            except Exception as exc:
                logger.debug("Cache GET failed: %s", exc)
            result = await func(*args, **kwargs)
            try:
                await r.set(key, json.dumps(result, default=str), ex=ttl)
            except Exception as exc:
                logger.debug("Cache SET failed: %s", exc)
            return result
        return wrapper
    return decorator


async def invalidate(pattern: str) -> int:
    """Delete all cache keys matching a glob pattern. Returns number deleted."""
    r = await get_redis()
    if r is None:
        return 0
    try:
        keys = await r.keys(pattern)
        if keys:
            return await r.delete(*keys)
    except Exception as exc:
        logger.warning("Cache invalidate failed: %s", exc)
    return 0
'''
    (services_dir / "cache_service.py").write_text(cache_service_py)
    init_py = services_dir / "__init__.py"
    if not init_py.exists():
        init_py.write_text("")

    # Upgrade docker-compose.yml to add Redis service if not already present
    compose_path = project_dir / "docker-compose.yml"
    if compose_path.exists():
        compose_text = compose_path.read_text()
        if "redis:" not in compose_text:
            # Append Redis service before the volumes block
            redis_service = """\

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
"""
            if "volumes:" in compose_text:
                compose_text = compose_text.replace(
                    "\nvolumes:",
                    redis_service + "\nvolumes:",
                    1,
                )
                # Add redis_data volume
                compose_text = compose_text.rstrip() + "\n  redis_data:\n"
            else:
                compose_text += redis_service + "\nvolumes:\n  redis_data:\n"
            compose_path.write_text(compose_text)
            logger.info("p03: Redis service added to docker-compose.yml")

    logger.info("p03: scale architecture written to %s", project_dir)


def create_minimal_scaffold(
        project_name: str,
        tech_stack: dict,
        output_dir: Path,
        domain: str = "general") -> Path:
    """Create project scaffold without network access."""
    
    backend = tech_stack.get("backend", "fastapi").lower()
    from aether_os.core.domain_engine import get_domain_profile
    profile = get_domain_profile(domain)
    
    project_dir = output_dir / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Create standard structure
    dirs = [
        "src", "tests", "docs",
        "src/api", "src/models", 
        "src/services"
    ]
    
    # Domain specific dirs
    if domain == "industrial":
        dirs += ["src/protocols", "src/alarms"]
    elif domain == "fintech":
        dirs += ["src/ledger", "src/reconciliation"]
    elif domain == "saas_multitenant":
        dirs += ["src/tenants", "src/webhooks"]

    for d in dirs:
        (project_dir / d).mkdir(parents=True, exist_ok=True)
        (project_dir / d / "__init__.py").touch()
    
    # Create main.py based on backend
    # Problem 49 fix: use correct lifespan pattern — @asynccontextmanager MUST be
    # immediately before async def lifespan, with setup_logging() INSIDE the function body.
    if "fastapi" in backend:
        main_content = f'''from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO)


# IMPORTANT: @asynccontextmanager must be on the line IMMEDIATELY before async def lifespan.
# Do NOT place any function calls between the decorator and the function definition.
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield


app = FastAPI(
    title="{project_name}",
    description="Generated {profile.name} Application",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {{"status": "healthy", "domain": "{domain}"}}
'''
    else:
        main_content = f'# {project_name}\n# Domain: {domain}\n'

    (project_dir / "src/main.py").write_text(main_content)
    # Also put a copy in project root for convenience
    (project_dir / "main.py").write_text(main_content)
    
    # Create requirements.txt
    reqs = ["fastapi", "uvicorn", "pydantic", "pytest", "python-jose", "passlib[bcrypt]"]
    db = tech_stack.get("database", "")
    if "postgres" in db.lower() or "timescale" in db.lower():
        reqs.extend(["sqlalchemy[asyncio]", "asyncpg", "alembic"])
    
    # Domain specific reqs
    if domain == "industrial":
        reqs += ["paho-mqtt", "asyncua"]
    elif domain == "fintech":
        reqs += ["redis", "cryptography"]
    elif domain == "saas_multitenant":
        reqs += ["stripe"]

    (project_dir / "requirements.txt").write_text("\n".join(sorted(set(reqs))))
    
    # Create .env.example
    import secrets as _sec
    _example_key = _sec.token_hex(32)
    (project_dir / ".env.example").write_text(
        "DATABASE_URL=postgresql://localhost/db\n"
        f"SECRET_KEY={_example_key}\n"
        "# Required by docker-compose.yml (it refuses to start without it). Choose your own value.\n"
        "POSTGRES_PASSWORD=\n")

    # Separate dev and prod env files
    _dev_key = _sec.token_hex(32)
    _prod_key = _sec.token_hex(32)
    (project_dir / ".env.dev").write_text(
        "DATABASE_URL=sqlite+aiosqlite:///./dev.db\n"
        f"SECRET_KEY={_dev_key}\n"
        "DEBUG=true\n"
        "CORS_ORIGINS=http://localhost:3000,http://localhost:5173\n"
    )
    (project_dir / ".env.prod").write_text(
        "# Production environment — fill all values before deploy\n"
        "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/appdb\n"
        f"SECRET_KEY={_prod_key}\n"
        "DEBUG=false\n"
        "CORS_ORIGINS=https://yourdomain.com\n"
        "ENVIRONMENT=production\n"
    )
    # .gitignore — never commit .env files with real secrets
    (project_dir / ".gitignore").write_text(
        ".env\n.env.prod\n.env.dev\n__pycache__/\n*.pyc\n.pytest_cache/\n"
        "node_modules/\ndist/\nbuild/\n*.db\n*.log\n"
    )

    # Create README.md
    _brand = os.environ.get("DEPLOYMENT_BRAND", "AetherOS Factory")
    (project_dir / "README.md").write_text(
        f"# {project_name}\n\n"
        f"Generated by {_brand}\n\n"
        f"## Setup\n\n"
        f"```bash\npip install -r requirements.txt\n```\n")
    
    # Initialize git
    import subprocess
    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)

    # Write .devcontainer/devcontainer.json
    _write_devcontainer(project_dir, project_name)

    # docker-compose with PostgreSQL (production-ready)
    (project_dir / "docker-compose.yml").write_text(f"""\
version: "3.9"
services:
  api:
    build: .
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://appuser:${{POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}}@db:5432/{project_name.lower()}
      SECRET_KEY: ${{SECRET_KEY}}
      CORS_ORIGINS: http://localhost:3000
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: appuser
      POSTGRES_PASSWORD: ${{POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}}
      POSTGRES_DB: {project_name.lower()}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U appuser"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped

volumes:
  pgdata:
""")

    return project_dir


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    arch = data.get("architecture_json", {})
    if isinstance(arch, str):
        try:
            arch = json.loads(arch)
        except Exception as e:
            logger.warning("p03: could not parse architecture_json: %s", e)
            arch = {}

    tech_stack = arch.get("tech_stack", {})
    backend = str(tech_stack.get("backend", "fastapi")).lower()
    project_name = safe_project_name(data.get("project_name", phase_input.project_id))
    domain = data.get("domain", "general")

    # ── GitHub repo fork: clone instead of generating from scratch ────────────
    github_url = data.get("github_url", "").strip()
    if github_url:
        try:
            validate_clone_url(github_url)
        except ValueError as exc:
            logger.warning("p03: github_url refused: %s", exc)
            return TaskResult(output_path=str(output_dir), confidence=0.0, success=False,
                              issues=[f"github_url refused: {exc}"])
        clone_dir = output_dir / project_name
        clone_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
                 "clone", "--depth=1", "--", github_url, str(clone_dir)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                files_created = list(clone_dir.rglob("*"))
                file_count = len([f for f in files_created if f.is_file()])
                logger.info("p03: cloned %s → %d files", github_url, file_count)
                return TaskResult(
                    output_path=str(clone_dir),
                    confidence=0.92,
                    metadata={"file_count": file_count, "backend": backend,
                              "github_url": github_url, "cloned": True},
                    issues=[],
                    success=True,
                )
            logger.warning("p03: git clone failed (rc=%d): %s", result.returncode, result.stderr[:200])
        except Exception as exc:
            logger.warning("p03: git clone error: %s — falling back to scaffold", exc)

    project_dir = create_minimal_scaffold(project_name, tech_stack, output_dir, domain=domain)

    # ── Scale architecture: upgraded database.py + cache_service.py ───────────
    try:
        _write_scale_architecture(project_dir)
    except Exception as _scale_exc:
        logger.warning("p03: scale architecture generation failed (non-fatal): %s", _scale_exc)

    # Problem 49 fix: validate all generated Python files with ast.parse(); retry LLM if invalid
    _syntax_errors: List[str] = []
    try:
        _llm = get_llm_client()
    except Exception as e:
        logger.warning("p03: could not get LLM client for syntax repair: %s", e)
        _llm = None

    for _py_file in project_dir.rglob("*.py"):
        _code = _py_file.read_text()
        try:
            ast.parse(_code)
        except SyntaxError as _exc:
            logger.warning("p03: SyntaxError in %s: %s — attempting single LLM correction", _py_file, _exc)
            # Single-call-per-phase rule: cap to ONE correction attempt per file.
            await _write_python_file_validated(
                _py_file, _code,
                description=str(_py_file.relative_to(project_dir)),
                llm=_llm,
                max_retries=1,
            )
            try:
                ast.parse(_py_file.read_text())
            except SyntaxError as _exc2:
                _syntax_errors.append(f"{_py_file.name}: {_exc2}")

    files_created = list(project_dir.rglob("*"))
    file_count = len([f for f in files_created if f.is_file()])

    issues = []
    if not project_dir.exists():
        issues.append("project directory not created")
    if file_count < 3:
        issues.append(f"only {file_count} files created (need >= 3)")
    if _syntax_errors:
        issues.extend([f"SyntaxError in {e}" for e in _syntax_errors])

    # Record scaffold pattern decision so downstream phases know the structure.
    # Infer pattern from architecture doc: microservices keyword → microservices,
    # otherwise monolith (default for generated apps).
    _arch_text_p03 = json.dumps(arch).lower() if arch else ""
    if "microservice" in _arch_text_p03:
        _scaffold_pattern = "microservices"
        _scaffold_reason = (
            "microservices keyword found in architecture.json; "
            "scaffold created with per-service directories"
        )
    else:
        _scaffold_pattern = "monolith"
        _scaffold_reason = (
            "default monolith scaffold: single FastAPI app under src/ "
            "with api/models/services subdirectories"
        )
    try:
        record_decision(
            data,
            key="scaffold_pattern",
            value=_scaffold_pattern,
            reason=_scaffold_reason,
            phase="p03",
        )
    except Exception as _rd_exc:
        logger.warning("p03: record_decision failed (non-fatal): %s", _rd_exc)

    return TaskResult(
        output_path=str(project_dir),
        confidence=0.9 if not issues else 0.4,
        metadata={
            "file_count": file_count,
            "backend": backend,
            "used_cookiecutter": False,
            "syntax_errors": _syntax_errors,
            "scaffold_pattern": _scaffold_pattern,
        },
        issues=issues,
        success=len([i for i in issues if "SyntaxError" not in i]) == 0,
    )
