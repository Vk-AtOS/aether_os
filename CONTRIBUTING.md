# Contributing to AetherOS

Thank you for your interest in contributing to AetherOS.

---

## Development Setup

### Prerequisites

- Python 3.11 (CI uses 3.11, `.github/workflows/ci.yml:60`; `pyproject.toml` allows 3.10 and newer)
- Node.js 20 (CI uses 20, `ci.yml:117`)
- PostgreSQL and Redis (or Docker). The compose files pin the images; use those versions
- Git

### 1. Clone and create a virtual environment

```bash
git clone <repo> aether_os
cd aether_os
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env - set at minimum:
#   AETHER_SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
#   AETHER_ONE_ZT_SECRET=<same way>
#   DATABASE_URL=postgresql+asyncpg://<user>:<password>@localhost:5432/<database>
#   REDIS_URL=redis://localhost:6379
#   one LLM provider, for example ANTHROPIC_API_KEY or AWS Bedrock credentials
```

### 3. Start dependencies

```bash
docker compose up -d db redis     # compose needs POSTGRES_PASSWORD and REDIS_PASSWORD in .env
```

### 4. Apply database migrations

```bash
alembic upgrade head
```
The history has one head, `merge_r2_heads`. If `alembic heads` prints more than one after you merge, add a merge revision. On an empty database use `scripts/db_migrate.py` instead: it creates the schema and stamps head, because the chain cannot be replayed from nothing. Set `AETHER_FIELD_KEY` first (field-level encryption, `core/encryption.py`).

### 5. Start the backend

```bash
uvicorn gateway.api:app --reload --port 8000    # run from the checkout; Docker and systemd use aether_os.gateway.api:create_app --factory
```

### 6. Build and start the frontend

```bash
cd dashboard
npm install
npm run dev   # Vite dev server; the port and the API proxy are set in dashboard/vite.config.js
# or
npm run build # Production build into dashboard/dist/
```

---

## Code Standards

### Python

- **Lint**: CI runs `ruff check . --select F,E9,B904` and it blocks the merge (`.github/workflows/ci.yml:71-73`). There is no `black` or `mypy` step in CI and no `black` config.
- **Type hints**: preferred on function signatures; nothing checks them.
- **Imports**: absolute imports with the `aether_os.` prefix, as in the existing code. Imports go at the top of the file.
- **Exception handling**: no bare `except:`, and no `except Exception: pass`. Catch `Exception as e` only with a log line, for example `logger.warning("...", e)`. The same rule is in `CLAUDE.md`.
- **File size**: no Python file over 600 lines, no router file over 400 lines (`CLAUDE.md`). Split first, then change.
- **Async**: I/O-bound code in the gateway is `async`. Do not use blocking calls in async handlers.
- **Tests**: new code needs pytest tests. CI runs the suite with coverage and fails below the floor `COVERAGE_FLOOR`, now 50 (`ci.yml:49,91-98`). There is no 80% target in the code.
- **Commits**: one logical change per commit, with the root cause in the message (`CLAUDE.md`). Recent history uses `type(scope): message`, for example `fix(compose): ...`.

Run checks locally:
```bash
ruff check . --select F,E9,B904
pytest tests/ --timeout=300 -q
```

### TypeScript / React

- **Style**: ESLint (config in `dashboard/eslint.config.js`). No Prettier config exists.
- **Components**: functional components, as in the existing code.
- **State**: TanStack Query for server state; `useState` / `useReducer` for local UI state.

```bash
cd dashboard
npm run lint
npm test            # vitest
npm run build:ci    # lint, test, build
npm run test:e2e    # Playwright
```
There is no `type-check` script in `dashboard/package.json`.

### Security

- **No secrets in code**: secrets come from environment variables. There is no `.pre-commit-config.yaml` in the repository, so no pre-commit hook scans for secrets. CI runs `bandit` (`ci.yml:76`).
- **SQL**: use SQLAlchemy ORM or parameterised queries only.
- **Auth**: every non-public endpoint depends on `get_current_user` (`gateway/dependencies.py`). It also applies the central role floor from `gateway/role_gate.py`, so a new mutating route is closed to viewers by default. Use `enforce(...)` from the policy engine or an explicit role check in the handler when a route needs more. A public route needs a comment that says why (`CLAUDE.md`).
- **Multi-tenancy**: every query that touches user data filters by `org_id`. Routes with `{run_id}` use the `require_run_user` dependency.

---

## PR Process

The review and merge rules below are team process. Nothing in the repository enforces them (branch protection is a GitHub setting and was not checked).

1. **Branch**: Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Commit messages**: Use [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   fix(auth): correct TOTP window validation off-by-one
   chore(deps): bump a dependency
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
orchestrator/     Pipeline orchestrator, phase_sequence.py (12 stages)
stages/           s01 .. s12 stage supervisors
phases/           phase agents (`ls phases | grep -c '^p[0-9]'`)
core/             Shared business logic (billing, identity, LLM, compliance)
dashboard/        React 19 frontend
cli/              Typer CLI
tests/            pytest suite
deploy/           Infrastructure configs
alembic/          Database migrations
```

---

## Adding a New Pipeline Phase

1. Create `phases/pXX_name/` with, as the existing phases do (for example `phases/p15_handoff/`):
   - `supervisor_agent.py` - phase supervisor, based on `PhaseBase` (`phases/base.py`)
   - `task_agent.py` - the `run(...)` function (keep it small; prompts and helpers go in their own files, `CLAUDE.md`)
   - `gate.py` - `validate(result)` returning a `GateOutcome`
2. Call the phase from the stage supervisor that owns it, under `stages/sNN_*/supervisor.py` (for example `stages/s10_enterprise/supervisor.py` calls `p16_iam`). The orchestrator runs stages, not single phases (`orchestrator/phase_sequence.py`).
3. Write tests in `tests/`, for example `tests/test_phases_later.py` shows the contract tests for later phases.

---

## Reporting Issues

Use GitHub Issues with:
- **Bug report**: Steps to reproduce, expected vs. actual behaviour, logs/screenshots
- **Feature request**: Use case, proposed API/UX, alternatives considered

For security vulnerabilities, see [SECURITY.md](SECURITY.md).
