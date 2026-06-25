# DCSP — Claude Context File
Last updated: 2026-04-29

## What this project is
DCSP (Dynamic Code Self-healing Pipeline) — autonomous CI/CD self-healing system. Detects build/test failures via webhook, localizes root cause with DFLE engine, generates patches using LLM, validates in Docker sandbox, and auto-submits PRs. Features predictive failure intelligence, multi-tenancy, real-time WebSocket dashboard, federation network, and a VS Code extension.

## Tech stack
- FastAPI (port 8001), SQLite/PostgreSQL
- Ollama (local LLM for code repair)
- Docker (sandboxed patch validation)
- WebSockets (real-time dashboard updates)
- Kubernetes configs (k8s/)
- VS Code extension (extensions/)
- Multi-tenant isolation
- Predictive engine: Z-score baseline analysis

## Key file locations
- `main.py` — entrypoint, runs uvicorn on port 8001
- `src/api/` — FastAPI routes and middleware
- `src/integrations/aether2_bridge.py` — bridge to aether2/aether_os
- `src/core/` — DFLE engine, repair logic, sandbox
- `docker-compose.yml` — full stack (API + DB + Redis)
- `k8s/` — Kubernetes deployment configs
- `extensions/` — VS Code extension
- `tests/` — 459+ tests
- `scripts/` — start_demo.sh, migrate_db.py, seed_demo_data.py

## Current status
- 459+ tests passing, Docker-ready
- Last commit: 2026-03-12 (stable, no active development)
- Superseded by aether_os as an internal engine
- Positioned as standalone open-source portfolio project
- Demo login: admin / dcsp2024 at http://localhost:8000/dashboard

## What Claude CAN do in this project
- Read and analyze any component
- Write a better README for GitHub
- Add missing endpoints or dashboard features
- Improve the predictive intelligence engine
- Fix any broken tests

## What Claude CANNOT do without asking
- Push to git or make public
- Change the database schema without a migration

## Known issues
- `dispatch_repair_job` missing from Aether2Bridge (flagged in BOS audit)
- SandboxGuard is a stub in the AgentOS integration layer

## How to run it
```bash
cd /Users/apple/Desktop/DCSP
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Set: DATABASE_URL, OLLAMA_HOST, WEBHOOK_SECRET

# Initialize DB
python scripts/migrate_db.py
python scripts/seed_demo_data.py

# Start full stack
./scripts/start_demo.sh
# OR
docker-compose up

# Access dashboard
open http://localhost:8000/dashboard
# Login: admin / dcsp2024
```
