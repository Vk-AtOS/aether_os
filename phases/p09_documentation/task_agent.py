"""
p09_documentation.task_agent — compatibility shim for p10_docs_delivery.

Provides _build_fallback_readme() (the function tests directly call) and a
run() wrapper that writes README.md to the canonical output path expected by
tests (output_dir/docs/README.md).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


def _build_fallback_readme(
    project_name: str,
    arch: Dict[str, Any],
    description: str,
) -> str:
    """
    Generate a template README when the LLM is unavailable.

    Produces at least 500 words and includes Installation, API Reference
    sections with curl examples for each endpoint in arch['api_endpoints'].
    """
    tech_stack = arch.get("tech_stack", {})
    backend = tech_stack.get("backend", "FastAPI")
    database = tech_stack.get("database", "PostgreSQL")
    endpoints: List[Dict[str, Any]] = arch.get("api_endpoints", [])
    schema: List[Dict[str, Any]] = arch.get("database_schema", [])

    entities = ", ".join(t["table"] for t in schema if "table" in t) or "core entities"
    description = description or f"A {backend} application with {database} database."

    # Build endpoint sections with curl examples
    endpoint_lines: List[str] = []
    for ep in endpoints:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")
        ep_desc = ep.get("description", "")
        auth_required = ep.get("auth", True)
        auth_flag = '-H "Authorization: Bearer $TOKEN"' if auth_required else ""
        if method in ("POST", "PUT", "PATCH"):
            curl = (
                f'curl -X {method} http://localhost:8000{path} \\\n'
                f'  -H "Content-Type: application/json" \\\n'
            )
            if auth_flag:
                curl += f"  {auth_flag} \\\n"
            curl += "  -d '{\"key\": \"value\"}'"
        else:
            curl = f"curl -X {method} http://localhost:8000{path}"
            if auth_flag:
                curl += f" \\\n  {auth_flag}"
        endpoint_lines.append(
            f"### {method} {path}\n\n"
            f"{ep_desc}\n\n"
            f"```bash\n{curl}\n```\n"
        )
    api_ref_section = "\n".join(endpoint_lines) if endpoint_lines else (
        "### GET /health\n\nHealth check endpoint — no auth required.\n\n"
        "```bash\ncurl http://localhost:8000/health\n```\n"
    )

    return f"""# {project_name}

{description}

## Overview

{project_name} is a production-ready web application built with **{backend}** and **{database}**.
It provides a RESTful API backend with JWT authentication, role-based access control, and full
CRUD operations for {entities}.

The application follows clean architecture principles with separated concerns:
- **Routers**: HTTP request handling and validation
- **Services**: Business logic and domain operations
- **Models**: SQLAlchemy ORM models with relationships
- **Schemas**: Pydantic models for request/response validation

## Features

- JWT authentication with access tokens and refresh tokens
- Role-based access control (admin / user roles)
- Full CRUD operations for all domain entities
- Input validation with Pydantic schemas
- Async database operations with SQLAlchemy (async mode)
- Structured JSON logging for observability
- Prometheus metrics endpoint at `/metrics`
- Docker Compose for local development and production deployment
- Health check endpoint at `/health`
- OpenAPI documentation at `/docs` (Swagger UI)

## Tech Stack

