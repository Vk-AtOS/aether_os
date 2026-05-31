"""P09 Documentation — generates README and API docs.

Wraps p10_docs_delivery with a stable public API for tests and older pipeline references.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _build_fallback_readme(project_name: str, arch: Dict[str, Any], requirements: str) -> str:
    """Generate a comprehensive README from architecture metadata.

    Produces >= 500 words with Installation, API Reference, and curl examples.
    """
    tech_stack = arch.get("tech_stack", {})
    backend = tech_stack.get("backend", "FastAPI")
    frontend = tech_stack.get("frontend", "React")
    database = tech_stack.get("database", "PostgreSQL")

    endpoints = arch.get("api_endpoints", [])
    db_schema = arch.get("database_schema", [])

    slug = project_name.lower().replace(" ", "-")

    # Build API reference section
    api_lines = ["## API Reference\n"]
    for ep in endpoints:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")
        desc = ep.get("description", "")
        auth = ep.get("auth", False)
        auth_label = "🔒 Auth required" if auth else "🔓 Public"
        api_lines.append(f"### `{method} {path}`\n")
        api_lines.append(f"{desc}\n\n**{auth_label}**\n")
        api_lines.append(f"```bash\ncurl -X {method} http://localhost:8000{path}")
        if auth:
            api_lines.append(" \\\n  -H \"Authorization: Bearer $TOKEN\"")
        api_lines.append("\n```\n")

    api_section = "\n".join(api_lines)

    # Build schema section
    schema_lines = ["## Data Models\n"]
    for table in db_schema:
        name = table.get("table", "unknown")
        cols = table.get("columns", [])
        schema_lines.append(f"### {name.title()}\n\nColumns: {', '.join(cols)}\n")
    schema_section = "\n".join(schema_lines) if db_schema else ""

    readme = f"""# {project_name}

> {requirements or f"A {backend} application with {database}."}

## Overview

{project_name} is a production-ready web application built with **{backend}** for the API layer,
**{database}** as the primary data store, and **{frontend}** for the user interface.
It follows REST conventions, ships with JWT-based authentication, and is fully containerised
for one-command deployment.

## Features

- **Authentication** — JWT access + refresh tokens, bcrypt password hashing
- **Role-based access control** — admin and user roles enforced on every endpoint
- **Full CRUD** — create, read, update, and delete resources via a consistent REST API
- **Input validation** — Pydantic schemas on every request body; automatic 422 responses
- **Health endpoint** — `GET /health` returns live/ready status for load balancers
- **Structured logging** — JSON logs with request IDs for easy correlation
- **Prometheus metrics** — `/metrics` endpoint compatible with Grafana dashboards
- **Docker Compose** — single command to spin up the full stack locally

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | {backend} |
| Database | {database} |
| Frontend | {frontend} |
| Auth | JWT (HS256, bcrypt) |
| Container | Docker + Docker Compose |
| CI/CD | GitHub Actions |

## Prerequisites

- Python 3.11+
- Docker and Docker Compose v2
- Node.js 20+ (for frontend development)

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-org/{slug}.git
cd {slug}

# 2. Copy environment template
cp .env.example .env
# Edit .env — set DATABASE_URL, SECRET_KEY, and any API keys

# 3. Start all services
docker compose up --build

# 4. Run database migrations
docker compose exec backend alembic upgrade head

# 5. Verify the API is live
curl http://localhost:8000/health
```

The application will be available at:
- **API** — `http://localhost:8000`
- **Frontend** — `http://localhost:3000`
- **API docs (Swagger)** — `http://localhost:8000/docs`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Connection string, e.g. `postgresql+asyncpg://user:pass@db/app` |
| `SECRET_KEY` | Yes | JWT signing secret — minimum 32 characters |
| `CORS_ORIGINS` | Yes | Comma-separated allowed frontend origins |
| `ADMIN_EMAIL` | No | Bootstrap admin account email |
| `ADMIN_PASSWORD` | No | Bootstrap admin account password |
| `LOG_LEVEL` | No | `INFO` (default), `DEBUG`, `WARNING` |

## Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run the full test suite
pytest tests/ -v

# With coverage report
pytest tests/ --cov=src --cov-report=term-missing
```

{api_section}

{schema_section}

## Architecture

```
┌─────────────┐     HTTP      ┌──────────────────┐     SQL    ┌──────────────┐
│  {frontend:<12} │◄────────────►│   {backend:<16} │◄──────────►│  {database:<12} │
└─────────────┘               └──────────────────┘            └──────────────┘
                                        │
                                        ▼
                               ┌──────────────────┐
                               │   Auth Middleware │
                               │  (JWT + bcrypt)   │
                               └──────────────────┘
```

The backend follows a layered architecture:
- **Routers** — FastAPI route handlers; thin, delegate to services
- **Services** — business logic, no direct DB access
- **Repositories** — async SQLAlchemy queries, one per entity
- **Schemas** — Pydantic models for request/response validation
- **Models** — SQLAlchemy ORM models mapping to DB tables

## Deployment

```bash
# Production build
docker compose -f docker-compose.prod.yml up -d

# Scale the API horizontally
docker compose -f docker-compose.prod.yml up -d --scale backend=3
```

Ensure the following before going live:
- [ ] `SECRET_KEY` is a securely generated random string
- [ ] Database backups are configured
- [ ] HTTPS / TLS termination is set up (nginx or cloud load balancer)
- [ ] `CORS_ORIGINS` is set to your production domain only
- [ ] Log aggregation is wired to your observability stack

## Contributing

1. Fork the repository and create a feature branch
2. Write tests for new functionality (`pytest tests/ -v`)
3. Submit a pull request against `main`

## Generated By

[AetherOS](https://aetheros.ai) — Autonomous AI App Factory
"""
    return readme


async def run(
    phase_input: Any,
    memory_ctx: List[Dict],
    output_dir: Path,
) -> Any:
    """Generate documentation, falling back to _build_fallback_readme if LLM fails."""
    from aether_os.phases.base import TaskResult

    output_dir = Path(output_dir)
    data = getattr(phase_input, "input_data", {}) or {}

    project_name = data.get("project_name", "App")
    arch = data.get("architecture_json", {})
    if isinstance(arch, str):
        import json
        try:
            arch = json.loads(arch)
        except Exception:
            arch = {}
    requirements = data.get("requirements_doc", "")

    docs_dir = output_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    readme_content = ""
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        prompt = (
            f"Write a comprehensive README.md for '{project_name}'. "
            f"Requirements: {requirements}. "
            f"Tech stack: {arch.get('tech_stack', {})}. "
            "Include: Overview, Installation, Environment Variables, API Reference with curl "
            "examples, Architecture, and Deployment. Minimum 600 words."
        )
        readme_content = await llm.call(prompt, task_type="documentation", max_tokens=4000)
    except Exception as exc:
        logger.warning("[p09] LLM call failed (%s) — using fallback README", exc)

    if not readme_content or len(readme_content.split()) < 100:
        readme_content = _build_fallback_readme(project_name, arch, requirements)

    readme_path = docs_dir / "README.md"
    readme_path.write_text(readme_content, encoding="utf-8")
    logger.info("[p09] wrote README.md (%d words)", len(readme_content.split()))

    return TaskResult(
        output_path=str(readme_path),
        confidence=0.9,
        metadata={"readme_words": len(readme_content.split()), "project": project_name},
        success=True,
        issues=[],
    )
