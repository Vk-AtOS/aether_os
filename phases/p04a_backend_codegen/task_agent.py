"""P04a Task Agent — generate backend code with syntax verification."""
from __future__ import annotations
import ast
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client, LLMClient

logger = logging.getLogger(__name__)


def _load_arch(data: dict) -> dict:
    """Load architecture dict from context, trying multiple locations."""
    arch = data.get("architecture_json", {})
    if arch and isinstance(arch, dict) and arch.get("api_endpoints"):
        return arch
    # Try reading from path
    for key in ("p02_architecture_path", "p01_intake_requirements_path"):
        path = data.get(key, "")
        if path:
            try:
                return json.loads(Path(path).read_text())
            except Exception:
                pass
    # Scan project_dir
    project_dir = Path(data.get("project_dir", ""))
    if project_dir.exists():
        for candidate in sorted(project_dir.rglob("architecture.json"))[:3]:
            try:
                return json.loads(candidate.read_text())
            except Exception:
                continue
    return {}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data

    architecture = _load_arch(data)
    project_dir = Path(data.get("project_dir", str(output_dir / "project")))
    project_dir.mkdir(parents=True, exist_ok=True)
    client = get_llm_client()

    agent = BackendCodegenAgent()
    generated_files = await agent.generate_backend_code(architecture, project_dir, client)

    issues = []
    if not generated_files:
        issues.append("No backend files were generated")

    return TaskResult(
        output_path=str(project_dir),
        confidence=0.9 if generated_files else 0.0,
        metadata={"generated_files": generated_files, "file_count": len(generated_files)},
        issues=issues,
        success=len(generated_files) > 0,
    )


class BackendCodegenAgent:
    async def generate_backend_code(
            self,
            architecture: dict,
            project_dir: Path,
            client: LLMClient) -> list:

        generated_files = []
        endpoints = architecture.get("api_endpoints", [
            {"method": "GET", "path": "/health", "description": "Health check", "auth": False}
        ])
        tech_stack = architecture.get("tech_stack", {})
        backend = tech_stack.get("backend", "FastAPI")
        db = tech_stack.get("database", "SQLite")

        src_dir = project_dir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        # ── main.py ──────────────────────────────────────────────────────────
        ep_list = "\n".join(
            f"  {ep.get('method','GET')} {ep.get('path','/')} — {ep.get('description','')}"
            for ep in endpoints[:6]
        )
        main_prompt = (
            f"Write a complete working FastAPI app in one file called main.py.\n"
            f"Endpoints to implement:\n{ep_list}\n"
            f"Rules: all imports at top, each endpoint returns JSON, include /health, "
            f"use Pydantic models for request bodies, no placeholder comments.\n"
            f"Reply with ONLY the Python code."
        )
        main_file = src_dir / "main.py"
        for attempt in range(3):
            try:
                code = await client.call(main_prompt, "code_generation", {})
                code = _strip_fences(code)
                ast.parse(code)
                main_file.write_text(code)
                generated_files.append(str(main_file))
                break
            except Exception as e:
                logger.warning("main.py attempt %d failed: %s", attempt + 1, e)
                if attempt == 2:
                    main_file.write_text(_fallback_main(endpoints))
                    generated_files.append(str(main_file))

        # ── models.py ─────────────────────────────────────────────────────────
        db_schema = architecture.get("database_schema", [])
        models_prompt = (
            f"Write Pydantic v2 models for this schema:\n"
            f"{json.dumps(db_schema[:4], indent=2)}\n"
            f"Each table → one BaseModel with all columns as fields.\n"
            f"Reply with ONLY the Python code, no markdown."
        )
        models_file = src_dir / "models.py"
        try:
            code = await client.call(models_prompt, "code_generation", {})
            code = _strip_fences(code)
            ast.parse(code)
            models_file.write_text(code)
            generated_files.append(str(models_file))
        except Exception as e:
            logger.warning("models.py generation failed: %s", e)
            # Fallback: generate models from schema directly
            models_file.write_text(_fallback_models(db_schema))
            generated_files.append(str(models_file))

        # ── requirements.txt ─────────────────────────────────────────────────
        reqs = _build_requirements(tech_stack)
        req_file = project_dir / "requirements.txt"
        req_file.write_text(reqs)
        generated_files.append(str(req_file))

        # ── .env.example ─────────────────────────────────────────────────────
        env_example = project_dir / ".env.example"
        env_example.write_text(
            "# Application settings\n"
            "SECRET_KEY=change-me-in-production\n"
            "DATABASE_URL=sqlite:///./data/app.db\n"
            "ALLOWED_ORIGINS=http://localhost:3000\n"
            "LOG_LEVEL=info\n"
        )
        generated_files.append(str(env_example))

        return generated_files


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_fences(code: str) -> str:
    code = re.sub(r"^```[a-z]*\n?", "", code.strip(), flags=re.MULTILINE)
    return code.rstrip("`").strip()


def _fallback_main(endpoints: list) -> str:
    routes = []
    for ep in endpoints:
        method = ep.get("method", "GET").lower()
        path   = ep.get("path", "/health")
        name   = re.sub(r"[^a-z0-9]", "_", path.strip("/")) or "health"
        routes.append(
            f'@app.{method}("{path}")\n'
            f'async def {name}():\n'
            f'    return {{"status": "ok", "path": "{path}"}}\n'
        )
    return (
        "from fastapi import FastAPI\n"
        "from fastapi.middleware.cors import CORSMiddleware\n\n"
        "app = FastAPI(title='Generated API')\n\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], "
        "allow_methods=['*'], allow_headers=['*'])\n\n"
        + "\n".join(routes)
    )


def _fallback_models(db_schema: list) -> str:
    lines = ["from pydantic import BaseModel\nfrom typing import Optional, List\n"]
    for table in db_schema[:6]:
        name = table.get("table", "Item").replace("_", " ").title().replace(" ", "")
        cols = table.get("columns", ["id", "name"])
        lines.append(f"class {name}(BaseModel):")
        for col in cols:
            t = "int" if col in ("id", "user_id", "count") else "str"
            opt = "Optional[" + t + "] = None" if col == "id" else t
            lines.append(f"    {col}: {opt}")
        lines.append("")
    if len(lines) == 1:
        lines.append("class Item(BaseModel):\n    id: Optional[int] = None\n    name: str\n")
    return "\n".join(lines)


def _build_requirements(stack: dict) -> str:
    pkgs = ["fastapi>=0.111.0", "uvicorn[standard]>=0.29.0", "pydantic>=2.0.0"]
    db = stack.get("database", "").lower()
    if "postgres" in db:
        pkgs += ["asyncpg", "sqlalchemy[asyncio]>=2.0.0", "alembic"]
    elif "mongo" in db:
        pkgs += ["motor", "beanie"]
    else:
        pkgs += ["aiosqlite", "sqlalchemy[asyncio]>=2.0.0"]
    cache = stack.get("cache", "").lower()
    if "redis" in cache:
        pkgs += ["redis[hiredis]"]
    pkgs += [
        "python-dotenv",
        "python-jose[cryptography]",
        "passlib[bcrypt]",
        "prometheus-client",
        "httpx",
        "pytest>=8.0.0",
        "pytest-asyncio>=0.23.0",
        "httpx",
    ]
    return "\n".join(sorted(set(pkgs))) + "\n"
