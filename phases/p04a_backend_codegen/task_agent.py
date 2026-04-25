"""P04a Task Agent — generate backend code with syntax verification.

Key behaviours:
- Writes src/main.py + src/models.py to BOTH the project root and the
  p04_backend phase output directory (so the file browser surfaces them
  under the phase as well as the root).
- Intelligent fallback: when Ollama output fails ast.parse(), extracts
  resource nouns from raw_input and generates proper CRUD routes — never
  a generic hello-world.
"""
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

# ── Domain-aware resource extraction ─────────────────────────────────────────

_DOMAIN_KEYWORDS = {
    "todo":      ("todos",    ["id", "title", "description", "completed", "created_at"]),
    "task":      ("tasks",    ["id", "title", "status", "priority", "due_date", "user_id"]),
    "user":      ("users",    ["id", "email", "name", "hashed_password", "created_at"]),
    "product":   ("products", ["id", "name", "description", "price", "stock"]),
    "order":     ("orders",   ["id", "user_id", "status", "total", "created_at"]),
    "item":      ("items",    ["id", "name", "description", "quantity", "price"]),
    "post":      ("posts",    ["id", "title", "content", "author_id", "published_at"]),
    "comment":   ("comments", ["id", "post_id", "author_id", "content", "created_at"]),
    "blog":      ("posts",    ["id", "title", "content", "author_id", "tags"]),
    "article":   ("articles", ["id", "title", "body", "author_id", "published_at"]),
    "customer":  ("customers", ["id", "name", "email", "phone", "address"]),
    "employee":  ("employees", ["id", "name", "email", "role", "department"]),
    "event":     ("events",   ["id", "title", "description", "start_at", "end_at"]),
    "message":   ("messages", ["id", "sender_id", "recipient_id", "content", "sent_at"]),
    "payment":   ("payments", ["id", "order_id", "amount", "status", "method"]),
    "booking":   ("bookings", ["id", "user_id", "resource_id", "start_at", "end_at"]),
    "review":    ("reviews",  ["id", "user_id", "product_id", "rating", "content"]),
    "category":  ("categories", ["id", "name", "description", "parent_id"]),
    "inventory": ("inventory", ["id", "product_id", "quantity", "location"]),
    "report":    ("reports",  ["id", "title", "data", "generated_by", "created_at"]),
}

_STOP_WORDS = {
    "the", "and", "for", "are", "with", "that", "this", "from", "have",
    "will", "can", "but", "not", "build", "create", "make", "using", "api",
    "app", "rest", "web", "system", "service", "python", "fastapi", "django",
    "flask", "database", "backend", "server", "application",
}


def _extract_resources(raw_input: str) -> List[Dict]:
    lower = raw_input.lower()
    found, seen = [], set()
    for kw, (table, cols) in _DOMAIN_KEYWORDS.items():
        if kw in lower and table not in seen:
            found.append({"resource": kw, "table": table, "columns": cols})
            seen.add(table)
    if not found:
        words = re.findall(r'\b([a-z]{3,})\b', lower)
        for w in dict.fromkeys(words):
            if w not in _STOP_WORDS and len(found) < 3:
                table = w + "s" if not w.endswith("s") else w
                found.append({"resource": w, "table": table,
                              "columns": ["id", "name", "description", "created_at"]})
    return found or [{"resource": "item", "table": "items",
                      "columns": ["id", "name", "description", "created_at"]}]


def _load_arch(data: dict) -> dict:
    """Load architecture dict from context, trying multiple locations."""
    arch = data.get("architecture_json", {})
    if arch and isinstance(arch, dict) and arch.get("api_endpoints"):
        return arch
    for key in ("p02_architecture_path", "p01_intake_requirements_path"):
        path = data.get(key, "")
        if path:
            try:
                return json.loads(Path(path).read_text())
            except Exception:
                pass
    project_dir = Path(data.get("project_dir", ""))
    if project_dir.exists():
        for candidate in sorted(project_dir.rglob("architecture.json"))[:3]:
            try:
                return json.loads(candidate.read_text())
            except Exception:
                continue
    return {}


