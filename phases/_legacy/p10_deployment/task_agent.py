"""P10 Task Agent — generate Dockerfile, docker-compose, and Pulumi IaC."""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    arch_json = data.get("architecture_json", {})
    if isinstance(arch_json, str):
        try:
            arch_json = json.loads(arch_json)
        except Exception:
            arch_json = {}
    project_dir = Path(data.get("project_dir", str(output_dir / "project")))
    project_name = data.get("project_name", "app")
    project_slug = project_name.lower().replace(" ", "-")
    stack = arch_json.get("tech_stack", {})
    llm = get_llm_client()

    # Find the real main.py to determine correct module path
    main_py, app_module = _find_main_py(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Generate Dockerfile
    dockerfile_code = await llm.call(
        f"Write a production Dockerfile for a {stack.get('backend','FastAPI')} app.\n"
        f"Requirements:\n"
        f"- Multi-stage build (builder + runtime)\n"
        f"- Non-root user\n"
        f"- COPY requirements.txt and install deps before copying code\n"
        f"- HEALTHCHECK instruction\n"
        f"- Expose port 8000\n"
        f"- Use python:3.11-slim base image for Python apps\n"
        f"- CMD: uvicorn {app_module}:app --host 0.0.0.0 --port 8000 --workers 4",
        task_type="code_generation",
    )
    dockerfile_path = project_dir / "Dockerfile"
    dockerfile_path.write_text(_strip_fences(dockerfile_code))

    # Generate docker-compose.yml
    db = stack.get("database", "postgres").lower()
    cache = stack.get("cache", "redis").lower()
    compose = _generate_compose(project_slug, db, cache)
    compose_path = project_dir / "docker-compose.yml"
    compose_path.write_text(compose)

    # Generate Pulumi IaC
    infra_dir = output_dir / "infra"
    infra_dir.mkdir(exist_ok=True)
    cloud = _detect_cloud(arch_json)
    pulumi_code = await llm.call(
        f"Write a Pulumi Python IaC script (infra/__main__.py) for {cloud}.\n"
        f"Include: VPC, security groups, compute instance (t3.medium or equivalent),\n"
        f"managed database ({db}), load balancer, SSL cert, DNS record.\n"
        f"Use pulumi.export() for all resource URLs.\n"
        f"App name: {project_slug}",
        task_type="code_generation",
    )
    (infra_dir / "__main__.py").write_text(_strip_fences(pulumi_code))
    (infra_dir / "Pulumi.yaml").write_text(
        f"name: {project_slug}\nruntime: python\ndescription: {project_name} infrastructure\n"
    )

    # Build Docker image
    docker_built = False
    try:
        result = subprocess.run(
            ["docker", "build", "-t", project_slug, "."],
            cwd=str(project_dir), capture_output=True, text=True, timeout=180,
        )
        docker_built = result.returncode == 0
        if not docker_built:
            logger.warning("docker build failed: %s", result.stderr[:300])
    except Exception as e:
        logger.info("Docker not available: %s", e)

    # Start docker-compose for verification
    compose_ok = False
    try:
        result = subprocess.run(
            ["docker-compose", "up", "-d", "--build"],
            cwd=str(project_dir), capture_output=True, text=True, timeout=120,
        )
        compose_ok = result.returncode == 0
        if compose_ok:
            # Bring down after verification
            subprocess.run(["docker-compose", "down"], cwd=str(project_dir),
                           capture_output=True, timeout=30)
    except Exception as e:
        logger.info("docker-compose not available: %s", e)

    # Write deployment manifest
    manifest = {
        "project": project_slug,
        "docker_image": f"{project_slug}:latest",
        "dockerfile": str(dockerfile_path),
        "compose_file": str(compose_path),
        "infra_dir": str(infra_dir),
        "cloud": cloud,
        "docker_built": docker_built,
        "compose_ok": compose_ok,
        "urls": {"local": f"http://localhost:8000", "health": f"http://localhost:8000/health"},
    }
    manifest_path = output_dir / "deployment_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    issues = []
    if not dockerfile_path.exists():
        issues.append("Dockerfile not written")
    if not compose_path.exists():
        issues.append("docker-compose.yml not written")
    if not manifest_path.exists():
        issues.append("deployment_manifest.json not written")
    if not docker_built:
        issues.append("docker build failed or Docker not available")

    return TaskResult(
        output_path=str(output_dir),
        confidence=0.9 if docker_built else (0.7 if compose_path.exists() else 0.4),
        metadata=manifest,
        issues=issues,
        success=dockerfile_path.exists() and compose_path.exists() and manifest_path.exists(),
    )


def _generate_compose(slug: str, db: str, cache: str) -> str:
    db_service = ""
    db_env = ""
    use_db_depends = False
    if "postgres" in db:
        use_db_depends = True
        db_service = f"""
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: {slug}
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${{DB_PASSWORD:-secret}}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 10s
      timeout: 5s
      retries: 5"""
        db_env = "DATABASE_URL=postgresql+asyncpg://app:${DB_PASSWORD:-secret}@db:5432/" + slug
    elif "mongo" in db:
        use_db_depends = True
        db_service = f"""
  db:
    image: mongo:7
    volumes:
      - mongo_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 10s
      timeout: 5s
      retries: 5"""
        db_env = f"MONGODB_URL=mongodb://db:27017/{slug}"
    else:
        # SQLite — no db service needed
        db_env = f"DATABASE_URL=sqlite+aiosqlite:///./data/{slug}.db"

    cache_service = ""
    cache_env = ""
    if "redis" in cache:
        cache_service = """
  cache:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]"""
        cache_env = "REDIS_URL=redis://cache:6379"

    volumes = ""
    if "postgres" in db:
        volumes = "\nvolumes:\n  postgres_data:"
    elif "mongo" in db:
        volumes = "\nvolumes:\n  mongo_data:"

    # Only include depends_on block when a db service actually exists
    depends_on_block = ""
    if use_db_depends:
        depends_on_block = """    depends_on:
      db:
        condition: service_healthy
"""

    # Build environment block — skip empty entries
    env_lines = [f"      - {db_env}"]
    if cache_env:
        env_lines.append(f"      - {cache_env}")
    env_lines.append("      - APP_SECRET_KEY=${APP_SECRET_KEY:-dev-secret}")
    env_block = "\n".join(env_lines)

    # For SQLite: add a named volume for persistence
    sqlite_volume_mount = ""
    sqlite_volume_def = ""
    if not use_db_depends and "sqlite" in db_env.lower():
        sqlite_volume_mount = "    volumes:\n      - app_data:/app/data\n"
        sqlite_volume_def = "\nvolumes:\n  app_data:"

    return f"""version: '3.8'

services:
  app:
    build: .
    ports:
      - "${{PORT:-8000}}:8000"
    environment:
{env_block}
{sqlite_volume_mount}{depends_on_block}    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
{db_service}
{cache_service}
{volumes}{sqlite_volume_def}
"""


def _is_real_app(path: Path) -> bool:
    """True if file looks like a real FastAPI app (not a stub)."""
    try:
        content = path.read_text()
        return "FastAPI" in content and len(content) > 300 and "@app." in content
    except Exception:
        return False


def _find_main_py(project_dir: Path):
    """
    Find the real main.py using priority order.
    Returns (path, dotted_module_path) tuple.
    """
    # Priority 1: project_dir/src/main.py
    p = project_dir / "src" / "main.py"
    if p.exists() and _is_real_app(p):
        return p, "src.main"

    # Priority 2: p04_backend output dirs
    for sub in ["p04a_backend_codegen", "p04_backend", "backend_codegen"]:
        p = project_dir / sub / "src" / "main.py"
        if p.exists() and _is_real_app(p):
            return p, f"{sub}.src.main"
        p = project_dir / sub / "main.py"
        if p.exists() and _is_real_app(p):
            return p, f"{sub}.main"

    # Priority 3: any main.py with FastAPI in it
    for candidate in sorted(project_dir.rglob("main.py")):
        if _is_real_app(candidate):
            rel = candidate.relative_to(project_dir)
            module = str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
            return candidate, module

    # Last resort: first main.py found
    for candidate in sorted(project_dir.rglob("main.py")):
        rel = candidate.relative_to(project_dir)
        module = str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
        return candidate, module

    # Fallback if nothing found
    return project_dir / "src" / "main.py", "src.main"


def _detect_cloud(arch: Dict) -> str:
    notes = str(arch.get("scalability_notes", "")).lower()
    stack = str(arch.get("tech_stack", {})).lower()
    if "gcp" in notes or "google" in notes:
        return "gcp"
    if "azure" in notes:
        return "azure"
    return "aws"


def _strip_fences(code: str) -> str:
    lines = code.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
