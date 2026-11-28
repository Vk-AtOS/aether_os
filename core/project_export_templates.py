"""Files the clean export writes itself (KAN-268 / KAN-271 D6): Dockerfiles, compose, nginx, .env.example, README, CI.

They are generated from the layout of the assembled tree, never copied from the run workspace, because the
workspace copies were written for the pipeline's flat layout (root-level requirements.txt, ``src/``, a ``frontend``
folder and an nginx that strips ``/api``) and referenced paths that do not exist in the shipped project.

Layout of the export::

    backend/    FastAPI app (src/ or main.py, requirements.txt, Dockerfile, optional tests/ and alembic/)
    frontend/   Vite app source (package.json, src/, Dockerfile, nginx.conf), no node_modules or dist
    docker-compose.yml  .env.example  README.md  .github/workflows/ci.yml  MANIFEST.json
"""
from __future__ import annotations

import re
from typing import Dict, List

PLACEHOLDER = "CHANGE_ME"
# Variable names whose value is a secret: the example file carries a placeholder, compose requires them to be set.
_SECRET_NAME = re.compile(r"(SECRET|PASSWORD|PASSWD|TOKEN|KEY|PRIVATE|CREDENTIAL)", re.I)
_ENV_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)$")
# Variables the compose file wires itself.
_WIRED = {"DATABASE_URL", "ENVIRONMENT", "SECRET_KEY", "RSA_PRIVATE_KEY_PATH", "RSA_PRIVATE_KEY"}


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def env_vars_from_example(text: str) -> Dict[str, str]:
    """Names (and non-secret values) the generated backend documents in its own .env.example."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        m = None if line.lstrip().startswith("#") else _ENV_LINE.match(line)
        if not m:
            continue
        name, value = m.group(1), m.group(2).strip().strip("'\"")
        out[name] = PLACEHOLDER if is_secret_name(name) else value
    return out


def backend_dockerfile(module: str) -> str:
    return (
        "FROM python:3.11-slim\n"
        "WORKDIR /app\n"
        "ENV PYTHONPATH=/app PYTHONUNBUFFERED=1\n"
        "COPY requirements.txt ./\n"
        "RUN pip install --no-cache-dir -r requirements.txt\n"
        "COPY . .\n"
        "# keys/ holds the generated JWT signing key and data/ the SQLite file when no Postgres is configured;\n"
        "# both are volumes in docker-compose.yml so they survive a container rebuild.\n"
        "RUN useradd --system --create-home app && mkdir -p /app/keys /app/data && chown -R app /app\n"
        "USER app\n"
        "EXPOSE 8000\n"
        "HEALTHCHECK --interval=15s --timeout=5s --retries=5 \\\n"
        "  CMD python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\"\n"
        f'CMD ["uvicorn", "{module}:app", "--host", "0.0.0.0", "--port", "8000"]\n'
    )


def frontend_dockerfile(has_lock: bool) -> str:
    install = "npm ci" if has_lock else "npm install"
    return (
        "FROM node:20-alpine AS build\n"
        "WORKDIR /app\n"
        "COPY package*.json ./\n"
        f"RUN {install}\n"
        "COPY . .\n"
        "# Empty: the browser calls /api on the same origin and nginx forwards it to the backend.\n"
        "ARG VITE_API_URL=\n"
        "ENV VITE_API_URL=${VITE_API_URL}\n"
        "RUN npm run build\n\n"
        "FROM nginx:alpine\n"
        "COPY --from=build /app/dist /usr/share/nginx/html\n"
        "COPY nginx.conf /etc/nginx/conf.d/default.conf\n"
        "EXPOSE 80\n"
    )


def frontend_nginx_conf() -> str:
    # The generated backend mounts every router under /api, so /api is forwarded unchanged (no prefix stripping).
    return (
        "server {\n"
        "  listen 80;\n"
        "  root /usr/share/nginx/html;\n"
        "  index index.html;\n\n"
        "  location /api/ {\n"
        "    proxy_pass http://backend:8000;\n"
        "    proxy_set_header Host $host;\n"
        "    proxy_set_header X-Real-IP $remote_addr;\n"
        "    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "    proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    proxy_read_timeout 60s;\n"
        "  }\n\n"
        "  location / {\n"
        "    try_files $uri $uri/ /index.html;\n"
        "  }\n"
        "}\n"
    )


def compose(use_postgres: bool, has_frontend: bool, extra_vars: Dict[str, str]) -> str:
    env_lines: List[str] = []
    if use_postgres:
        env_lines.append(
            "      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-app}:${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}"
            "@db:5432/${POSTGRES_DB:-app}")
    else:
        env_lines.append("      DATABASE_URL: sqlite+aiosqlite:////app/data/app.db")
    env_lines += [
        "      SECRET_KEY: ${SECRET_KEY:?set SECRET_KEY in .env}",
        "      ENVIRONMENT: production",
        "      RSA_PRIVATE_KEY_PATH: /app/keys/private_key.pem",
    ]
    for name, value in sorted(extra_vars.items()):
        if name in _WIRED or name.startswith("POSTGRES_"):
            continue
        if is_secret_name(name):
            env_lines.append(f"      {name}: ${{{name}:?set {name} in .env}}")
        else:
            env_lines.append(f"      {name}: ${{{name}:-{value}}}")
    out = ["services:"]
    if use_postgres:
        out += [
            "  db:",
            "    image: postgres:16-alpine",
            "    environment:",
            "      POSTGRES_USER: ${POSTGRES_USER:-app}",
            "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}",
            "      POSTGRES_DB: ${POSTGRES_DB:-app}",
            "    volumes:",
            "      - pgdata:/var/lib/postgresql/data",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER:-app} -d $${POSTGRES_DB:-app}"]',
            "      interval: 5s",
            "      timeout: 5s",
            "      retries: 10",
            "    restart: unless-stopped",
        ]
    out += ["  backend:", "    build: ./backend", "    environment:", *env_lines, "    volumes:",
            "      - appkeys:/app/keys", "      - appdata:/app/data"]
    if use_postgres:
        out += ["    depends_on:", "      db:", "        condition: service_healthy"]
    out += ["    restart: unless-stopped"]
    if not has_frontend:
        out += ["    ports:", '      - "${HTTP_PORT:-8000}:8000"']
    else:
        out += [
            "  frontend:", "    build: ./frontend", "    ports:", '      - "${HTTP_PORT:-8080}:80"',
            "    depends_on:", "      - backend", "    restart: unless-stopped",
        ]
    out += ["", "volumes:", "  appkeys:", "  appdata:"]
    if use_postgres:
        out.append("  pgdata:")
    return "\n".join(out) + "\n"


def env_example(use_postgres: bool, extra_vars: Dict[str, str]) -> str:
    lines = ["# Copy to .env and fill in every CHANGE_ME. Never commit .env.", ""]
    if use_postgres:
        lines += ["POSTGRES_USER=app", f"POSTGRES_PASSWORD={PLACEHOLDER}", "POSTGRES_DB=app", ""]
    lines += ["# generate with: openssl rand -hex 32", f"SECRET_KEY={PLACEHOLDER}"]
    for name, value in sorted(extra_vars.items()):
        if name in _WIRED or name.startswith("POSTGRES_"):
            continue
        lines.append(f"{name}={PLACEHOLDER if is_secret_name(name) else value}")
    lines += ["HTTP_PORT=8080", ""]
    return "\n".join(lines)


def readme(project: str, has_frontend: bool, use_postgres: bool, has_tests: bool) -> str:
    port = "8080" if has_frontend else "8000"
    return (
        f"# {project}\n\n"
        "Generated by AetherOS. This folder is a complete, deployable project.\n\n"
        "## Layout\n\n"
        "- `backend/` FastAPI service (`Dockerfile`, `requirements.txt`)\n"
        + ("- `frontend/` React + Vite app served by nginx (`Dockerfile`, `nginx.conf`)\n" if has_frontend else "")
        + "- `docker-compose.yml` runs the whole stack\n"
        "- `.env.example` every setting the stack reads; secrets are placeholders\n"
        "- `.github/workflows/ci.yml` build and test on every push\n"
        "- `MANIFEST.json` every file in this export with its SHA-256\n\n"
        "## Deploy\n\n"
        "1. Install Docker with the Compose plugin on the server.\n"
        "2. `cp .env.example .env` and replace every `CHANGE_ME` with a real value "
        "(`openssl rand -hex 32` makes a good `SECRET_KEY`).\n"
        "3. `docker compose up -d --build`\n"
        f"4. Open `http://<server>:{port}`; the API health check is `/health` on the backend container.\n\n"
        "Put a TLS reverse proxy (Caddy, nginx, a cloud load balancer) in front for production. "
        "The JWT signing key is generated on first start and kept in the `appkeys` volume; "
        "back that volume up with the database"
        + (" (`pgdata`)" if use_postgres else " (`appdata`)") + ".\n\n"
        "## Develop locally\n\n"
        "```\ncd backend && pip install -r requirements.txt && uvicorn "
        "$(test -f src/main.py && echo src.main || echo main):app --reload\n"
        + ("cd frontend && npm install && npm run dev\n" if has_frontend else "")
        + "```\n"
        + ("\nRun the backend tests with `cd backend && PYTHONPATH=. pytest tests`.\n" if has_tests else "")
    )


def ci_workflow(has_frontend: bool, has_tests: bool, has_lock: bool, scripts: List[str],
                backend_check: str) -> str:
    """GitHub Actions workflow whose every path exists in the export (checked by workflow_path_problems)."""
    y = [
        "name: CI", "", "on:", "  push:", "    branches: [main, master]", "  pull_request:", "",
        "jobs:", "  backend:", "    runs-on: ubuntu-latest", "    defaults:", "      run:",
        "        working-directory: backend", "    steps:", "      - uses: actions/checkout@v4",
        "      - uses: actions/setup-python@v5", "        with:", '          python-version: "3.11"',
        "          cache: pip", "          cache-dependency-path: backend/requirements.txt",
        "      - name: Install dependencies", "        run: pip install -r requirements.txt",
        "      - name: Byte-compile", f"        run: python -m compileall -q {backend_check}",
    ]
    if has_tests:
        y += ["      - name: Test", "        run: |",
              "          pip install pytest pytest-asyncio httpx",
              "          PYTHONPATH=. pytest tests -q"]
    if has_frontend:
        y += ["", "  frontend:", "    runs-on: ubuntu-latest", "    defaults:", "      run:",
              "        working-directory: frontend", "    steps:", "      - uses: actions/checkout@v4",
              "      - uses: actions/setup-node@v4", "        with:", '          node-version: "20"']
        if has_lock:
            y += ["          cache: npm", "          cache-dependency-path: frontend/package-lock.json"]
        y += ["      - name: Install dependencies", f"        run: {'npm ci' if has_lock else 'npm install'}"]
        for s in ("typecheck", "lint"):
            if s in scripts:
                y += [f"      - name: {s}", f"        run: npm run {s}"]
        y += ["      - name: Build", "        run: npm run build"]
    y += ["", "  docker:", "    runs-on: ubuntu-latest", "    needs: [backend" + (", frontend]" if has_frontend else "]"),
          "    steps:", "      - uses: actions/checkout@v4",
          "      - name: Build backend image", "        run: docker build -t app-backend backend"]
    if has_frontend:
        y += ["      - name: Build frontend image", "        run: docker build -t app-frontend frontend"]
    return "\n".join(y) + "\n"