# ── Code generation ───────────────────────────────────────────────────────────

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data

    architecture = _load_arch(data)
    raw_input    = data.get("raw_input", "")

    # Root project dir (where src/ goes for the final deliverable)
    root_dir = Path(data.get("project_dir", str(output_dir / "project")))
    root_dir.mkdir(parents=True, exist_ok=True)

    client = get_llm_client()
    agent  = BackendCodegenAgent()
    generated_files = await agent.generate_backend_code(
        architecture, raw_input, root_dir, output_dir, client
    )

    issues = []
    if not generated_files:
        issues.append("No backend files were generated")

    return TaskResult(
        output_path=str(output_dir),
        confidence=0.9 if generated_files else 0.0,
        metadata={"generated_files": generated_files, "file_count": len(generated_files)},
        issues=issues,
        success=len(generated_files) > 0,
    )


class BackendCodegenAgent:

    async def generate_backend_code(
            self,
            architecture: dict,
            raw_input: str,
            root_dir: Path,
            phase_dir: Path,
            client: LLMClient) -> list:
        """
        Generate all backend files.
        Writes to root_dir/src/ (project deliverable) AND
                  phase_dir/src/ (visible in phase artifacts view).
        """
        generated_files = []

        endpoints  = architecture.get("api_endpoints", [])
        tech_stack = architecture.get("tech_stack", {})
        db_schema  = architecture.get("database_schema", [])
        resources  = _extract_resources(raw_input)

        # Fall back to resource-based endpoints if architecture is empty
        if not endpoints:
            primary = resources[0]
            endpoints = [
                {"method": "GET",    "path": "/health",             "auth": False,
                 "description": "Health check"},
                {"method": "GET",    "path": f"/{primary['table']}", "auth": True,
                 "description": f"List {primary['table']}"},
                {"method": "POST",   "path": f"/{primary['table']}", "auth": True,
                 "description": f"Create {primary['resource']}"},
                {"method": "GET",    "path": f"/{primary['table']}/{{id}}", "auth": True,
                 "description": f"Get {primary['resource']} by ID"},
                {"method": "PUT",    "path": f"/{primary['table']}/{{id}}", "auth": True,
                 "description": f"Update {primary['resource']}"},
                {"method": "DELETE", "path": f"/{primary['table']}/{{id}}", "auth": True,
                 "description": f"Delete {primary['resource']}"},
            ]
        if not db_schema:
            db_schema = [{"table": r["table"], "columns": r["columns"]}
                         for r in resources]

        backend = tech_stack.get("backend", "FastAPI")

        # ── main.py ──────────────────────────────────────────────────────────
        ep_list = "\n".join(
            f"  {ep.get('method','GET')} {ep.get('path','/')} — {ep.get('description','')}"
            for ep in endpoints[:8]
        )
        main_prompt = (
            f"Write a complete working FastAPI application in a single file called main.py.\n"
            f"Project requirement: {raw_input[:300]}\n\n"
            f"Endpoints to implement:\n{ep_list}\n\n"
            f"Rules:\n"
            f"- All imports at top of file\n"
            f"- Each endpoint returns JSON with real business logic (not just placeholder)\n"
            f"- Include /health endpoint returning {{\"status\": \"ok\"}}\n"
            f"- Use Pydantic v2 BaseModel for request/response bodies\n"
            f"- Use in-memory list/dict storage (no DB driver needed)\n"
            f"- Include CORS middleware\n"
            f"- No placeholder comments like 'TODO' or 'implement this'\n"
            f"Reply with ONLY valid Python code, no markdown fences."
        )
        main_code = await self._generate_python(main_prompt, client,
                                                 _intelligent_fallback_main(endpoints, resources))
        main_files = _write_to_both(main_code, root_dir, phase_dir, Path("src") / "main.py")
        generated_files.extend(main_files)

        # ── models.py ─────────────────────────────────────────────────────────
        schema_str = json.dumps(db_schema[:5], indent=2)
        models_prompt = (
            f"Write Pydantic v2 models for this database schema:\n{schema_str}\n\n"
            f"Rules:\n"
            f"- Each table becomes a BaseModel with all columns as typed fields\n"
            f"- Use Optional[int] = None for id fields\n"
            f"- Use appropriate types: str, int, float, bool, Optional\n"
            f"- Include a Create model (no id) and a full model (with id) for each table\n"
            f"Reply with ONLY valid Python code, no markdown fences."
        )
        models_code = await self._generate_python(models_prompt, client,
                                                   _fallback_models(db_schema))
        model_files = _write_to_both(models_code, root_dir, phase_dir, Path("src") / "models.py")
        generated_files.extend(model_files)

        # ── requirements.txt ─────────────────────────────────────────────────
        reqs = _build_requirements(tech_stack)
        for target_dir in [root_dir, phase_dir]:
            req_file = target_dir / "requirements.txt"
            req_file.write_text(reqs)
            generated_files.append(str(req_file))

        # ── .env.example ─────────────────────────────────────────────────────
        env_content = (
            "# Application settings\n"
            "SECRET_KEY=change-me-in-production\n"
            "DATABASE_URL=sqlite:///./data/app.db\n"
            "ALLOWED_ORIGINS=http://localhost:3000\n"
            "LOG_LEVEL=info\n"
        )
        env_file = root_dir / ".env.example"
        env_file.write_text(env_content)
        generated_files.append(str(env_file))

        # ── README.md ────────────────────────────────────────────────────────
        readme = _build_readme(raw_input, endpoints, resources, tech_stack)
        for target_dir in [root_dir, phase_dir]:
            (target_dir / "README.md").write_text(readme)
            generated_files.append(str(target_dir / "README.md"))

        logger.info("[p04a] Generated %d files in root=%s phase=%s",
                    len(generated_files), root_dir, phase_dir)
        return generated_files

    async def _generate_python(
            self, prompt: str, client: LLMClient, fallback: str) -> str:
        """Try LLM 2 times; each attempt validates with ast.parse(); use fallback on failure."""
        for attempt in range(2):
            try:
                code = await client.call(prompt, "code_generation", {})
                code = _strip_fences(code)
                ast.parse(code)   # validate syntax
                return code
            except SyntaxError as e:
                logger.warning("[p04a] Syntax error attempt %d: %s", attempt + 1, e)
            except Exception as e:
                logger.warning("[p04a] LLM error attempt %d: %s", attempt + 1, e)
        logger.info("[p04a] Using intelligent fallback code")
        return fallback