| Layer       | Technology                        |
|-------------|-----------------------------------|
| Backend     | {backend}                         |
| Database    | {database}                        |
| Auth        | JWT (RS256, access + refresh)     |
| Validation  | Pydantic v2                       |
| ORM         | SQLAlchemy (async)                |
| Migrations  | Alembic                           |
| Container   | Docker + Docker Compose           |
| Monitoring  | Prometheus + Grafana              |

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.11+** — [python.org](https://www.python.org/)
- **Node.js 20+** — [nodejs.org](https://nodejs.org/)
- **Docker & Docker Compose** — [docker.com](https://www.docker.com/)
- **{database}** — see installation guide for your OS

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd {project_name.lower().replace(" ", "-")}
```

### 2. Set up the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env and set:
# DATABASE_URL=<your-database-url>
# SECRET_KEY=<random-32-char-string>
# CORS_ORIGINS=http://localhost:5173
```

### 4. Run database migrations

```bash
alembic upgrade head
```

### 5. Start the backend server

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.
Interactive API docs: `http://localhost:8000/docs`

### 6. Set up the frontend (if applicable)

```bash
cd ../frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:5173`.

## Environment Variables

| Variable          | Required | Default     | Description                              |
|-------------------|----------|-------------|------------------------------------------|
| `DATABASE_URL`    | Yes      | —           | Database connection string               |
| `SECRET_KEY`      | Yes      | —           | JWT signing secret (min 32 chars)        |
| `CORS_ORIGINS`    | Yes      | —           | Comma-separated allowed origins          |
| `ADMIN_EMAIL`     | No       | —           | Admin user email (auto-created at boot)  |
| `ADMIN_PASSWORD`  | No       | —           | Admin user password                      |
| `LOG_LEVEL`       | No       | `INFO`      | Logging level (DEBUG/INFO/WARNING/ERROR) |

## Running with Docker Compose

```bash
# Start all services (API + database + monitoring)
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f api

# Stop services
docker-compose down
```

## API Reference

All authenticated endpoints require a Bearer token in the Authorization header:

```bash
# Login to get a token
curl -X POST http://localhost:8000/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{{"email": "admin@example.com", "password": "yourpassword"}}'

# Use the returned access_token:
export TOKEN=<access_token_from_login_response>
```

{api_ref_section}

## Architecture

{project_name} follows a layered architecture:

```
┌───────────────────────────────────────────────────────────────┐
│                        Frontend (React)                       │
└───────────────────────────────┬───────────────────────────────┘
                                │ HTTP / REST
┌───────────────────────────────▼───────────────────────────────┐
│                    API Gateway (FastAPI)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │   Routers   │  │  Services   │  │   Auth Middleware    │   │
│  └──────┬──────┘  └──────┬──────┘  └─────────────────────┘   │
│         └────────────────┘                                    │
│                    │                                          │
│  ┌─────────────────▼─────────────────────────────────────┐   │
│  │             SQLAlchemy ORM (async)                    │   │
│  └─────────────────────────────────────────────────────┘   │
└───────────────────────────────┬───────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────┐
│                    {database} Database                         │
└───────────────────────────────────────────────────────────────┘
```

## Deployment

### Production checklist

- [ ] Set `SECRET_KEY` to a cryptographically random 32+ character string
- [ ] Use a production-grade database (not SQLite)
- [ ] Set `CORS_ORIGINS` to your actual frontend domain
- [ ] Enable HTTPS (TLS) via reverse proxy (nginx/Caddy)
- [ ] Set `LOG_LEVEL=WARNING` or `ERROR` in production
- [ ] Configure database connection pooling
- [ ] Set up database backups

### Nginx reverse proxy example

```nginx
server {{
    listen 443 ssl;
    server_name yourdomain.com;

    location / {{
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }}
}}
```

## Generated By

[AetherOS](https://aetheros.ai) — Autonomous AI Application Factory
"""


async def run(
    phase_input: Any,
    memory_ctx: Any,
    output_dir: Path,
) -> TaskResult:
    """
    Documentation phase entrypoint.

    Writes README.md to output_dir/docs/README.md. Falls back to the template
    generator when LLM output is empty or unavailable.
    """
    data = getattr(phase_input, "input_data", {}) or {}
    project_name = data.get("project_name", "App")
    description = data.get("requirements_doc", "")
    arch = data.get("architecture_json", {})
    if isinstance(arch, str):
        try:
            arch = json.loads(arch)
        except Exception as exc:
            logger.warning("p09_documentation: could not parse architecture_json: %s", exc)
            arch = {}

    docs_dir = Path(output_dir) / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    readme_path = docs_dir / "README.md"

    # Try LLM documentation generation
    readme_content = ""
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        endpoints = arch.get("api_endpoints", [])
        ep_summary = "\n".join(
            f"  {ep.get('method','GET').upper()} {ep.get('path','/')}"
            for ep in endpoints[:20]
        )
        prompt = (
            f"Generate a comprehensive README.md for '{project_name}'. "
            f"Description: {description}. "
            f"API endpoints:\n{ep_summary}\n"
            "Return only the markdown content, at least 500 words."
        )
        readme_content = await llm.call(prompt, task_type="documentation", max_tokens=4000)
    except Exception as exc:
        logger.warning("p09_documentation: LLM failed (%s), using fallback template", exc)

    # Fallback to template if LLM returned empty/failed
    if not readme_content or len(readme_content.split()) < 100:
        readme_content = _build_fallback_readme(project_name, arch, description)

    readme_path.write_text(readme_content, encoding="utf-8")
    logger.info("p09_documentation: README.md written (%d words)", len(readme_content.split()))

    summary_path = output_dir / "docs_summary.json"
    summary_path.write_text(
        json.dumps({"readme_path": str(readme_path), "project": project_name}, indent=2)
    )

    return TaskResult(
        output_path=str(summary_path),
        confidence=0.85,
        metadata={"readme_path": str(readme_path), "project": project_name},
        success=True,
        issues=[],
    )
