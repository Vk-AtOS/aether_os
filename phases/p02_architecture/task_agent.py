"""P02 Task Agent — design architecture using sequential LLM calls."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)

ARCHITECTURE_SCHEMA = {
    "tech_stack": {
        "backend": "FastAPI",
        "frontend": "React",
        "database": "PostgreSQL",
        "cache": "Redis",
        "queue": "None",
        "deployment": "Docker",
        "monitoring": "Prometheus"
    },
    "component_diagram": "graph TD\n  Client --> API\n  API --> DB",
    "database_schema": [
        {"table": "users", "columns": ["id", "email", "password_hash"]}
    ],
    "api_endpoints": [
        {"method": "GET", "path": "/health", "description": "Health check", "auth": False}
    ],
    "data_flow": "sequenceDiagram\n  Client->>API: Request\n  API->>DB: Query",
    "security_considerations": [
        "JWT authentication",
        "Input validation"
    ],
    "scalability_notes": "Horizontally scalable via Docker"
}

TECH_STACK_DEFAULTS = {
    "backend": "FastAPI",
    "frontend": "React", 
    "database": "PostgreSQL",
    "cache": "None",
    "queue": "None",
    "deployment": "Docker",
    "monitoring": "Prometheus"
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
            {"method": "GET", "path": "/health", "description": "Health check", "auth": False}
        ]
    return result

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    requirements = data.get("requirements_doc", data.get("structured_requirements", str(data)))
    llm = get_llm_client()

    prompt = f"Design a complete software architecture for the following requirements:\n\n{requirements}"
    
    # Use call_structured with the requested schema
    doc = await llm.call_structured(
        prompt=prompt,
        schema_example=ARCHITECTURE_SCHEMA,
        task_type="architecture"
    )

    # Apply defaults and fix missing sections
    doc = fix_tech_stack(doc)

    out_json = output_dir / "architecture.json"
    out_md = output_dir / "architecture.md"
    out_json.write_text(json.dumps(doc, indent=2))

    # Generate Markdown summary for humans
    stack = doc.get("tech_stack", {})
    md = [f"# Architecture\n\n## Tech Stack\n"]
    for k, v in stack.items():
        md.append(f"- **{k}**: {v}")
    
    if doc.get("component_diagram"):
        md.append(f"\n## Component Diagram\n```mermaid\n{doc['component_diagram']}\n```")
    
    md.append(f"\n## API Endpoints\n")
    for ep in doc.get("api_endpoints", []):
        md.append(f"- `{ep.get('method','GET')} {ep.get('path','')}` — {ep.get('description','')}")
    
    md.append(f"\n## Security\n")
    for s in doc.get("security_considerations", []):
        md.append(f"- {s}")
    
    md.append(f"\n## Scalability\n{doc.get('scalability_notes','')}")
    out_md.write_text("\n".join(md))

    return TaskResult(
        output_path=str(out_json),
        confidence=0.9,
        metadata={"json_path": str(out_json), "markdown_path": str(out_md)},
        issues=[],
        success=True,
    )