# ── File writing helpers ──────────────────────────────────────────────────────

def _write_to_both(content: str, root_dir: Path, phase_dir: Path,
                   rel_path: Path) -> List[str]:
    """Write content to rel_path under both root_dir and phase_dir."""
    written = []
    for target_dir in [root_dir, phase_dir]:
        dest = target_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        written.append(str(dest))
    return written


# ── Fallback code generators ──────────────────────────────────────────────────

def _strip_fences(code: str) -> str:
    code = re.sub(r"^```[a-z]*\n?", "", code.strip(), flags=re.MULTILINE)
    return code.rstrip("`").strip()


def _intelligent_fallback_main(endpoints: list, resources: List[Dict]) -> str:
    """
    Generate real CRUD FastAPI code from the detected resources.
    Uses in-memory storage so it's immediately runnable without a DB driver.
    """
    primary = resources[0] if resources else {"resource": "item", "table": "items",
                                               "columns": ["id", "name", "created_at"]}
    res     = primary["resource"]
    table   = primary["table"]
    cols    = [c for c in primary["columns"] if c != "id"]

    # Build Pydantic model fields
    field_defs = "\n".join(
        f"    {col}: Optional[str] = None" if col.endswith(("_at", "_id"))
        else f"    {col}: str"
        for col in cols[:6]
    )
    create_model = (
        f"class {res.title()}Create(BaseModel):\n"
        f"{field_defs}\n"
        f"\n"
        f"class {res.title()}(BaseModel):\n"
        f"    id: int\n"
        f"{field_defs}\n"
    )

    # Build routes
    routes = [
        f'@app.get("/health")\ndef health():\n    return {{"status": "ok", "version": "1.0.0"}}\n',
        f'@app.get("/{table}", response_model=List[{res.title()}])\ndef list_{table}():\n    return list({table}_db.values())\n',
        f'@app.post("/{table}", response_model={res.title()}, status_code=201)\ndef create_{res}(payload: {res.title()}Create):\n    new_id = max({table}_db.keys(), default=0) + 1\n    record = {res.title()}(id=new_id, **payload.dict())\n    {table}_db[new_id] = record\n    return record\n',
        f'@app.get("/{table}/{{item_id}}", response_model={res.title()})\ndef get_{res}(item_id: int):\n    if item_id not in {table}_db:\n        raise HTTPException(404, detail="{res.title()} not found")\n    return {table}_db[item_id]\n',
        f'@app.put("/{table}/{{item_id}}", response_model={res.title()})\ndef update_{res}(item_id: int, payload: {res.title()}Create):\n    if item_id not in {table}_db:\n        raise HTTPException(404, detail="{res.title()} not found")\n    updated = {res.title()}(id=item_id, **payload.dict())\n    {table}_db[item_id] = updated\n    return updated\n',
        f'@app.delete("/{table}/{{item_id}}")\ndef delete_{res}(item_id: int):\n    if item_id not in {table}_db:\n        raise HTTPException(404, detail="{res.title()} not found")\n    del {table}_db[item_id]\n    return {{"status": "deleted", "id": item_id}}\n',
    ]

    # Extra resources
    for r in resources[1:3]:
        r_res, r_table = r["resource"], r["table"]
        routes += [
            f'@app.get("/{r_table}")\ndef list_{r_table}():\n    return list({r_table}_db.values())\n',
            f'@app.post("/{r_table}", status_code=201)\ndef create_{r_res}(payload: dict):\n    new_id = max({r_table}_db.keys(), default=0) + 1\n    {r_table}_db[new_id] = {{"id": new_id, **payload}}\n    return {r_table}_db[new_id]\n',
        ]

    # In-memory stores
    stores = f"{table}_db: Dict[int, {res.title()}] = {{}}\n"
    for r in resources[1:3]:
        stores += f"{r['table']}_db: Dict[int, dict] = {{}}\n"

    return (
        "from fastapi import FastAPI, HTTPException\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from pydantic import BaseModel\n"
        "from typing import Dict, List, Optional\n\n"
        "app = FastAPI(title='Generated API', version='1.0.0')\n\n"
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['*'],\n"
        "    allow_methods=['*'],\n"
        "    allow_headers=['*'],\n"
        ")\n\n"
        f"# Pydantic models\n{create_model}\n"
        f"# In-memory storage (replace with real DB)\n{stores}\n\n"
        + "\n".join(routes)
    )


