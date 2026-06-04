# Contributing to AetherOS

Thank you for your interest in contributing to AetherOS.

---

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 20+ (for the React dashboard)
- PostgreSQL 15+ (or Docker for local dev)
- Redis 7+ (or Docker for local dev)
- Git

### 1. Clone and create a virtual environment

```bash
git clone <repo> aether_os
cd aether_os
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set at minimum:
#   AETHER_SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
#   DATABASE_URL=postgresql+asyncpg://aetheros:password@localhost:5432/aetheros
#   REDIS_URL=redis://localhost:6379
#   ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Start dependencies

```bash
docker-compose up -d db redis
```

### 4. Apply database migrations

```bash
alembic upgrade add_pipeline_run_checkpoint
# If AETHER_FIELD_KEY is configured (field-level encryption):
alembic upgrade encrypt_sensitive_columns
```

### 5. Start the backend

```bash
uvicorn gateway.api:app --reload --port 8000
```

### 6. Build and start the frontend

```bash
cd dashboard
npm install
npm run dev   # Development server on port 3000
# or
npm run build # Production build into dashboard/dist/
```

---

## Code Standards

### Python

- **Style**: Follow PEP 8. We use `ruff` for linting and `black` for formatting.
- **Type hints**: All function signatures must have type annotations (Pydantic models preferred for API boundaries).
- **Imports**: Use absolute imports from the project root. No wildcard imports.
- **Exception handling**: Never use bare `except:`. Always catch specific exception types.
- **Async**: All I/O-bound code must be `async`. Never use blocking `time.sleep` or synchronous DB calls in async context.
- **Tests**: New code must include pytest tests. Target coverage: 80%+.

Run checks locally:
```bash
ruff check .
black --check .
pytest tests/ -v
```

### TypeScript / React

- **Style**: ESLint + Prettier (config in `dashboard/.eslintrc`).
- **Components**: Functional components only. No class components.
- **State**: Use React Query (TanStack Query) for server state; `useState` / `useReducer` for local UI state.
- **Types**: All props and API response shapes must be typed.

```bash
cd dashboard
npm run lint
npm run type-check
npm test
```

### Security

- **No secrets in code**: All secrets via environment variables. Pre-commit hooks will fail on detected secrets.
- **SQL**: Use SQLAlchemy ORM or parameterised queries only. No raw string interpolation into SQL.
- **Auth**: All non-public endpoints must use `Depends(get_current_user)`. Role checks via `require_role(...)`.
- **Multi-tenancy**: Every database query that touches user data must filter by `org_id`.

---

## PR Process

1. **Branch**: Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Commit messages**: Use [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   feat(phase): add p15 internationalization support
   fix(auth): correct TOTP window validation off-by-one
   chore(deps): bump anthropic to 0.30.0
   ```

3. **Tests**: Ensure all tests pass before opening a PR.

4. **PR description**: Fill in:
   - What this PR does
   - Why it is needed
   - How to test it manually
   - Screenshots for UI changes

5. **Review**: PRs require at least one review approval before merging. The reviewer will check:
   - Correctness and test coverage
   - Security implications (especially anything touching auth, multi-tenancy, or sandbox)
   - Performance impact on pipeline phases
   - Backwards compatibility

6. **Merge**: Squash-merge into `main`. The PR author merges after approval.

---

## Project Structure Quick Reference

```
gateway/          FastAPI app, auth, routers
orchestrator/     Pipeline orchestrator, MessageBus
phases/           21 phase modules (p01–p14, including p02b and p07b)
core/             Shared business logic (billing, identity, LLM, compliance)
dashboard/        React 18 frontend
cli/              Typer CLI
tests/            pytest suite
deploy/           Infrastructure configs
alembic/          Database migrations
```

---

## Adding a New Pipeline Phase

1. Create `phases/pXX_name/` with:
   - `supervisor.py` — phase supervisor that publishes results to MessageBus
   - `task_agent.py` — LLM task agent(s)
   - `gate.py` — quality gate (returns `GateResult`)
2. Register the phase in `orchestrator/factory_pipeline.py`
3. Add phase config defaults in `core/services/pipeline_service.py`
4. Write tests in `tests/phases/test_pXX_name.py`

---

## Reporting Issues

Use GitHub Issues with:
- **Bug report**: Steps to reproduce, expected vs. actual behaviour, logs/screenshots
- **Feature request**: Use case, proposed API/UX, alternatives considered

For security vulnerabilities, see [SECURITY.md](SECURITY.md).
