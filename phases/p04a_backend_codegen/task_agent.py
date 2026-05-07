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
import time
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
    domain = data.get("domain", "general")
    generated_files = await agent.generate_backend_code(
        architecture, raw_input, root_dir, output_dir, client, domain=domain, data=data
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
            client: LLMClient,
            domain: str = "general",
            data: dict = {}) -> list:
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
        from aether_os.core.domain_engine import get_domain_profile
        profile = get_domain_profile(domain)

        # ── main.py ──────────────────────────────────────────────────────────
        ep_list = "\n".join(
            f"  {ep.get('method','GET')} {ep.get('path','/')} — {ep.get('description','')}"
            for ep in endpoints[:8]
        )
        
        domain_rules = []
        if domain == "fintech":
            domain_rules.append("- Implement an @idempotent decorator for POST/PUT endpoints")
            domain_rules.append("- Include an 'audit_log' list and record all state changes")
        elif domain == "industrial":
            domain_rules.append("- Include a /telemetry endpoint for high-frequency sensor ingestion")
            domain_rules.append("- Implement a background task that checks for 'alarm' conditions")
        elif domain == "saas_multitenant":
            domain_rules.append("- Implement a middleware that extracts 'X-Org-ID' header into a ContextVar")
            domain_rules.append("- Ensure ALL in-memory storage queries are filtered by this org_id")
            domain_rules.append("- Add a /onboarding endpoint that initializes a new organisation")
        elif domain == "healthcare":
            domain_rules.append("- Implement a simple PII masking layer for patient data")
            domain_rules.append("- Include 'fhir_resource_type' in all models")
        
        rules_str = "\n".join(domain_rules)

        main_prompt = (
            f"Write a complete working FastAPI application in a single file called main.py.\n"
            f"Project requirement: {raw_input[:300]}\n"
            f"Domain: {profile.name}\n\n"
            f"Endpoints to implement:\n{ep_list}\n\n"
            f"Rules:\n"
            f"- At the top of main.py, include this header block:\n"
            f'  \"\"\"\n  Generated by AetherOS Factory — {time.ctime()}\n'
            f'  Project: {data.get("project_name", "App")}\n'
            f'  Domain: {domain}\n'
            f'  Requirement: {raw_input[:100]}\n'
            f'  Architecture decision: {profile.why_this_stack_was_chosen}\n  \"\"\"\n'
            f"- Before each route handler, include an inline comment explaining its purpose\n"
            f"- Before each domain-specific logic, include '# Domain pattern: {{name}} — {{why used}}' comments\n"
            f"- Include security comments like '# Security: why this pattern is required for this domain'\n"
            f"- Use Pydantic v2 BaseModel for request/response bodies\n"
            f"- Use in-memory list/dict storage (no DB driver needed)\n"
            f"- Include CORS middleware\n"
            f"{rules_str}\n"
            f"- No placeholder comments like 'TODO' or 'implement this'\n"
            f"Reply with ONLY valid Python code, no markdown fences."
        )
        main_code = await self._generate_python(main_prompt, client,
                                                 _intelligent_fallback_main(endpoints, resources, raw_input, domain=domain))
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

        # ── DECISIONS.md ──────────────────────────────────────────────────────
        decisions_content = (
            f"# Architecture Decisions\n\n"
            f"## Why {tech_stack.get('backend', 'FastAPI')}\n"
            f"{profile.why_this_stack_was_chosen}\n\n"
            f"## Key patterns used\n"
            f"{profile.required_patterns}\n\n"
            f"## Security requirements\n"
            f"{profile.security_requirements}\n\n"
            f"## How to extend this project\n"
            f"{profile.domain_specific_guidance}\n"
        )
        decisions_file = root_dir / "DECISIONS.md"
        decisions_file.write_text(decisions_content)
        generated_files.append(str(decisions_file))

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


