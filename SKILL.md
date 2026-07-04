# aether_os — Claude Context File
Last updated: 2026-04-29

## What this project is
AetherOS — Unified Multi-Agent Software Development System. Takes a software requirement and executes a full 10-phase development pipeline (Requirements → Architecture → Scaffold → Codegen → Review → Security → Testing → CI/CD → Docs → Package).

## Tech stack
- FastAPI (port 8080), Uvicorn/Gunicorn
- Anthropic claude-sonnet-4-6 (primary LLM)
- Ollama (local fallback)
- SQLite (async SQLAlchemy + aiosqlite)
- JWT auth, zero-trust execution, policy engine
- Typer CLI, Rich terminal UI
- Docker (deployment output), pyproject.toml packaging

## Key file locations
- `main.py` — Typer CLI entrypoint (start / demo / status commands)
- `agents/` — individual phase agents (p01_requirements through p11_deployment)
- `core/` — errors, config, db, audit, policy, licensing, identity, approval
- `gateway/` — FastAPI app, routes, client portal
- `orchestrator/` — pipeline orchestration logic
- `phases/` — phase definitions and execution
- `tests/` — 61 tests (all passing as of 2026-04-19)
- `COMPLETION_REPORT.md` — full file manifest and build notes
- `.env.example` — required env vars

## Current status
- 61/61 tests passing
- Most actively developed project (last commit 2026-04-29)
- One modified file: `gateway/client_portal/routes.py`
- Demo mode fully working: `python aether_os/main.py demo`
- API at http://0.0.0.0:8080

## What Claude CAN do in this project
- Read and analyze all agents and pipeline phases
- Fix bugs in any agent (p01–p11)
- Add new pipeline phases
- Improve the client portal gateway
- Write additional tests
- Improve Ollama fallback handling
- Run: `python aether_os/main.py status`

## What Claude CANNOT do without asking
- Push to git
- Change the primary LLM from claude-sonnet-4-6
- Modify the zero-trust policy engine without full review

## Known issues
- Ollama URL in Docker templates was broken (fixed 2026-04-29: use host.docker.internal)
- p04_backend may timeout causing p11_deployment to deploy a stub instead of real app

## How to run it
```bash
cd /Users/apple/Desktop/aether_os
source venv/bin/activate  # or: pip install -r requirements.txt

# Copy env and set keys
cp .env.example .env
# Set: ANTHROPIC_API_KEY, AETHER_SECRET_KEY, AETHER_ONE_ZT_SECRET, AETHER_ADMIN_PASSWORD

# Start API server
python aether_os/main.py start

# Run demo pipeline
python aether_os/main.py demo

# Check status
python aether_os/main.py status

# Run tests
pytest tests/ -v
```
