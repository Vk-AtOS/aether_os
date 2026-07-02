"""P10 Documentation & Delivery — generates README, API reference, architecture
overview, and deployment guide for the completed project, then triggers the
client portal and optional change-request workflow."""
from __future__ import annotations
import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_SUBTASK_TIMEOUT = 180.0


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_src_dir(data: dict) -> Optional[Path]:
    for key in ("backend_src_dir", "main_py"):
        val = data.get(key, "")
        if val:
            p = Path(val)
            if p.is_file():
                p = p.parent
            if p.is_dir() and (p / "main.py").exists():
                return p
    project_dir = data.get("project_dir", "")
    if project_dir:
        candidates = sorted(Path(project_dir).rglob("main.py"), key=lambda x: len(x.parts))
        if candidates:
            return candidates[-1].parent
    return None


def _read_safe(path: Path, limit: int = 3000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except Exception:
        return ""


def _extract_routes(main_py: str) -> List[str]:
    """Pull HTTP method + path from FastAPI decorators."""
    return re.findall(r'@(?:app|router)\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']', main_py)


def _extract_models(models_py: str) -> List[str]:
    """Extract SQLAlchemy model class names."""
    return re.findall(r'^class\s+(\w+)\s*\(', models_py, re.MULTILINE)


# ── Documentation generator ────────────────────────────────────────────────────

async def _generate_docs(
    data: dict,
    src_dir: Optional[Path],
    output_dir: Path,
    llm,
) -> TaskResult:
    """Generate README, API reference, architecture doc, and deployment guide."""
    output_dir.mkdir(parents=True, exist_ok=True)

    project_name = data.get("project_name", "App")
    domain = data.get("domain", "general")
    tech_stack = data.get("tech_stack", "FastAPI + PostgreSQL + React")

    # Gather source context for the LLM
    main_py      = _read_safe(src_dir / "main.py")      if src_dir else ""
    models_py    = _read_safe(src_dir / "models.py")    if src_dir else ""
    schemas_py   = _read_safe(src_dir / "schemas.py",   2000) if src_dir else ""
    routes       = _extract_routes(main_py)
    model_names  = _extract_models(models_py)

    routes_text = "\n".join(f"  {m.upper()} {p}" for m, p in routes) or "  (no routes extracted)"
    models_text = ", ".join(model_names) or "(no models extracted)"

    arch_json = data.get("architecture", {})
    if isinstance(arch_json, str):
        try:
            arch_json = json.loads(arch_json)
        except Exception:
            arch_json = {}
    entities = arch_json.get("entities", data.get("entities", []))
    entities_text = ", ".join(e.get("name", str(e)) for e in entities[:12]) if entities else models_text

    prompt = f"""\
Generate comprehensive technical documentation for "{project_name}" ({domain}).

Project overview:
- Tech stack: {tech_stack}
- Domain: {domain}
- Data models: {entities_text}

API Routes detected:
{routes_text}

SQLAlchemy models (first 1500 chars):
{models_py[:1500]}

Schemas (first 800 chars):
{schemas_py[:800]}

Generate a JSON object with these exact keys:
{{
  "README.md": "<full markdown README with: Overview, Features, Tech Stack, Prerequisites, Local Setup, Environment Variables, Running, API Summary, Architecture, Deployment>",
  "docs/API_REFERENCE.md": "<full API reference markdown with every endpoint: method, path, auth, request body, response schema, example curl>",
  "docs/ARCHITECTURE.md": "<architecture overview: system design, component diagram as ASCII, data flow, key design decisions>",
  "docs/DEPLOYMENT.md": "<deployment guide: Docker Compose, environment variables table, production checklist, health checks, scaling notes>",
  "docs/SCHEMA.md": "<data model reference: each entity with fields, types, relationships, example JSON payloads>"
}}

All sections must be thorough, production-quality, and specific to this project.
Return ONLY the JSON object, no markdown fences."""

    files: Dict[str, str] = {}
    try:
        raw = await llm.call(prompt, task_type="documentation", max_tokens=8000)
        # Strip markdown fences if present
        raw = re.sub(r'^```(?:json)?\s*', '', raw.strip())
        raw = re.sub(r'\s*```$', '', raw.strip())
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            files = parsed
    except Exception as exc:
        logger.warning("[p10] LLM docs generation failed (%s), using template fallback", exc)

    # Template fallback when LLM fails or returns bad JSON
    if not files.get("README.md"):
        files["README.md"] = _template_readme(project_name, domain, tech_stack, routes_text, entities_text)
    if not files.get("docs/API_REFERENCE.md"):
        files["docs/API_REFERENCE.md"] = _template_api_ref(project_name, routes)
    if not files.get("docs/ARCHITECTURE.md"):
        files["docs/ARCHITECTURE.md"] = _template_architecture(project_name, domain, entities_text)
    if not files.get("docs/DEPLOYMENT.md"):
        files["docs/DEPLOYMENT.md"] = _template_deployment(project_name)
    if not files.get("docs/SCHEMA.md"):
        files["docs/SCHEMA.md"] = _template_schema(project_name, model_names, models_py[:2000])

    # Write files to disk
    written = []
    for rel_path, content in files.items():
        out = output_dir / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        written.append(str(out))
        logger.info("[p10] wrote %s (%d chars)", rel_path, len(content))

    summary = {
        "files": {k: v for k, v in files.items()},
        "files_written": written,
        "project": project_name,
    }
    summary_path = output_dir / "docs_summary.json"
    summary_path.write_text(json.dumps({k: len(v) for k, v in files.items()}, indent=2))

    return TaskResult(
        output_path=str(summary_path),
        confidence=0.9 if files else 0.5,
        metadata={"files_written": len(written), "project": project_name, "files": {k: len(v) for k, v in files.items()}},
        success=bool(files),
        issues=[] if files else ["Documentation generation produced no files"],
    )


# ── Template fallbacks ─────────────────────────────────────────────────────────

def _template_readme(name: str, domain: str, stack: str, routes: str, entities: str) -> str:
    return f"""# {name}

> AI-generated full-stack application for the **{domain}** domain.

## Overview
{name} is a production-ready web application built with {stack}.
It provides a complete API backend with authentication, CRUD operations, and a React frontend.

## Features
- JWT authentication with refresh tokens
- Role-based access control (admin / user)
- Full CRUD for: {entities}
- Structured JSON logging + Prometheus metrics
- Docker Compose deployment

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy (async) |
| Database | PostgreSQL |
| Auth | JWT (access + refresh tokens, bcrypt) |
| Frontend | React + Vite + TanStack Router |
| Monitoring | Prometheus + Grafana |
| Container | Docker + Docker Compose |

## Prerequisites
- Python 3.11+
- Node.js 20+
- Docker & Docker Compose
- PostgreSQL 15+

## Local Setup

```bash
# Clone and enter
git clone <repo-url> && cd {name.lower().replace(" ", "-")}

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # edit DATABASE_URL, SECRET_KEY
alembic upgrade head
python -m uvicorn src.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `SECRET_KEY` | Yes | JWT signing secret (min 32 chars) |
| `ADMIN_PASSWORD` | No | Admin user password (auto-generated if unset) |
| `CORS_ORIGINS` | Yes | Allowed frontend origins |

## API Summary
```
{routes}
```

## Architecture
See `docs/ARCHITECTURE.md` for system design and data flow.

## Deployment
See `docs/DEPLOYMENT.md` for Docker Compose and production checklist.

## Generated By
[AetherOS](https://aetheros.ai) — Autonomous AI App Factory
"""


def _template_api_ref(name: str, routes: List) -> str:
    lines = [f"# {name} — API Reference\n\nBase URL: `http://localhost:8000/api`\n\n## Authentication\n",
             "All endpoints (except `/auth/login` and `/auth/register`) require:\n```\nAuthorization: Bearer <access_token>\n```\n\n## Endpoints\n"]
    for method, path in routes:
        lines.append(f"### {method.upper()} {path}\n\n**Auth required:** Yes\n\n**Response:** `200 OK`\n\n---\n")
    return "\n".join(lines)


def _template_architecture(name: str, domain: str, entities: str) -> str:
    return f"""# {name} — Architecture

## System Overview
{name} follows a standard three-tier architecture:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   React/Vite    │───▶│   FastAPI       │───▶│  PostgreSQL     │
│   Frontend      │    │   Backend       │    │  Database       │
│   (Port 5173)   │    │   (Port 8000)   │    │  (Port 5432)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                               │
                               ▼
                       ┌─────────────────┐
                       │   Prometheus    │
                       │   (Port 9090)   │
                       └─────────────────┘
```

## Domain: {domain}

## Data Models
Entities: {entities}

## Key Design Decisions
- **Async SQLAlchemy** — non-blocking DB operations via asyncpg
- **JWT with refresh tokens** — short-lived access (15min) + long-lived refresh (7d)
- **CORS** — configured per environment via `CORS_ORIGINS` env var
- **Structured logging** — JSON output for log aggregation pipelines
"""


def _template_deployment(name: str) -> str:
    slug = name.lower().replace(" ", "-")
    return f"""# {name} — Deployment Guide

## Docker Compose (Recommended)

```bash
# Copy and configure environment
cp .env.example .env
# Set: DATABASE_URL, SECRET_KEY, CORS_ORIGINS

docker compose up -d
# App available at http://localhost:8000
```

## Environment Variables
| Variable | Example | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@db:5432/{slug}` | Required |
| `SECRET_KEY` | `$(openssl rand -hex 32)` | Min 32 chars |
| `CORS_ORIGINS` | `https://yourdomain.com` | Comma-separated |
| `ENVIRONMENT` | `production` | Enables strict security |

## Production Checklist
- [ ] Set `ENVIRONMENT=production`
- [ ] Use a strong `SECRET_KEY` (openssl rand -hex 32)
- [ ] Set `CORS_ORIGINS` to your actual domain
- [ ] Configure database backups
- [ ] Set up SSL/TLS termination (nginx or Traefik)
- [ ] Configure Prometheus alerting

## Health Check
```
GET /health  →  200 {{"status": "ok"}}
GET /metrics →  Prometheus metrics
```

## Scaling
- Horizontal: run multiple API replicas behind a load balancer
- Database: enable read replicas for read-heavy workloads
"""


def _template_schema(name: str, models: List[str], models_py_snippet: str) -> str:
    return f"""# {name} — Data Schema Reference

## Models
{', '.join(models) if models else 'See models.py'}

## Source (SQLAlchemy)
```python
{models_py_snippet}
```

## Admin User
Default admin created on first boot:
- Email: `admin@example.com`
- Password: logged to stdout on first run (look for `Seeded admin user:` in logs)
"""


# ── Main entry point ───────────────────────────────────────────────────────────

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, TaskResult] = {}

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    src_dir = _find_src_dir(data)

    # Sub-task 1: Documentation (real generator — not p09)
    try:
        from aether_os.core.llm.client import LLMClient
        llm = LLMClient()
        sub_dir = output_dir / "docs"
        r = await asyncio.wait_for(
            _generate_docs(data, src_dir, sub_dir, llm),
            timeout=_SUBTASK_TIMEOUT,
        )
        results["documentation"] = r
        if r.success:
            phase_input.input_data["docs_path"] = r.output_path
        logger.info("[p10] documentation: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("[p10] documentation timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as exc:
        logger.warning("[p10] documentation failed (non-critical): %s", exc)

    # Sub-task 2: Client portal
    try:
        from aether_os.phases.p14_client_portal.task_agent import run as portal_run
        sub_dir = output_dir / "client_portal"
        r = await asyncio.wait_for(portal_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT)
        results["client_portal"] = r
        logger.info("[p10] client_portal: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("[p10] client_portal timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as exc:
        logger.warning("[p10] client_portal failed (non-critical): %s", exc)

    # Sub-task 3: Change requests (optional phase, graceful if absent)
    try:
        from aether_os.phases.p15_change_requests.task_agent import run as cr_run  # type: ignore[import]
        sub_dir = output_dir / "change_requests"
        r = await asyncio.wait_for(cr_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT)
        results["change_requests"] = r
        logger.info("[p10] change_requests: %s", r.output_path)
    except ImportError:
        pass  # p15 is optional
    except asyncio.TimeoutError:
        logger.warning("[p10] change_requests timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as exc:
        logger.warning("[p10] change_requests failed (non-critical): %s", exc)

    # Problem 70: check for docs at the canonical paths under p10_docs_delivery/docs/
    docs_dir = output_dir / "docs"
    _p70_issues = []
    # README.md is written as "README.md" key → docs_dir/README.md
    _readme_path = docs_dir / "README.md"
    # API_REFERENCE.md is written as "docs/API_REFERENCE.md" key → docs_dir/docs/API_REFERENCE.md
    _api_ref_path = docs_dir / "docs" / "API_REFERENCE.md"
    # Also accept flattened path docs_dir/API_REFERENCE.md (in case LLM used flat key)
    _api_ref_alt = docs_dir / "API_REFERENCE.md"

    if not _readme_path.exists():
        _p70_issues.append(f"README.md missing at {_readme_path}")
    if not _api_ref_path.exists() and not _api_ref_alt.exists():
        _p70_issues.append(f"API_REFERENCE.md missing at {_api_ref_path} or {_api_ref_alt}")

    if _p70_issues:
        logger.warning("[p10] gate check issues: %s", _p70_issues)

    # Add quality_report.json to handoff package with error_registry summary
    try:
        from aether_os.core.error_registry import get_registry
        _reg = get_registry()
        _quality_report = {
            "error_registry_summary": _reg.get_summary(),
            "phase_confidence": data.get("phase_confidence", {}),
            "low_confidence_phases": data.get("low_confidence_phases", []),
            "governor_report": data.get("governor_report", {}),
            "generated_at": datetime.utcnow().isoformat(),
        }
        (output_dir / "quality_report.json").write_text(
            json.dumps(_quality_report, indent=2, default=str)
        )
        logger.info("p10: quality_report.json written to handoff package")
    except Exception as _qr_exc:
        logger.warning("p10: quality_report.json failed (non-fatal): %s", _qr_exc)

    summary = {
        "phases": {
            k: {"output_path": v.output_path, "success": v.success, "confidence": v.confidence}
            for k, v in results.items()
        },
        "docs_dir": str(docs_dir),
        "readme_path": str(_readme_path),
        "api_ref_path": str(_api_ref_path),
        "gate_issues": _p70_issues,
    }
    summary_path = output_dir / "consolidated.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    any_success = any(v.success for v in results.values())
    all_issues = _p70_issues if not any_success else []
    return TaskResult(
        output_path=str(summary_path),
        confidence=0.9 if any_success and not _p70_issues else 0.5,
        metadata=summary,
        success=any_success or bool(results),
        issues=all_issues,
    )