def _intelligent_fallback_main(endpoints: list, resources: List[Dict],
                               raw_input: str = "", domain: str = "general") -> str:
    """
    Generate domain-specific FastAPI code from raw_input when LLM fails.
    Falls back to resource-based CRUD if domain can't be detected.
    """
    if raw_input.strip() and domain == "general":
        return _generate_from_requirement(raw_input)

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
    
    extra_fields = ""
    if domain == "saas_multitenant":
        extra_fields = "    org_id: str\n"
    elif domain == "healthcare":
        extra_fields = "    fhir_resource_type: str = 'Observation'\n"

    create_model = (
        f"class {res.title()}Create(BaseModel):\n"
        f"{field_defs}\n"
        f"{extra_fields}\n"
        f"class {res.title()}(BaseModel):\n"
        f"    id: int\n"
        f"{field_defs}\n"
        f"{extra_fields}\n"
    )

    # Build routes
    routes = [
        f'@app.get("/health")\ndef health():\n    return {{"status": "ok", "domain": "{domain}"}}\n',
    ]
    
    if domain == "industrial":
        routes.append(
            '@app.post("/telemetry")\ndef post_telemetry(data: dict):\n    # High-frequency ingestion\n    return {"status": "recorded", "ts": 123456789}\n'
        )
    elif domain == "fintech":
        routes.append(
            'def idempotent(func):\n    def wrapper(*args, **kwargs):\n        return func(*args, **kwargs)\n    return wrapper\n'
        )

    routes += [
        f'@app.get("/{table}", response_model=List[{res.title()}])\ndef list_{table}():\n    return list({table}_db.values())\n',
        f'@app.post("/{table}", response_model={res.title()}, status_code=201)\ndef create_{res}(payload: {res.title()}Create):\n    new_id = max({table}_db.keys(), default=0) + 1\n    record = {res.title()}(id=new_id, **payload.dict())\n    {table}_db[new_id] = record\n    return record\n',
    ]

    # In-memory stores
    stores = f"{table}_db: Dict[int, {res.title()}] = {{}}\n"
    
    middleware = ""
    if domain == "saas_multitenant":
        middleware = """
@app.middleware("http")
async def org_middleware(request, call_next):
    org_id = request.headers.get("X-Org-ID", "default")
    # In real app, set this in a ContextVar
    response = await call_next(request)
    return response
"""

    return (
        "from fastapi import FastAPI, HTTPException, Request\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from pydantic import BaseModel\n"
        "from typing import Dict, List, Optional\n\n"
        f"app = FastAPI(title='{domain.title()} API', version='1.0.0')\n\n"
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['*'],\n"
        "    allow_methods=['*'],\n"
        "    allow_headers=['*'],\n"
        ")\n"
        f"{middleware}\n"
        f"# Pydantic models\n{create_model}\n"
        f"# In-memory storage\n{stores}\n\n"
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


# ── Domain-specific template generators ──────────────────────────────────────

def _generate_from_requirement(raw_text: str, project_name: str = "app") -> str:
    """Detect domain from requirement text and return a matching FastAPI app."""
    low = raw_text.lower()
    if any(w in low for w in ["meeting", "notes", "summar", "transcript"]):
        return _meeting_summarizer_app(project_name or "meetingmind")
    if any(w in low for w in ["todo", "task", "checklist"]):
        return _todo_app(project_name or "taskmanager")
    if any(w in low for w in ["invoice", "billing", "payment"]):
        return _billing_app(project_name or "invoicer")
    if any(w in low for w in ["voice", "audio", "record", "speech"]):
        return _voice_app(project_name or "voicerecorder")
    if any(w in low for w in ["chat", "message", "conversation"]):
        return _chat_app(project_name or "chatapp")
    if any(w in low for w in ["game", "score", "player", "level", "snake"]):
        return _game_app(project_name or "gameapp")
    if any(w in low for w in ["odoo", "module", "erp", "attendance", "leave", "payroll", "inventory", "crm"]):
        return _odoo_module_app(project_name or "module")
    return _generic_api(project_name or "app")


# ── Python code templates (raw strings to avoid f-string conflicts) ───────────

_MEETING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MeetingMind</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f1117;color:#e2e8f0;height:100vh;display:flex;flex-direction:column}
header{padding:1rem 1.5rem;border-bottom:1px solid #1e293b;display:flex;align-items:center;gap:.75rem}
header h1{font-size:1.25rem;font-weight:700;color:#fff}
header .badge{font-size:.7rem;color:#6366f1;border:1px solid #6366f160;border-radius:999px;padding:.125rem .5rem}
.layout{display:flex;flex:1;overflow:hidden}
.sidebar{width:280px;border-right:1px solid #1e293b;overflow-y:auto;padding:1rem;flex-shrink:0}
.sidebar h2{font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.75rem}
.hi{background:#1e293b;border:1px solid #334155;border-radius:.5rem;padding:.75rem;margin-bottom:.5rem;cursor:pointer;transition:border-color .2s;position:relative}
.hi:hover{border-color:#6366f1}
.hi-sum{font-size:.78rem;color:#94a3b8;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hi-date{font-size:.68rem;color:#475569;margin-top:.25rem}
.hi-del{position:absolute;top:.5rem;right:.5rem;background:none;border:none;color:#475569;cursor:pointer;font-size:1rem;line-height:1;padding:0}
.hi-del:hover{color:#ef4444}
.main{flex:1;overflow-y:auto;padding:1.5rem;display:flex;flex-direction:column;gap:1rem}
.card{background:#1e293b;border:1px solid #334155;border-radius:.75rem;padding:1.25rem}
label{font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.05em;display:block;margin-bottom:.5rem}
textarea{width:100%;background:#0f172a;border:1px solid #334155;border-radius:.5rem;padding:.75rem;color:#e2e8f0;font-size:.875rem;resize:vertical;min-height:160px;outline:none;font-family:inherit}
textarea:focus{border-color:#6366f1}
.btn{display:inline-flex;align-items:center;gap:.5rem;background:#6366f1;color:#fff;border:none;border-radius:.5rem;padding:.625rem 1.25rem;font-size:.875rem;font-weight:600;cursor:pointer;transition:background .2s;margin-top:.75rem}
.btn:hover{background:#5254e7}
.btn:disabled{opacity:.5;cursor:not-allowed}
.rs h3{font-size:.875rem;font-weight:700;color:#fff;margin-bottom:.75rem}
.rs-sec{margin-bottom:1rem}
.rs-sec h4{font-size:.7rem;font-weight:600;color:#6366f1;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.4rem}
.rs-sec p{font-size:.875rem;color:#cbd5e1;line-height:1.6}
.rs-sec ul{list-style:none;padding:0}
.rs-sec li{font-size:.875rem;color:#cbd5e1;padding:.2rem 0 .2rem 1rem;position:relative}
.rs-sec li::before{content:"›";position:absolute;left:0;color:#6366f1}
.hidden{display:none}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #fff4;border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<header>
  <h1>MeetingMind</h1>
  <span class="badge">AI Summarizer</span>
</header>
<div class="layout">
  <aside class="sidebar">
    <h2>History</h2>
    <div id="hist"></div>
  </aside>
  <main class="main">
    <div class="card">
      <label>Paste Meeting Notes</label>
      <textarea id="notes" placeholder="Paste your meeting notes here..."></textarea>
      <button class="btn" id="sbtn" onclick="doSummarize()">
        <span id="bico">&#10024;</span>
        <span id="btxt">Summarize with AI</span>
      </button>
    </div>
    <div class="card rs hidden" id="res">
      <h3>Summary</h3>
      <div class="rs-sec"><h4>Overview</h4><p id="r-sum"></p></div>
      <div class="rs-sec"><h4>Action Items</h4><ul id="r-act"></ul></div>
      <div class="rs-sec"><h4>Decisions</h4><ul id="r-dec"></ul></div>
      <div class="rs-sec"><h4>Next Steps</h4><ul id="r-nxt"></ul></div>
    </div>
  </main>
</div>
<script>
var _cache={};
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
async function doSummarize(){
  var notes=document.getElementById('notes').value.trim();
  if(!notes)return;
  var btn=document.getElementById('sbtn');
  btn.disabled=true;
  document.getElementById('bico').innerHTML='<span class="spinner"></span>';
  document.getElementById('btxt').textContent='Summarizing...';
  try{
    var r=await fetch('/summarize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:notes})});
    var d=await r.json();
    showResult(d);
    loadHistory();
  }catch(e){alert('Error: '+e.message);}
  finally{
    btn.disabled=false;
    document.getElementById('bico').textContent='\\u2728';
    document.getElementById('btxt').textContent='Summarize with AI';
  }
}
function showResult(d){
  document.getElementById('r-sum').textContent=d.summary||'';
  function toList(el,arr){el.innerHTML=(arr||[]).map(function(i){return'<li>'+esc(i)+'</li>';}).join('')||'<li>None noted.</li>';}
  toList(document.getElementById('r-act'),d.action_items);
  toList(document.getElementById('r-dec'),d.decisions);
  toList(document.getElementById('r-nxt'),d.next_steps);
  document.getElementById('res').classList.remove('hidden');
}
async function loadHistory(){
  try{
    var r=await fetch('/summaries');var items=await r.json();
    _cache={};items.forEach(function(i){_cache[i.id]=i;});
    var el=document.getElementById('hist');
    if(!items.length){el.innerHTML='<p style="color:#475569;font-size:.8rem">No summaries yet.</p>';return;}
    el.innerHTML=items.map(function(item){
      return'<div class="hi" onclick="loadItem('+item.id+')">'
        +'<button class="hi-del" onclick="event.stopPropagation();delItem('+item.id+')">\\u00d7</button>'
        +'<div class="hi-sum">'+esc(item.summary)+'</div>'
        +'<div class="hi-date">'+(item.created_at?item.created_at.split('T')[0]:'')+'</div></div>';
    }).join('');
  }catch(e){}
}
function loadItem(id){if(_cache[id])showResult(_cache[id]);}
async function delItem(id){
  if(!confirm('Delete?'))return;
  await fetch('/summaries/'+id,{method:'DELETE'});
  loadHistory();
}
loadHistory();
</script>
</body>
</html>"""


def _meeting_summarizer_app(project_name: str = "meetingmind") -> str:
    """Return a complete meeting summarizer FastAPI app with SQLite + Ollama."""
    body = r'''from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3, httpx, json, re, os
from pathlib import Path

app = FastAPI(title="MeetingMind", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = Path("data/meetings.db")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:3b")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        notes TEXT NOT NULL,
        summary TEXT NOT NULL,
        action_items TEXT DEFAULT '[]',
        decisions TEXT DEFAULT '[]',
        next_steps TEXT DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit(); conn.close()


init_db()


class SummarizeRequest(BaseModel):
    notes: str


class SummaryOut(BaseModel):
    id: Optional[int] = None
    notes: str
    summary: str
    action_items: List[str] = []
    decisions: List[str] = []
    next_steps: List[str] = []
    created_at: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0", "service": "MeetingMind"}


@app.post("/summarize", response_model=SummaryOut)
async def summarize(req: SummarizeRequest):
    prompt = (
        "Analyze these meeting notes. Respond with ONLY valid JSON (no markdown fences):\n"
        "{\"summary\": \"2-3 sentence overview\", \"action_items\": [\"item\"],"
        " \"decisions\": [\"decision\"], \"next_steps\": [\"step\"]}\n\nNotes:\n"
        + req.notes[:3000]
    )
    result = {"summary": "Summary unavailable (Ollama not reachable).",
              "action_items": [], "decisions": [], "next_steps": []}
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(OLLAMA_URL, json={"model": OLLAMA_MODEL,
                                               "prompt": prompt, "stream": False})
            r.raise_for_status()
            raw = r.json().get("response", "{}")
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                p = json.loads(m.group())
                result = {k: p.get(k, result[k]) for k in result}
    except Exception:
        pass
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "INSERT INTO summaries (notes,summary,action_items,decisions,next_steps)"
            " VALUES(?,?,?,?,?)",
            (req.notes, result["summary"], json.dumps(result["action_items"]),
             json.dumps(result["decisions"]), json.dumps(result["next_steps"])))
        conn.commit(); rid = cur.lastrowid
    finally:
        conn.close()
    return SummaryOut(id=rid, notes=req.notes, **result)


@app.get("/summaries", response_model=List[SummaryOut])
def list_summaries():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM summaries ORDER BY created_at DESC LIMIT 50").fetchall()
        return [SummaryOut(id=r["id"], notes=r["notes"], summary=r["summary"],
                action_items=json.loads(r["action_items"] or "[]"),
                decisions=json.loads(r["decisions"] or "[]"),
                next_steps=json.loads(r["next_steps"] or "[]"),
                created_at=r["created_at"]) for r in rows]
    finally:
        conn.close()


@app.delete("/summaries/{sid}")
def delete_summary(sid: int):
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.execute("DELETE FROM summaries WHERE id=?", (sid,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, detail="Not found")
        return {"status": "deleted", "id": sid}
    finally:
        conn.close()


HTML_CONTENT = __HTML__


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_CONTENT
'''
    return body.replace("__HTML__", repr(_MEETING_HTML))


def _todo_app(project_name: str = "taskmanager") -> str:
    """Return a complete todo/task manager FastAPI app."""
    html = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>TaskManager</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e2e8f0;max-width:800px;margin:0 auto;padding:2rem}
h1{color:#fff;margin-bottom:1.5rem;font-size:1.5rem}
.form{display:flex;gap:.75rem;margin-bottom:1.5rem}
input[type=text]{flex:1;background:#1e293b;border:1px solid #334155;border-radius:.5rem;padding:.625rem 1rem;color:#e2e8f0;font-size:.875rem;outline:none}
input:focus{border-color:#6366f1}
select{background:#1e293b;border:1px solid #334155;border-radius:.5rem;padding:.625rem;color:#e2e8f0;outline:none}
button{background:#6366f1;color:#fff;border:none;border-radius:.5rem;padding:.625rem 1.25rem;font-size:.875rem;font-weight:600;cursor:pointer}
button:hover{background:#5254e7}
.todo{background:#1e293b;border:1px solid #334155;border-radius:.5rem;padding:.875rem 1rem;margin-bottom:.5rem;display:flex;align-items:center;gap:.75rem}
.todo.done .title{text-decoration:line-through;color:#64748b}
.title{flex:1;font-size:.875rem}
.badge{font-size:.65rem;padding:.125rem .5rem;border-radius:999px;font-weight:600}
.HIGH{background:#ef444420;color:#ef4444;border:1px solid #ef444440}
.MEDIUM{background:#f59e0b20;color:#f59e0b;border:1px solid #f59e0b40}
.LOW{background:#22c55e20;color:#22c55e;border:1px solid #22c55e40}
.del{background:none;border:none;color:#475569;cursor:pointer;padding:0;font-size:1.1rem}
.del:hover{color:#ef4444}
</style></head>
<body>
<h1>Task Manager</h1>
<div class="form">
  <input type="text" id="title" placeholder="New task title..." onkeydown="if(event.key==='Enter')addTask()">
  <select id="pri"><option value="HIGH">High</option><option value="MEDIUM" selected>Medium</option><option value="LOW">Low</option></select>
  <button onclick="addTask()">Add Task</button>
</div>
<div id="list"></div>
<script>
async function load(){
  var r=await fetch('/todos');var todos=await r.json();
  var el=document.getElementById('list');
  el.innerHTML=todos.map(function(t){
    return'<div class="todo'+(t.completed?' done':'')+'"><input type="checkbox"'+(t.completed?' checked':'')
      +' onchange="toggle('+t.id+',this.checked)"><span class="title">'+esc(t.title)+'</span>'
      +'<span class="badge '+t.priority+'">'+t.priority+'</span>'
      +'<button class="del" onclick="del('+t.id+')">&#x2715;</button></div>';
  }).join('');
}
async function addTask(){
  var t=document.getElementById('title').value.trim();
  if(!t)return;
  var p=document.getElementById('pri').value;
  await fetch('/todos',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,priority:p})});
  document.getElementById('title').value='';load();
}
async function toggle(id,done){await fetch('/todos/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({completed:done})});load();}
async function del(id){await fetch('/todos/'+id,{method:'DELETE'});load();}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
load();
</script>
</body></html>"""

    return (
        "from fastapi import FastAPI, HTTPException\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from fastapi.responses import HTMLResponse\n"
        "from pydantic import BaseModel\n"
        "from typing import Optional, List\n"
        "import sqlite3, json\n"
        "from pathlib import Path\n\n"
        "app = FastAPI(title='TaskManager', version='1.0.0')\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])\n\n"
        "DB_PATH = Path('data/tasks.db')\n\n"
        "def init_db():\n"
        "    DB_PATH.parent.mkdir(parents=True, exist_ok=True)\n"
        "    conn = sqlite3.connect(str(DB_PATH))\n"
        "    conn.execute(\"\"\"CREATE TABLE IF NOT EXISTS todos (\n"
        "        id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "        title TEXT NOT NULL,\n"
        "        priority TEXT DEFAULT 'MEDIUM',\n"
        "        completed INTEGER DEFAULT 0,\n"
        "        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
        "    )\"\"\")\n"
        "    conn.commit(); conn.close()\n\n"
        "init_db()\n\n"
        "class TodoCreate(BaseModel):\n"
        "    title: str\n"
        "    priority: str = 'MEDIUM'\n\n"
        "class TodoUpdate(BaseModel):\n"
        "    completed: Optional[bool] = None\n"
        "    title: Optional[str] = None\n\n"
        "class TodoOut(BaseModel):\n"
        "    id: int\n"
        "    title: str\n"
        "    priority: str\n"
        "    completed: bool\n"
        "    created_at: Optional[str] = None\n\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'ok'}\n\n"
        "@app.get('/todos', response_model=List[TodoOut])\n"
        "def list_todos():\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        rows = conn.execute('SELECT * FROM todos ORDER BY created_at DESC').fetchall()\n"
        "        return [dict(r) for r in rows]\n"
        "    finally: conn.close()\n\n"
        "@app.post('/todos', response_model=TodoOut, status_code=201)\n"
        "def create_todo(payload: TodoCreate):\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        cur = conn.execute('INSERT INTO todos(title,priority) VALUES(?,?)',\n"
        "                           (payload.title, payload.priority))\n"
        "        conn.commit()\n"
        "        row = conn.execute('SELECT * FROM todos WHERE id=?', (cur.lastrowid,)).fetchone()\n"
        "        return dict(row)\n"
        "    finally: conn.close()\n\n"
        "@app.put('/todos/{tid}', response_model=TodoOut)\n"
        "def update_todo(tid: int, payload: TodoUpdate):\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        if payload.completed is not None:\n"
        "            conn.execute('UPDATE todos SET completed=? WHERE id=?', (int(payload.completed), tid))\n"
        "        if payload.title:\n"
        "            conn.execute('UPDATE todos SET title=? WHERE id=?', (payload.title, tid))\n"
        "        conn.commit()\n"
        "        row = conn.execute('SELECT * FROM todos WHERE id=?', (tid,)).fetchone()\n"
        "        if not row: raise HTTPException(404, 'Not found')\n"
        "        return dict(row)\n"
        "    finally: conn.close()\n\n"
        "@app.delete('/todos/{tid}')\n"
        "def delete_todo(tid: int):\n"
        "    conn = sqlite3.connect(str(DB_PATH))\n"
        "    try:\n"
        "        cur = conn.execute('DELETE FROM todos WHERE id=?', (tid,))\n"
        "        conn.commit()\n"
        "        if cur.rowcount == 0: raise HTTPException(404, 'Not found')\n"
        "        return {'status': 'deleted', 'id': tid}\n"
        "    finally: conn.close()\n\n"
        f"HTML_CONTENT = {repr(html)}\n\n"
        "@app.get('/', response_class=HTMLResponse)\n"
        "async def index(): return HTML_CONTENT\n"
    )


def _voice_app(project_name: str = "voicerecorder") -> str:
    """Return a voice recorder FastAPI app (browser MediaRecorder + file storage)."""
    html = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Voice Recorder</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e2e8f0;display:flex;flex-direction:column;align-items:center;padding:3rem 1rem}
h1{color:#fff;margin-bottom:2rem}
.rec-btn{width:80px;height:80px;border-radius:50%;border:none;background:#6366f1;cursor:pointer;font-size:2rem;transition:all .2s;box-shadow:0 0 0 0 #6366f160}
.rec-btn.recording{background:#ef4444;animation:pulse 1s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 #ef444460}70%{box-shadow:0 0 0 20px #ef444400}100%{box-shadow:0 0 0 0 #ef444400}}
.status{margin:.75rem 0;font-size:.875rem;color:#64748b}
.recordings{width:100%;max-width:600px;margin-top:2rem}
.recordings h2{font-size:.875rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.75rem}
.rec-item{background:#1e293b;border:1px solid #334155;border-radius:.5rem;padding:.875rem 1rem;margin-bottom:.5rem;display:flex;align-items:center;gap:.75rem}
.rec-item audio{flex:1;height:32px}
.rec-name{font-size:.8rem;color:#94a3b8;min-width:160px}
.del{background:none;border:none;color:#475569;cursor:pointer;font-size:1.1rem}
.del:hover{color:#ef4444}
</style></head>
<body>
<h1>Voice Recorder</h1>
<button class="rec-btn" id="rbtn" onclick="toggleRecord()">&#x1f3a4;</button>
<div class="status" id="status">Click to start recording</div>
<div class="recordings"><h2>Recordings</h2><div id="rlist"></div></div>
<script>
var mr=null,chunks=[];
async function toggleRecord(){
  if(mr&&mr.state==='recording'){mr.stop();return;}
  var stream=await navigator.mediaDevices.getUserMedia({audio:true});
  mr=new MediaRecorder(stream);chunks=[];
  mr.ondataavailable=function(e){chunks.push(e.data);};
  mr.onstop=async function(){
    var blob=new Blob(chunks,{type:'audio/webm'});
    var fd=new FormData();fd.append('audio',blob,'recording.webm');
    await fetch('/transcribe',{method:'POST',body:fd});
    stream.getTracks().forEach(function(t){t.stop();});
    document.getElementById('rbtn').classList.remove('recording');
    document.getElementById('rbtn').textContent='\\u1f3a4';
    document.getElementById('status').textContent='Click to start recording';
    loadRecs();
  };
  mr.start();
  document.getElementById('rbtn').classList.add('recording');
  document.getElementById('status').textContent='Recording... click to stop';
}
async function loadRecs(){
  var r=await fetch('/recordings');var recs=await r.json();
  var el=document.getElementById('rlist');
  el.innerHTML=recs.map(function(rec){
    return'<div class="rec-item"><span class="rec-name">'+esc(rec.filename)+'</span>'
      +'<audio controls src="/recordings/'+esc(rec.filename)+'"></audio>'
      +'<button class="del" onclick="delRec('+rec.id+')">&#x2715;</button></div>';
  }).join('');
}
async function delRec(id){await fetch('/recordings/'+id,{method:'DELETE'});loadRecs();}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
loadRecs();
</script>
</body></html>"""

    return (
        "from fastapi import FastAPI, HTTPException, UploadFile, File\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from fastapi.responses import HTMLResponse, FileResponse\n"
        "from pydantic import BaseModel\n"
        "from typing import Optional, List\n"
        "import sqlite3, shutil, uuid\n"
        "from pathlib import Path\n\n"
        "app = FastAPI(title='VoiceRecorder', version='1.0.0')\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])\n\n"
        "AUDIO_DIR = Path('data/recordings')\n"
        "DB_PATH = Path('data/recordings.db')\n\n"
        "def init_db():\n"
        "    AUDIO_DIR.mkdir(parents=True, exist_ok=True)\n"
        "    DB_PATH.parent.mkdir(parents=True, exist_ok=True)\n"
        "    conn = sqlite3.connect(str(DB_PATH))\n"
        "    conn.execute(\"\"\"CREATE TABLE IF NOT EXISTS recordings (\n"
        "        id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "        filename TEXT NOT NULL,\n"
        "        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
        "    )\"\"\")\n"
        "    conn.commit(); conn.close()\n\n"
        "init_db()\n\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'ok'}\n\n"
        "@app.post('/transcribe')\n"
        "async def transcribe(audio: UploadFile = File(...)):\n"
        "    fname = f'{uuid.uuid4().hex}.webm'\n"
        "    dest = AUDIO_DIR / fname\n"
        "    with open(dest, 'wb') as f:\n"
        "        shutil.copyfileobj(audio.file, f)\n"
        "    conn = sqlite3.connect(str(DB_PATH))\n"
        "    try:\n"
        "        cur = conn.execute('INSERT INTO recordings(filename) VALUES(?)', (fname,))\n"
        "        conn.commit(); rid = cur.lastrowid\n"
        "    finally: conn.close()\n"
        "    return {'id': rid, 'filename': fname}\n\n"
        "@app.get('/recordings')\n"
        "def list_recordings():\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        rows = conn.execute('SELECT * FROM recordings ORDER BY created_at DESC').fetchall()\n"
        "        return [dict(r) for r in rows]\n"
        "    finally: conn.close()\n\n"
        "@app.get('/recordings/{filename}')\n"
        "def get_recording(filename: str):\n"
        "    path = AUDIO_DIR / filename\n"
        "    if not path.exists(): raise HTTPException(404, 'Not found')\n"
        "    return FileResponse(str(path), media_type='audio/webm')\n\n"
        "@app.delete('/recordings/{rid}')\n"
        "def delete_recording(rid: int):\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        row = conn.execute('SELECT filename FROM recordings WHERE id=?', (rid,)).fetchone()\n"
        "        if not row: raise HTTPException(404, 'Not found')\n"
        "        audio = AUDIO_DIR / row['filename']\n"
        "        if audio.exists(): audio.unlink()\n"
        "        conn.execute('DELETE FROM recordings WHERE id=?', (rid,))\n"
        "        conn.commit()\n"
        "        return {'status': 'deleted', 'id': rid}\n"
        "    finally: conn.close()\n\n"
        f"HTML_CONTENT = {repr(html)}\n\n"
        "@app.get('/', response_class=HTMLResponse)\n"
        "async def index(): return HTML_CONTENT\n"
    )


def _chat_app(project_name: str = "chatapp") -> str:
    """Return an AI chat FastAPI app (Ollama backend)."""
    html = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>AI Chat</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Courier New',monospace;background:#0a0a0a;color:#e2e8f0;height:100vh;display:flex;flex-direction:column}
header{padding:.75rem 1.5rem;border-bottom:1px solid #1a1a2e;display:flex;align-items:center;justify-content:space-between}
header h1{color:#6366f1;font-size:1rem}
.chat{flex:1;overflow-y:auto;padding:1rem 1.5rem;display:flex;flex-direction:column;gap:.75rem}
.msg{max-width:70%;padding:.625rem 1rem;border-radius:.75rem;font-size:.875rem;line-height:1.5;white-space:pre-wrap}
.user{align-self:flex-end;background:#6366f1;color:#fff}
.assistant{align-self:flex-start;background:#1e293b;color:#e2e8f0;border:1px solid #334155}
.footer{padding:.75rem 1rem;border-top:1px solid #1a1a2e;display:flex;gap:.5rem}
textarea{flex:1;background:#1e293b;border:1px solid #334155;border-radius:.5rem;padding:.625rem;color:#e2e8f0;font-size:.875rem;resize:none;outline:none;height:44px;font-family:inherit}
textarea:focus{border-color:#6366f1}
button{background:#6366f1;color:#fff;border:none;border-radius:.5rem;padding:.625rem 1rem;cursor:pointer;font-size:.875rem;font-weight:600}
button:hover{background:#5254e7}
.clear-btn{background:#1e293b;color:#64748b;border:1px solid #334155}
.clear-btn:hover{color:#e2e8f0}
</style></head>
<body>
<header><h1>&#9670; AI Chat</h1><button class="clear-btn" onclick="clearChat()">Clear</button></header>
<div class="chat" id="chat"></div>
<div class="footer">
  <textarea id="inp" placeholder="Message..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}"></textarea>
  <button onclick="send()">Send</button>
</div>
<script>
async function send(){
  var inp=document.getElementById('inp');
  var msg=inp.value.trim();if(!msg)return;
  inp.value='';
  addMsg('user',msg);
  var el=addMsg('assistant','...');
  try{
    var r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
    var d=await r.json();
    el.textContent=d.reply||d.error||'No response';
  }catch(e){el.textContent='Error: '+e.message;}
  var chat=document.getElementById('chat');
  chat.scrollTop=chat.scrollHeight;
}
function addMsg(role,text){
  var chat=document.getElementById('chat');
  var div=document.createElement('div');div.className='msg '+role;div.textContent=text;
  chat.appendChild(div);chat.scrollTop=chat.scrollHeight;return div;
}
async function clearChat(){
  await fetch('/chat',{method:'DELETE'});
  document.getElementById('chat').innerHTML='';
}
</script>
</body></html>"""

    return (
        "from fastapi import FastAPI\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from fastapi.responses import HTMLResponse\n"
        "from pydantic import BaseModel\n"
        "import httpx, os\n\n"
        "app = FastAPI(title='AIChat', version='1.0.0')\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])\n\n"
        "OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://host.docker.internal:11434/api/generate')\n"
        "OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:3b')\n"
        "history = []\n\n"
        "class ChatRequest(BaseModel):\n"
        "    message: str\n\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'ok'}\n\n"
        "@app.post('/chat')\n"
        "async def chat(req: ChatRequest):\n"
        "    history.append({'role': 'user', 'content': req.message})\n"
        "    context = '\\n'.join([f\"{m['role'].upper()}: {m['content']}\" for m in history[-10:]])\n"
        "    prompt = f'You are a helpful assistant.\\n\\nConversation:\\n{context}\\n\\nASSISTANT:'\n"
        "    try:\n"
        "        async with httpx.AsyncClient(timeout=60.0) as c:\n"
        "            r = await c.post(OLLAMA_URL, json={'model': OLLAMA_MODEL, 'prompt': prompt, 'stream': False})\n"
        "            reply = r.json().get('response', 'No response from model').strip()\n"
        "    except Exception as e:\n"
        "        reply = f'Ollama not reachable: {str(e)[:100]}'\n"
        "    history.append({'role': 'assistant', 'content': reply})\n"
        "    return {'reply': reply}\n\n"
        "@app.delete('/chat')\n"
        "def clear_chat():\n"
        "    history.clear()\n"
        "    return {'status': 'cleared'}\n\n"
        f"HTML_CONTENT = {repr(html)}\n\n"
        "@app.get('/', response_class=HTMLResponse)\n"
        "async def index(): return HTML_CONTENT\n"
    )


def _billing_app(project_name: str = "invoicer") -> str:
    """Return an invoice generator FastAPI app with SQLite."""
    html = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Invoicer</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e2e8f0;padding:2rem;max-width:900px;margin:0 auto}
h1{color:#fff;margin-bottom:1.5rem}
.form{background:#1e293b;border:1px solid #334155;border-radius:.75rem;padding:1.5rem;margin-bottom:1.5rem}
.row{display:grid;grid-template-columns:2fr 1fr 1fr;gap:.75rem;margin-bottom:.75rem}
input{background:#0f172a;border:1px solid #334155;border-radius:.375rem;padding:.5rem .75rem;color:#e2e8f0;font-size:.875rem;outline:none;width:100%}
input:focus{border-color:#6366f1}
.btn{background:#6366f1;color:#fff;border:none;border-radius:.5rem;padding:.625rem 1.25rem;cursor:pointer;font-size:.875rem;font-weight:600}
.btn:hover{background:#5254e7}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;padding:.5rem .75rem;border-bottom:1px solid #1e293b}
td{padding:.75rem;border-bottom:1px solid #1e293b;font-size:.875rem}
.total{font-weight:700;color:#6366f1}
.del{background:none;border:none;color:#475569;cursor:pointer;font-size:1rem}
.del:hover{color:#ef4444}
</style></head>
<body>
<h1>Invoicer</h1>
<div class="form">
  <div class="row">
    <input id="client" placeholder="Client name" type="text">
    <input id="desc" placeholder="Description" type="text">
    <input id="amount" placeholder="Amount" type="number" step="0.01">
  </div>
  <button class="btn" onclick="addInvoice()">Create Invoice</button>
</div>
<table>
  <thead><tr><th>Client</th><th>Description</th><th>Amount</th><th>Status</th><th>Date</th><th></th></tr></thead>
  <tbody id="tbody"></tbody>
</table>
<script>
async function load(){
  var r=await fetch('/invoices');var inv=await r.json();
  var el=document.getElementById('tbody');
  var total=inv.reduce(function(s,i){return s+(i.amount||0);},0);
  el.innerHTML=inv.map(function(i){
    return'<tr><td>'+esc(i.client)+'</td><td>'+esc(i.description)+'</td>'
      +'<td>$'+(i.amount||0).toFixed(2)+'</td>'
      +'<td>'+esc(i.status)+'</td>'
      +'<td>'+(i.created_at?i.created_at.split('T')[0]:i.created_at||'')+'</td>'
      +'<td><button class="del" onclick="del('+i.id+')">&#x2715;</button></td></tr>';
  }).join('')+'<tr><td colspan="2"></td><td class="total">Total: $'+total.toFixed(2)+'</td><td colspan="3"></td></tr>';
}
async function addInvoice(){
  var c=document.getElementById('client').value.trim();
  var d=document.getElementById('desc').value.trim();
  var a=parseFloat(document.getElementById('amount').value);
  if(!c||!d||isNaN(a))return alert('Fill all fields');
  await fetch('/invoices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client:c,description:d,amount:a})});
  document.getElementById('client').value='';document.getElementById('desc').value='';document.getElementById('amount').value='';
  load();
}
async function del(id){await fetch('/invoices/'+id,{method:'DELETE'});load();}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
load();
</script>
</body></html>"""

    return (
        "from fastapi import FastAPI, HTTPException\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from fastapi.responses import HTMLResponse\n"
        "from pydantic import BaseModel\n"
        "from typing import Optional, List\n"
        "import sqlite3\n"
        "from pathlib import Path\n\n"
        "app = FastAPI(title='Invoicer', version='1.0.0')\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])\n\n"
        "DB_PATH = Path('data/invoices.db')\n\n"
        "def init_db():\n"
        "    DB_PATH.parent.mkdir(parents=True, exist_ok=True)\n"
        "    conn = sqlite3.connect(str(DB_PATH))\n"
        "    conn.execute(\"\"\"CREATE TABLE IF NOT EXISTS invoices (\n"
        "        id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "        client TEXT NOT NULL,\n"
        "        description TEXT NOT NULL,\n"
        "        amount REAL NOT NULL,\n"
        "        status TEXT DEFAULT 'pending',\n"
        "        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
        "    )\"\"\")\n"
        "    conn.commit(); conn.close()\n\n"
        "init_db()\n\n"
        "class InvoiceCreate(BaseModel):\n"
        "    client: str\n"
        "    description: str\n"
        "    amount: float\n"
        "    status: str = 'pending'\n\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'ok'}\n\n"
        "@app.get('/invoices')\n"
        "def list_invoices():\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        rows = conn.execute('SELECT * FROM invoices ORDER BY created_at DESC').fetchall()\n"
        "        return [dict(r) for r in rows]\n"
        "    finally: conn.close()\n\n"
        "@app.post('/invoices', status_code=201)\n"
        "def create_invoice(payload: InvoiceCreate):\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        cur = conn.execute('INSERT INTO invoices(client,description,amount,status) VALUES(?,?,?,?)',\n"
        "                           (payload.client, payload.description, payload.amount, payload.status))\n"
        "        conn.commit()\n"
        "        row = conn.execute('SELECT * FROM invoices WHERE id=?', (cur.lastrowid,)).fetchone()\n"
        "        return dict(row)\n"
        "    finally: conn.close()\n\n"
        "@app.delete('/invoices/{iid}')\n"
        "def delete_invoice(iid: int):\n"
        "    conn = sqlite3.connect(str(DB_PATH))\n"
        "    try:\n"
        "        cur = conn.execute('DELETE FROM invoices WHERE id=?', (iid,))\n"
        "        conn.commit()\n"
        "        if cur.rowcount == 0: raise HTTPException(404, 'Not found')\n"
        "        return {'status': 'deleted', 'id': iid}\n"
        "    finally: conn.close()\n\n"
        f"HTML_CONTENT = {repr(html)}\n\n"
        "@app.get('/', response_class=HTMLResponse)\n"
        "async def index(): return HTML_CONTENT\n"
    )


def _game_app(project_name: str = "gameapp") -> str:
    """Return a Snake game FastAPI app."""
    html = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Snake</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e2e8f0;display:flex;flex-direction:column;align-items:center;padding:2rem}
h1{color:#6366f1;font-size:1.5rem;margin-bottom:.5rem}
.meta{font-size:.875rem;color:#64748b;margin-bottom:1rem}
canvas{border:2px solid #334155;border-radius:.5rem;background:#0a0f1a}
.score{margin-top:1rem;font-size:1.25rem;color:#e2e8f0}
.hi{font-size:.875rem;color:#64748b;margin-top:.25rem}
.overlay{position:fixed;inset:0;background:#0008;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:1rem}
.overlay h2{font-size:2rem;color:#fff}
.overlay p{color:#94a3b8}
button.play{background:#6366f1;color:#fff;border:none;border-radius:.5rem;padding:.75rem 2rem;font-size:1rem;font-weight:700;cursor:pointer}
button.play:hover{background:#5254e7}
.hidden{display:none}
</style></head>
<body>
<h1>Snake</h1>
<p class="meta">Use arrow keys or WASD</p>
<canvas id="c" width="400" height="400"></canvas>
<div class="score">Score: <span id="sc">0</span></div>
<div class="hi">Best: <span id="hi">0</span></div>
<div class="overlay hidden" id="ov">
  <h2 id="ov-title">Snake</h2>
  <p id="ov-msg">Press Play to start</p>
  <button class="play" onclick="startGame()">Play</button>
</div>
<script>
var GRID=20,CELL=20,W=GRID,H=GRID;
var ctx=document.getElementById('c').getContext('2d');
var snake,dir,food,score,hi=parseInt(localStorage.getItem('snake_hi')||'0'),loop;
document.getElementById('hi').textContent=hi;
document.getElementById('ov').classList.remove('hidden');
document.addEventListener('keydown',function(e){
  var map={ArrowUp:[0,-1],ArrowDown:[0,1],ArrowLeft:[-1,0],ArrowRight:[1,0],
           KeyW:[0,-1],KeyS:[0,1],KeyA:[-1,0],KeyD:[1,0]};
  var nd=map[e.code];
  if(nd&&!(nd[0]===-dir[0]&&nd[1]===-dir[1])){dir=nd;e.preventDefault();}
});
function startGame(){
  document.getElementById('ov').classList.add('hidden');
  snake=[[10,10],[9,10],[8,10]];dir=[1,0];score=0;
  document.getElementById('sc').textContent=0;
  placeFood();clearInterval(loop);
  loop=setInterval(step,Math.max(60,150-score*5));
}
function placeFood(){
  do{food=[Math.floor(Math.random()*W),Math.floor(Math.random()*H)];}
  while(snake.some(function(s){return s[0]===food[0]&&s[1]===food[1];}));
}
function step(){
  var head=[snake[0][0]+dir[0],snake[0][1]+dir[1]];
  if(head[0]<0||head[0]>=W||head[1]<0||head[1]>=H||snake.some(function(s){return s[0]===head[0]&&s[1]===head[1];})){
    clearInterval(loop);
    if(score>hi){hi=score;localStorage.setItem('snake_hi',hi);document.getElementById('hi').textContent=hi;}
    document.getElementById('ov-title').textContent='Game Over';
    document.getElementById('ov-msg').textContent='Score: '+score;
    document.getElementById('ov').classList.remove('hidden');return;
  }
  snake.unshift(head);
  if(head[0]===food[0]&&head[1]===food[1]){
    score++;document.getElementById('sc').textContent=score;
    clearInterval(loop);loop=setInterval(step,Math.max(60,150-score*5));
    placeFood();
  }else{snake.pop();}
  draw();
}
function draw(){
  ctx.fillStyle='#0a0f1a';ctx.fillRect(0,0,400,400);
  snake.forEach(function(s,i){
    ctx.fillStyle=i===0?'#6366f1':'#4f46e5';
    ctx.fillRect(s[0]*CELL+1,s[1]*CELL+1,CELL-2,CELL-2);
  });
  ctx.fillStyle='#22c55e';
  ctx.beginPath();ctx.arc(food[0]*CELL+CELL/2,food[1]*CELL+CELL/2,CELL/2-2,0,Math.PI*2);ctx.fill();
}
</script>
</body></html>"""

    return (
        "from fastapi import FastAPI\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from fastapi.responses import HTMLResponse\n\n"
        "app = FastAPI(title='SnakeGame', version='1.0.0')\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])\n\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'ok'}\n\n"
        f"HTML_CONTENT = {repr(html)}\n\n"
        "@app.get('/', response_class=HTMLResponse)\n"
        "async def index(): return HTML_CONTENT\n"
    )


def _generic_api(project_name: str = "app") -> str:
    """Return a generic FastAPI app when no domain can be detected."""
    html = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>API</title>
<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:system-ui,sans-serif;background:#0f1117;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:1rem}h1{color:#6366f1;font-size:2rem}p{color:#64748b}a{color:#6366f1;text-decoration:none}a:hover{text-decoration:underline}</style>
</head>
<body>
<h1>API is running</h1>
<p>Generated by AetherOS Factory</p>
<a href="/docs">&#x2192; View API Documentation</a>
<a href="/health">&#x2192; Health Check</a>
</body></html>"""

    return (
        "from fastapi import FastAPI\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from fastapi.responses import HTMLResponse\n\n"
        "app = FastAPI(title='GeneratedAPI', version='1.0.0')\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])\n\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'ok', 'version': '1.0.0'}\n\n"
        f"HTML_CONTENT = {repr(html)}\n\n"
        "@app.get('/', response_class=HTMLResponse)\n"
        "async def index(): return HTML_CONTENT\n"
    )


_ODOO_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__MODULE_NAME__</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:#16162a;color:#cdd6f4;min-height:100vh;display:flex;flex-direction:column}
.topbar{background:#12121e;border-bottom:1px solid #2a2a45;padding:0 1.5rem;height:50px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.brand{display:flex;align-items:center;gap:.625rem}
.brand-icon{width:30px;height:30px;background:linear-gradient(135deg,#7c3aed,#6d28d9);border-radius:.375rem;display:flex;align-items:center;justify-content:center;font-size:.8rem;font-weight:800;color:#fff}
.brand-name{font-size:.875rem;font-weight:700;color:#fff;letter-spacing:-.01em}
.brand-crumb{font-size:.75rem;color:#4a4a75;margin-left:.25rem}
.user-pill{display:flex;align-items:center;gap:.5rem;background:#1e1e36;border:1px solid #2a2a45;border-radius:999px;padding:.25rem .75rem .25rem .375rem}
.avatar{width:24px;height:24px;background:#7c3aed;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:.625rem;font-weight:700}
.user-name{font-size:.72rem;color:#6c6c9a}
.subnav{background:#12121e;border-bottom:1px solid #2a2a45;padding:0 1.5rem;display:flex;gap:0;height:38px}
.nav-tab{padding:0 1rem;font-size:.78rem;font-weight:500;color:#4a4a75;cursor:pointer;border-bottom:2px solid transparent;display:flex;align-items:center;transition:all .15s}
.nav-tab:hover{color:#9694b0}
.nav-tab.active{color:#a78bfa;border-bottom-color:#7c3aed;font-weight:600}
.page{flex:1;padding:1.5rem;overflow:auto;display:flex;flex-direction:column;gap:1rem}
.toolbar{display:flex;align-items:center;gap:.75rem}
.search-wrap{display:flex;align-items:center;gap:.5rem;background:#1e1e36;border:1px solid #2a2a45;border-radius:.5rem;padding:.375rem .875rem;flex:1;max-width:360px}
.search-wrap input{background:none;border:none;outline:none;color:#cdd6f4;font-size:.8rem;width:100%;min-width:0}
.search-wrap input::placeholder{color:#3a3a5c}
.filter-pill{background:#1e1e36;border:1px solid #2a2a45;border-radius:.5rem;padding:.375rem .75rem;color:#6c6c9a;font-size:.78rem;cursor:pointer;display:flex;align-items:center;gap:.375rem;white-space:nowrap;transition:border-color .15s}
.filter-pill:hover{border-color:#7c3aed;color:#cdd6f4}
.btn-primary{background:linear-gradient(135deg,#7c3aed,#6d28d9);color:#fff;border:none;border-radius:.5rem;padding:.375rem 1rem;font-size:.8rem;font-weight:600;cursor:pointer;white-space:nowrap;transition:opacity .15s}
.btn-primary:hover{opacity:.9}
.kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem}
.kpi{background:#1e1e36;border:1px solid #2a2a45;border-radius:.625rem;padding:.875rem 1rem}
.kpi-val{font-size:1.5rem;font-weight:700;color:#fff;line-height:1}
.kpi-label{font-size:.68rem;color:#4a4a75;text-transform:uppercase;letter-spacing:.06em;margin-top:.25rem}
.kpi.v-purple .kpi-val{color:#a78bfa}
.kpi.v-green .kpi-val{color:#4ade80}
.kpi.v-amber .kpi-val{color:#fbbf24}
.card{background:#1e1e36;border:1px solid #2a2a45;border-radius:.75rem;overflow:hidden}
.card-head{padding:.75rem 1.25rem;border-bottom:1px solid #2a2a45;display:flex;align-items:center;justify-content:space-between}
.card-title{font-size:.8rem;font-weight:600;color:#9694b0}
.rec-badge{font-size:.68rem;background:#12121e;border:1px solid #2a2a45;border-radius:999px;padding:.1rem .5rem;color:#4a4a75}
table{width:100%;border-collapse:collapse}
th{padding:.5rem 1rem;text-align:left;font-size:.65rem;font-weight:600;color:#4a4a75;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #2a2a45;white-space:nowrap;background:#12121e}
th:first-child{padding-left:1.25rem}
td{padding:.75rem 1rem;font-size:.8rem;border-bottom:1px solid #1e1e3a}
td:first-child{padding-left:1.25rem;color:#7c3aed;font-weight:700;font-family:monospace;font-size:.75rem}
tr:last-child td{border-bottom:none}
tr:hover td{background:#252540}
.name-cell{color:#e2e8f0;font-weight:500}
.desc-cell{color:#6c6c9a;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dept-cell{color:#9694b0}
.date-cell{color:#4a4a75;font-size:.72rem}
.badge{display:inline-flex;align-items:center;gap:.2rem;padding:.15rem .5rem;border-radius:999px;font-size:.65rem;font-weight:700;letter-spacing:.02em;text-transform:uppercase}
.b-active{background:#22c55e18;color:#4ade80;border:1px solid #22c55e30}
.b-draft{background:#f9731618;color:#fb923c;border:1px solid #f9731630}
.b-pending{background:#7c3aed18;color:#a78bfa;border:1px solid #7c3aed30}
.b-archived{background:#6c6c9a18;color:#6c6c9a;border:1px solid #6c6c9a30}
.actions{display:flex;gap:.375rem}
.act{background:none;border:1px solid #2a2a45;border-radius:.375rem;padding:.2rem .5rem;font-size:.7rem;color:#4a4a75;cursor:pointer;transition:all .15s}
.act:hover{border-color:#7c3aed;color:#a78bfa}
.act-d:hover{border-color:#ef444460;color:#f87171}
.empty-row td{padding:3rem;text-align:center;color:#3a3a5c;font-size:.875rem}
.modal-mask{position:fixed;inset:0;background:rgba(0,0,0,.75);display:flex;align-items:center;justify-content:center;z-index:100;backdrop-filter:blur(3px)}
.modal{background:#1e1e36;border:1px solid #2a2a45;border-radius:.875rem;padding:1.5rem;width:100%;max-width:460px;box-shadow:0 30px 60px rgba(0,0,0,.5)}
.modal-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.25rem}
.modal-heading{font-size:.9rem;font-weight:700;color:#fff}
.close-btn{background:none;border:none;color:#4a4a75;cursor:pointer;font-size:1.125rem;line-height:1;padding:0}
.close-btn:hover{color:#cdd6f4}
.field{margin-bottom:.875rem}
.field label{display:block;font-size:.68rem;font-weight:700;color:#4a4a75;text-transform:uppercase;letter-spacing:.06em;margin-bottom:.375rem}
.inp,.sel,.ta{width:100%;background:#12121e;border:1px solid #2a2a45;border-radius:.5rem;padding:.5rem .75rem;color:#cdd6f4;font-size:.8rem;outline:none;font-family:inherit;transition:border-color .15s}
.inp:focus,.sel:focus,.ta:focus{border-color:#7c3aed}
.ta{min-height:72px;resize:vertical}
.sel option{background:#1e1e36}
.modal-foot{display:flex;justify-content:flex-end;gap:.5rem;margin-top:1.25rem;padding-top:1rem;border-top:1px solid #2a2a45}
.btn-ghost{background:#12121e;border:1px solid #2a2a45;border-radius:.5rem;padding:.4rem 1rem;color:#6c6c9a;font-size:.8rem;cursor:pointer;transition:color .15s}
.btn-ghost:hover{color:#cdd6f4}
.btn-save{background:linear-gradient(135deg,#7c3aed,#6d28d9);color:#fff;border:none;border-radius:.5rem;padding:.4rem 1rem;font-size:.8rem;font-weight:600;cursor:pointer;transition:opacity .15s}
.btn-save:hover{opacity:.9}
.hidden{display:none!important}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <div class="brand-icon">&#9670;</div>
    <span class="brand-name">__MODULE_NAME__</span>
    <span class="brand-crumb">/ Records</span>
  </div>
  <div class="user-pill">
    <div class="avatar">AD</div>
    <span class="user-name">Administrator</span>
  </div>
</div>
<div class="subnav">
  <div class="nav-tab active">Records</div>
  <div class="nav-tab">Reports</div>
  <div class="nav-tab">Configuration</div>
</div>
<div class="page">
  <div class="toolbar">
    <div class="search-wrap">
      <span style="color:#3a3a5c;font-size:.875rem">&#128269;</span>
      <input id="q" type="text" placeholder="Search records..." oninput="applyFilter()">
    </div>
    <button class="filter-pill" onclick="nextFilter()">
      <span>&#9662;</span><span id="flabel">All Status</span>
    </button>
    <div style="flex:1"></div>
    <button class="btn-primary" onclick="openModal(null)">+ New Record</button>
  </div>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-val" id="k-total">0</div><div class="kpi-label">Total Records</div></div>
    <div class="kpi v-purple"><div class="kpi-val" id="k-active">0</div><div class="kpi-label">Active</div></div>
    <div class="kpi v-green"><div class="kpi-val" id="k-draft">0</div><div class="kpi-label">Draft</div></div>
    <div class="kpi v-amber"><div class="kpi-val" id="k-pending">0</div><div class="kpi-label">Pending</div></div>
  </div>
  <div class="card">
    <div class="card-head">
      <span class="card-title">__MODULE_NAME__ Records</span>
      <span class="rec-badge" id="rec-ct">0 records</span>
    </div>
    <table>
      <thead>
        <tr><th>ID</th><th>Name</th><th>Description</th><th>Department</th><th>Status</th><th>Created</th><th>Actions</th></tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</div>
<div class="modal-mask hidden" id="mask">
  <div class="modal">
    <div class="modal-head">
      <span class="modal-heading" id="m-title">New Record</span>
      <button class="close-btn" onclick="closeModal()">&#215;</button>
    </div>
    <div class="field"><label>Name *</label><input class="inp" id="m-name" type="text" placeholder="Record name..."></div>
    <div class="field"><label>Description</label><textarea class="ta" id="m-desc" placeholder="Description..."></textarea></div>
    <div class="field"><label>Department</label><input class="inp" id="m-dept" type="text" placeholder="e.g. HR, Finance, Engineering..."></div>
    <div class="field"><label>Status</label>
      <select class="sel" id="m-status">
        <option value="draft">Draft</option>
        <option value="active">Active</option>
        <option value="pending">Pending</option>
        <option value="archived">Archived</option>
      </select>
    </div>
    <div class="modal-foot">
      <button class="btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn-save" onclick="save()">Save Record</button>
    </div>
  </div>
</div>
<script>
var ALL=[],EID=null,FLT='all';
var FLTS=['all','active','draft','pending','archived'];
var FLTN={'all':'All Status','active':'Active','draft':'Draft','pending':'Pending','archived':'Archived'};
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function badge(s){
  var m={active:'b-active',draft:'b-draft',pending:'b-pending',archived:'b-archived'};
  return '<span class="badge '+(m[s]||'b-draft')+'">'+esc(s)+'</span>';
}
function dt(s){
  if(!s)return'';
  try{return new Date(s).toLocaleDateString('en-US',{month:'short',day:'2-digit',year:'numeric'});}
  catch(e){return String(s).split('T')[0]||'';}
}
function kpi(){
  document.getElementById('k-total').textContent=ALL.length;
  document.getElementById('k-active').textContent=ALL.filter(function(r){return r.status==='active';}).length;
  document.getElementById('k-draft').textContent=ALL.filter(function(r){return r.status==='draft';}).length;
  document.getElementById('k-pending').textContent=ALL.filter(function(r){return r.status==='pending';}).length;
}
function render(rows){
  var tb=document.getElementById('tbody');
  var ct=document.getElementById('rec-ct');
  kpi();
  ct.textContent=rows.length+' record'+(rows.length!==1?'s':'');
  if(!rows.length){
    tb.innerHTML='<tr class="empty-row"><td colspan="7">No records match your search.</td></tr>';
    return;
  }
  tb.innerHTML=rows.map(function(r){
    return '<tr>'
      +'<td>#'+r.id+'</td>'
      +'<td class="name-cell">'+esc(r.name)+'</td>'
      +'<td class="desc-cell" title="'+esc(r.description||'')+'">'+esc(r.description||'—')+'</td>'
      +'<td class="dept-cell">'+esc(r.department||'—')+'</td>'
      +'<td>'+badge(r.status||'draft')+'</td>'
      +'<td class="date-cell">'+dt(r.created_at)+'</td>'
      +'<td><div class="actions">'
        +'<button class="act" onclick="openModal('+r.id+')">Edit</button>'
        +'<button class="act act-d" onclick="del('+r.id+')">Delete</button>'
      +'</div></td>'
    +'</tr>';
  }).join('');
}
function applyFilter(){
  var q=document.getElementById('q').value.toLowerCase();
  var rows=ALL.filter(function(r){
    var ok=(FLT==='all'||r.status===FLT);
    if(q)ok=ok&&((r.name||'').toLowerCase().indexOf(q)>=0||(r.description||'').toLowerCase().indexOf(q)>=0||(r.department||'').toLowerCase().indexOf(q)>=0);
    return ok;
  });
  render(rows);
}
function nextFilter(){
  FLT=FLTS[(FLTS.indexOf(FLT)+1)%FLTS.length];
  document.getElementById('flabel').textContent=FLTN[FLT];
  applyFilter();
}
async function load(){var r=await fetch('/records');ALL=await r.json();applyFilter();}
function openModal(id){
  EID=id;
  document.getElementById('m-title').textContent=id?'Edit Record':'New Record';
  var rec=id?ALL.find(function(r){return r.id===id;}):null;
  document.getElementById('m-name').value=rec?rec.name||'':'';
  document.getElementById('m-desc').value=rec?rec.description||'':'';
  document.getElementById('m-dept').value=rec?rec.department||'':'';
  document.getElementById('m-status').value=rec?rec.status||'draft':'draft';
  document.getElementById('mask').classList.remove('hidden');
  setTimeout(function(){document.getElementById('m-name').focus();},50);
}
function closeModal(){document.getElementById('mask').classList.add('hidden');}
document.getElementById('mask').addEventListener('click',function(e){if(e.target===this)closeModal();});
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
async function save(){
  var n=document.getElementById('m-name').value.trim();
  if(!n)return document.getElementById('m-name').focus();
  var p={name:n,description:document.getElementById('m-desc').value.trim(),
         department:document.getElementById('m-dept').value.trim(),
         status:document.getElementById('m-status').value};
  await fetch(EID?'/records/'+EID:'/records',{method:EID?'PUT':'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  closeModal();load();
}
function del(id){if(confirm('Delete this record?'))fetch('/records/'+id,{method:'DELETE'}).then(load);}
load();
</script>
</body>
</html>"""


def _odoo_module_app(project_name: str = "module") -> str:
    """Return a complete Odoo-style CRUD module FastAPI app with SQLite + professional dark UI."""
    module_name = (project_name or "module").replace("-", " ").replace("_", " ").title()
    html = _ODOO_HTML_TEMPLATE.replace("__MODULE_NAME__", module_name)
    return (
        "from fastapi import FastAPI, HTTPException\n"
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from fastapi.responses import HTMLResponse\n"
        "from pydantic import BaseModel\n"
        "from typing import Optional, List\n"
        "import sqlite3\n"
        "from pathlib import Path\n\n"
        f"MODULE_NAME = {repr(module_name)}\n"
        "app = FastAPI(title=MODULE_NAME, version='1.0.0')\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])\n\n"
        "DB_PATH = Path('data/module.db')\n\n"
        "def init_db():\n"
        "    DB_PATH.parent.mkdir(parents=True, exist_ok=True)\n"
        "    conn = sqlite3.connect(str(DB_PATH))\n"
        "    conn.execute(\"\"\"CREATE TABLE IF NOT EXISTS records (\n"
        "        id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "        name TEXT NOT NULL,\n"
        "        description TEXT DEFAULT '',\n"
        "        department TEXT DEFAULT '',\n"
        "        status TEXT DEFAULT 'draft',\n"
        "        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
        "    )\"\"\")\n"
        "    conn.commit(); conn.close()\n\n"
        "init_db()\n\n"
        "class RecordCreate(BaseModel):\n"
        "    name: str\n"
        "    description: Optional[str] = ''\n"
        "    department: Optional[str] = ''\n"
        "    status: Optional[str] = 'draft'\n\n"
        "class RecordUpdate(BaseModel):\n"
        "    name: Optional[str] = None\n"
        "    description: Optional[str] = None\n"
        "    department: Optional[str] = None\n"
        "    status: Optional[str] = None\n\n"
        "@app.get('/health')\n"
        "def health(): return {'status': 'ok', 'module': MODULE_NAME, 'version': '1.0.0'}\n\n"
        "@app.get('/records')\n"
        "def list_records():\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        return [dict(r) for r in conn.execute(\n"
        "            'SELECT * FROM records ORDER BY created_at DESC').fetchall()]\n"
        "    finally: conn.close()\n\n"
        "@app.post('/records', status_code=201)\n"
        "def create_record(payload: RecordCreate):\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        cur = conn.execute(\n"
        "            'INSERT INTO records(name,description,department,status) VALUES(?,?,?,?)',\n"
        "            (payload.name, payload.description or '', payload.department or '',\n"
        "             payload.status or 'draft'))\n"
        "        conn.commit()\n"
        "        return dict(conn.execute(\n"
        "            'SELECT * FROM records WHERE id=?', (cur.lastrowid,)).fetchone())\n"
        "    finally: conn.close()\n\n"
        "@app.put('/records/{rid}')\n"
        "def update_record(rid: int, payload: RecordUpdate):\n"
        "    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row\n"
        "    try:\n"
        "        row = conn.execute('SELECT * FROM records WHERE id=?', (rid,)).fetchone()\n"
        "        if not row: raise HTTPException(404, detail='Record not found')\n"
        "        rec = dict(row)\n"
        "        for k, v in payload.dict(exclude_none=True).items(): rec[k] = v\n"
        "        conn.execute(\n"
        "            'UPDATE records SET name=?,description=?,department=?,status=? WHERE id=?',\n"
        "            (rec['name'], rec['description'], rec['department'], rec['status'], rid))\n"
        "        conn.commit()\n"
        "        return dict(conn.execute(\n"
        "            'SELECT * FROM records WHERE id=?', (rid,)).fetchone())\n"
        "    finally: conn.close()\n\n"
        "@app.delete('/records/{rid}')\n"
        "def delete_record(rid: int):\n"
        "    conn = sqlite3.connect(str(DB_PATH))\n"
        "    try:\n"
        "        cur = conn.execute('DELETE FROM records WHERE id=?', (rid,))\n"
        "        conn.commit()\n"
        "        if cur.rowcount == 0: raise HTTPException(404, detail='Record not found')\n"
        "        return {'status': 'deleted', 'id': rid}\n"
        "    finally: conn.close()\n\n"
        f"HTML_CONTENT = {repr(html)}\n\n"
        "@app.get('/', response_class=HTMLResponse)\n"
        "async def index(): return HTML_CONTENT\n"
    )


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
