# aether_os — Claude Context File
Last updated: 2026-04-29 (STALE: describes the project as of April 2026; corrected below on 15 Nov 2026)

> Corrections at 15 Nov 2026, commit `e5c23fd`: the pipeline is 12 stages over 49 phase directories (`ls stages`; `ls -d phases/p*/` also counts `phases/patterns`, which is not a phase), not 10 phases; `tests/` has 217 test files and 2357 collected tests, not 61; `agents/` holds `base.py`, `implementations.py` and `tools/`, not p01 to p11 agents. Test results are in `SALE_READINESS.md`.

## What this project is
AetherOS — Unified Multi-Agent Software Development System. Takes a software requirement and executes a development pipeline (as of April 2026: 10 phases; now 12 stages) (Requirements → Architecture → Scaffold → Codegen → Review → Security → Testing → CI/CD → Docs → Package).

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
- `agents/` — base agent classes and tools (see correction above)
- `core/` — errors, config, db, audit, policy, licensing, identity, approval
- `gateway/` — FastAPI app, routes, client portal
- `orchestrator/` — pipeline orchestration logic
- `phases/` — phase definitions and execution
- `tests/` — 61 tests as of 2026-04-19 (2357 collected at 21 Nov 2026)
- `.env.example` — required env vars

## Current status
- 61/61 tests passing as of 2026-04-19 (not current)
- Status lines from April 2026 removed because they are not current and not measured (last commit, modified file, demo status).
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