def _fallback_models(db_schema: list) -> str:
    lines = [
        "from pydantic import BaseModel\n"
        "from typing import Optional, List\n"
    ]
    for table in db_schema[:6]:
        name = table.get("table", "Item").rstrip("s").replace("_", " ").title().replace(" ", "")
        cols = table.get("columns", ["id", "name"])
        lines.append(f"class {name}Create(BaseModel):")
        for col in cols:
            if col == "id":
                continue
            t = "int" if col.endswith("_id") else "str"
            lines.append(f"    {col}: Optional[{t}] = None")
        lines.append("")
        lines.append(f"class {name}({name}Create):")
        lines.append(f"    id: Optional[int] = None")
        lines.append("")
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
    if "redis" in stack.get("cache", "").lower():
        pkgs += ["redis[hiredis]"]
    pkgs += [
        "python-dotenv",
        "python-jose[cryptography]",
        "passlib[bcrypt]",
        "prometheus-client",
        "httpx",
        "pytest>=8.0.0",
        "pytest-asyncio>=0.23.0",
        "slowapi",
    ]
    return "\n".join(sorted(set(pkgs))) + "\n"


def _build_readme(raw_input: str, endpoints: list, resources: List[Dict],
                  tech_stack: dict) -> str:
    primary  = resources[0] if resources else {"resource": "item", "table": "items"}
    ep_lines = "\n".join(
        f"| `{ep.get('method','GET')}` | `{ep.get('path','')}` | {ep.get('description','')} |"
        for ep in endpoints[:10]
    )
    return (
        f"# {raw_input[:60].title()}\n\n"
        f"Generated by AetherOS factory pipeline.\n\n"
        f"## Stack\n\n"
        f"- **Backend**: {tech_stack.get('backend', 'FastAPI')}\n"
        f"- **Database**: {tech_stack.get('database', 'PostgreSQL')}\n"
        f"- **Deployment**: {tech_stack.get('deployment', 'Docker')}\n\n"
        f"## Quick Start\n\n"
        f"```bash\npip install -r requirements.txt\nuvicorn src.main:app --reload\n```\n\n"
        f"## API Endpoints\n\n"
        f"| Method | Path | Description |\n"
        f"|--------|------|-------------|\n"
        f"{ep_lines}\n\n"
        f"Docs: http://localhost:8000/docs\n"
    )
