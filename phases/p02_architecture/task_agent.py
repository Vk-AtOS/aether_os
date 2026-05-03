"""P02 Task Agent — design architecture using sequential LLM calls.

Guarantees: architecture.json is ALWAYS written, even when the LLM is
unavailable.  The fallback produces a domain-aware schema derived from
the raw_input text (not a generic hello-world placeholder).
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)

ARCHITECTURE_SCHEMA = {
    "domain": "general",
    "tech_stack": {
        "backend": "FastAPI",
        "frontend": "React",
        "database": "PostgreSQL",
        "cache": "None",
        "queue": "None",
        "deployment": "Docker",
        "monitoring": "Prometheus",
    },
    "component_diagram": "graph TD\n  Client --> API\n  API --> DB",
    "database_schema": [
        {"table": "users", "columns": ["id", "email", "password_hash", "created_at"]}
    ],
    "api_endpoints": [
        {"method": "GET",    "path": "/health",  "description": "Health check",   "auth": False},
        {"method": "GET",    "path": "/items",   "description": "List items",      "auth": True},
        {"method": "POST",   "path": "/items",   "description": "Create item",     "auth": True},
        {"method": "GET",    "path": "/items/{id}", "description": "Get item",     "auth": True},
        {"method": "PUT",    "path": "/items/{id}", "description": "Update item",  "auth": True},
        {"method": "DELETE", "path": "/items/{id}", "description": "Delete item",  "auth": True},
    ],
    "data_flow": "sequenceDiagram\n  Client->>API: Request\n  API->>DB: Query\n  DB-->>API: Result\n  API-->>Client: Response",
    "security_considerations": ["JWT authentication", "Input validation", "Rate limiting"],
    "scalability_notes": "Horizontally scalable via Docker Compose",
}

TECH_STACK_DEFAULTS = {
    "backend": "FastAPI",
    "frontend": "React",
    "database": "PostgreSQL",
    "cache": "None",
    "queue": "None",
    "deployment": "Docker",
    "monitoring": "Prometheus",
}

# Common domain nouns → CRUD resource detection
_DOMAIN_KEYWORDS = {
    "todo":      ("todos",    ["id", "title", "description", "completed", "created_at", "user_id"]),
    "task":      ("tasks",    ["id", "title", "description", "status", "priority", "due_date", "user_id"]),
    "user":      ("users",    ["id", "email", "password_hash", "name", "created_at"]),
    "product":   ("products", ["id", "name", "description", "price", "stock", "category_id"]),
    "order":     ("orders",   ["id", "user_id", "status", "total", "created_at"]),
    "item":      ("items",    ["id", "name", "description", "quantity", "price"]),
    "post":      ("posts",    ["id", "title", "content", "author_id", "published_at"]),
    "comment":   ("comments", ["id", "post_id", "author_id", "content", "created_at"]),
    "blog":      ("posts",    ["id", "title", "content", "author_id", "tags", "published_at"]),
    "article":   ("articles", ["id", "title", "body", "author_id", "published_at"]),
    "category":  ("categories", ["id", "name", "description", "parent_id"]),
    "inventory": ("inventory", ["id", "product_id", "quantity", "location", "updated_at"]),
    "customer":  ("customers", ["id", "name", "email", "phone", "address"]),
    "employee":  ("employees", ["id", "name", "email", "role", "department", "hired_at"]),
    "event":     ("events",   ["id", "title", "description", "start_at", "end_at", "location"]),
    "message":   ("messages", ["id", "sender_id", "recipient_id", "content", "sent_at"]),
    "payment":   ("payments", ["id", "order_id", "amount", "status", "method", "created_at"]),
    "booking":   ("bookings", ["id", "user_id", "resource_id", "start_at", "end_at", "status"]),
    "review":    ("reviews",  ["id", "user_id", "product_id", "rating", "content", "created_at"]),
    "report":    ("reports",  ["id", "title", "data", "generated_by", "created_at"]),
}


def _extract_resources(raw_input: str) -> List[Dict]:
    """
    Parse raw_input to detect domain nouns and build a rich resource list.
    Returns a list of {"resource": str, "table": str, "columns": [...]} dicts.
    """
    lower = raw_input.lower()
    found = []
    seen_tables: set = set()

    for keyword, (table, columns) in _DOMAIN_KEYWORDS.items():
        if keyword in lower and table not in seen_tables:
            found.append({"resource": keyword, "table": table, "columns": columns})
            seen_tables.add(table)

    # Fallback: extract bare nouns from the sentence if nothing matched
    if not found:
        words = re.findall(r'\b([a-z]{3,})\b', lower)
        stop_words = {"the", "and", "for", "are", "with", "that", "this",
                      "from", "have", "will", "can", "but", "not", "build",
                      "create", "make", "using", "api", "app", "rest", "web",
                      "system", "service", "python", "fastapi", "django"}
        candidates = [w for w in dict.fromkeys(words) if w not in stop_words][:3]
        for noun in candidates:
            table = noun + "s" if not noun.endswith("s") else noun
            found.append({
                "resource": noun,
                "table": table,
                "columns": ["id", "name", "description", "created_at"],
            })

    return found


def _build_fallback_architecture(raw_input: str, domain: str = "general") -> dict:
    """
    Build a domain-aware architecture dict when the LLM is unavailable.
    Never returns a generic hello-world — always reflects the requirement.
    """
    from aether_os.core.domain_engine import get_domain_profile
    profile = get_domain_profile(domain)
    
    resources = _extract_resources(raw_input)
    primary = resources[0] if resources else {"resource": "item", "table": "items",
                                               "columns": ["id", "name", "created_at"]}

    # Database schema: one table per detected resource + users
    db_schema = []
    seen = set()
    for r in resources:
        if r["table"] not in seen:
            db_schema.append({"table": r["table"], "columns": r["columns"]})
            seen.add(r["table"])
    if "users" not in seen:
        db_schema.append({"table": "users",
                          "columns": ["id", "email", "password_hash", "created_at"]})

    # API endpoints: full CRUD for primary resource + auth + health
    res_name  = primary["resource"]
    res_table = primary["table"]
    endpoints = [
        {"method": "GET",    "path": "/health",
         "description": "Health check", "auth": False},
        {"method": "POST",   "path": "/auth/register",
         "description": "Register user", "auth": False},
        {"method": "POST",   "path": "/auth/login",
         "description": "Login and get JWT token", "auth": False},
        {"method": "GET",    "path": f"/{res_table}",
         "description": f"List all {res_table}", "auth": True},
        {"method": "POST",   "path": f"/{res_table}",
         "description": f"Create a new {res_name}", "auth": True},
        {"method": "GET",    "path": f"/{res_table}/{{id}}",
         "description": f"Get {res_name} by ID", "auth": True},
        {"method": "PUT",    "path": f"/{res_table}/{{id}}",
         "description": f"Update {res_name}", "auth": True},
        {"method": "DELETE", "path": f"/{res_table}/{{id}}",
         "description": f"Delete {res_name}", "auth": True},
    ]
    # Add secondary resource endpoints
    for r in resources[1:3]:
        endpoints.append({
            "method": "GET", "path": f"/{r['table']}",
            "description": f"List all {r['table']}", "auth": True,
        })
        endpoints.append({
            "method": "POST", "path": f"/{r['table']}",
            "description": f"Create {r['resource']}", "auth": True,
        })

    stack = {**TECH_STACK_DEFAULTS, **profile.suggested_tech_stack}
    db_type = stack.get("database", "PostgreSQL")

    component_diagram = (
        f"graph TD\n"
        f"  Client --> API[FastAPI]\n"
        f"  API --> DB[({db_type})]\n"
        f"  API --> Auth[JWT Auth]\n"
        f"  subgraph Resources\n"
        + "".join(f"    API --> {r['table'].title()}[{r['table'].title()}]\n"
                  for r in resources[:4])
        + "  end"
    )

    return {
        "tech_stack": stack,
        "component_diagram": component_diagram,
        "database_schema": db_schema,
        "api_endpoints": endpoints,
        "data_flow": (
            "sequenceDiagram\n"
            "  Client->>API: HTTP Request\n"
            "  API->>Auth: Validate JWT\n"
            "  Auth-->>API: Payload\n"
            f"  API-->>{res_table.title()}Service: Business Logic\n"
            f"  {res_table.title()}Service->>DB: SQL Query\n"
            f"  DB-->>{res_table.title()}Service: Rows\n"
            f"  {res_table.title()}Service-->>API: Result\n"
            "  API-->>Client: JSON Response"
        ),
        "security_considerations": profile.security_requirements + [
            "Pydantic input validation on all endpoints",
            "SQL injection prevention via ORM",
        ],
        "scalability_notes": (
            f"Stateless FastAPI app — scale horizontally behind nginx. "
            f"{db_type} with read replicas for {res_table}. "
        ),
        "_fallback": True,
        "_detected_resources": [r["resource"] for r in resources],
        "domain": domain
    }


def fix_tech_stack(result: dict) -> dict:
    ts = result.get("tech_stack", {})
    if not isinstance(ts, dict):
        ts = {}
    for k, v in TECH_STACK_DEFAULTS.items():
        if not ts.get(k):
            ts[k] = v
    result["tech_stack"] = ts
    if not result.get("api_endpoints"):
        result["api_endpoints"] = [
            {"method": "GET", "path": "/health",
             "description": "Health check", "auth": False}
        ]
    return result


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data        = phase_input.input_data
    raw_input   = data.get("raw_input", "")
    requirements = data.get("requirements_doc",
                            data.get("structured_requirements", raw_input or str(data)))
    domain = data.get("domain", "general")

    from aether_os.core.domain_engine import get_domain_profile
    profile = get_domain_profile(domain)

    out_json = output_dir / "architecture.json"
    out_md   = output_dir / "architecture.md"
    used_fallback = False

    # ── Attempt LLM-generated architecture ───────────────────────────────────
    doc: dict = {}
    try:
        llm    = get_llm_client()
        prompt = (
            f"Design a complete software architecture for the following requirements:\n\n"
            f"{requirements}\n\n"
            f"Domain: {profile.name}\n"
            f"Preferred Database: {profile.preferred_db}\n"
            f"Suggested Stack: {json.dumps(profile.suggested_tech_stack)}\n"
            f"Mandatory Patterns: {', '.join(profile.required_patterns)}\n"
            f"Security: {', '.join(profile.security_requirements)}\n"
            f"Example Entities to consider: {', '.join(profile.example_entities)}\n\n"
            f"Focus on: tech stack choices, database schema, API endpoints, security."
        )
        # Seed the schema example with domain defaults
        schema_example = dict(ARCHITECTURE_SCHEMA)
        schema_example["domain"] = domain
        schema_example["tech_stack"] = {**TECH_STACK_DEFAULTS, **profile.suggested_tech_stack}
        if "database" in profile.suggested_tech_stack:
            schema_example["tech_stack"]["database"] = profile.suggested_tech_stack["database"]
        schema_example["security_considerations"] = profile.security_requirements + ["Input validation"]
        
        doc = await llm.call_structured(
            prompt=prompt,
            schema_example=schema_example,
            task_type="architecture",
        )
        # call_structured never raises but may return the schema example on total failure
        # Detect total failure: if parse_error flag is set or doc is identical to schema
        if doc.get("parse_error") or doc.get("tech_stack") == ARCHITECTURE_SCHEMA["tech_stack"]:
            raise ValueError("LLM returned unparseable response")
    except Exception as e:
        logger.warning("[p02] LLM call failed (%s), using intelligent fallback", e)
        doc = {}
        used_fallback = True

    # ── Apply fallback if LLM produced nothing useful ────────────────────────
    if not doc or not doc.get("api_endpoints") or used_fallback:
        fallback = _build_fallback_architecture(raw_input or requirements, domain=domain)
        # Merge: keep any valid LLM fields, fill gaps with fallback
        for key, val in fallback.items():
            if not doc.get(key):
                doc[key] = val
        used_fallback = True

    doc = fix_tech_stack(doc)

    # ── Always write architecture.json ───────────────────────────────────────
    out_json.write_text(json.dumps(doc, indent=2))
    logger.info("[p02] architecture.json written (%d endpoints, fallback=%s)",
                len(doc.get("api_endpoints", [])), used_fallback)

    # ── Human-readable Markdown ───────────────────────────────────────────────
    stack = doc.get("tech_stack", {})
    md = ["# Architecture\n\n## Tech Stack\n"]
    for k, v in stack.items():
        md.append(f"- **{k}**: {v}")
    if doc.get("component_diagram"):
        md.append(f"\n## Component Diagram\n```mermaid\n{doc['component_diagram']}\n```")
    md.append("\n## API Endpoints\n")
    for ep in doc.get("api_endpoints", []):
        auth_label = " [auth]" if ep.get("auth") else ""
        md.append(f"- `{ep.get('method','GET')} {ep.get('path','')}`{auth_label} — {ep.get('description','')}")
    if doc.get("database_schema"):
        md.append("\n## Database Schema\n")
        for tbl in doc["database_schema"]:
            cols = ", ".join(tbl.get("columns", []))
            md.append(f"- **{tbl.get('table','')}**: {cols}")
    md.append("\n## Security\n")
    for s in doc.get("security_considerations", []):
        md.append(f"- {s}")
    md.append(f"\n## Scalability\n{doc.get('scalability_notes', '')}")
    if used_fallback:
        md.append(f"\n\n> ⚠️ Architecture generated from fallback (LLM unavailable). "
                  f"Detected resources: {doc.get('_detected_resources', [])}")
    out_md.write_text("\n".join(md))

    return TaskResult(
        output_path=str(out_json),
        confidence=0.7 if used_fallback else 0.9,
        metadata={
            "json_path": str(out_json),
            "markdown_path": str(out_md),
            "used_fallback": used_fallback,
            "endpoint_count": len(doc.get("api_endpoints", [])),
        },
        issues=["Used fallback architecture (LLM unavailable)"] if used_fallback else [],
        success=True,   # always True — architecture.json always written
    )
