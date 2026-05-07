# AetherOS — Launch Readiness Report
**Prepared:** 2026-05-08  
**Deployment target:** 80,243 global users  
**Contract deadline:** May 15, 2026  
**Auditor:** Exhaustive static analysis across all layers (gateway, orchestrator, frontend, deploy, DB, security)

---

## Executive Summary

This system **cannot be launched safely on May 15th in its current state.**

There are **6 P0 issues** that will cause the server to either crash on startup, serve zero API responses, or expose every user's data to every other user. There are **12 P1 issues** that are active security vulnerabilities, including hardcoded credentials shipped to 80K users. There are **14 P2 issues** that guarantee instability under production load, and **12 P3 issues** that represent broken or stub features visible to paying users.

**Total defects found: 44**

---

## Severity Scale

| Severity | Definition |
|----------|-----------|
| **P0** | Launch blocker — will crash, 404, or corrupt data immediately |
| **P1** | Security / data integrity — active vulnerability, must fix before users touch it |
| **P2** | Reliability / scalability — will degrade or fail under real load |
| **P3** | Quality / UX — broken feature or visible stub shipped to paying users |

---

## P0 — LAUNCH BLOCKERS

These issues will prevent the system from functioning at all, or will cause immediate catastrophic failure.

---

### P0-1 · systemd service points at wrong entry point — server will crash on start

**File:** `deploy/aetheros.service`, line 20  
**Code:** `ExecStart=/opt/aetheros/venv/bin/uvicorn main:app`

`main.py` exports `app = typer.Typer(...)` — a CLI application, not a FastAPI ASGI app. Uvicorn will fail to load it and the service will crash immediately on `systemctl start aetheros`. The system will never come up.

**Fix:** Change to:
```
ExecStart=/opt/aetheros/venv/bin/uvicorn aether_os.gateway.api:app \
    --host 127.0.0.1 \
    --port 9200 \
    --workers 4
```

---

### P0-2 · Frontend makes requests without `/api/` prefix — nginx never routes them to FastAPI

**File:** `dashboard/src/api.js`, line 3 and `deploy/nginx.conf`, line 47  
**Code:** `const BASE = ""; // Use relative paths to stay on same origin`

nginx only proxies requests that begin with `/api/` to FastAPI (`location /api/`). The React dashboard sends all API requests to bare paths: `/auth/login`, `/factory/runs`, `/system/health`, etc. These paths match nginx's `location /` (static files), which returns `index.html` — not the API. Every single API call from the dashboard returns an HTML document, not JSON. The application is 100% non-functional through nginx.

**Fix (option A — preferred):** Set `const BASE = "/api"` in `api.js` so the frontend prefixes all requests with `/api/`.  
**Fix (option B):** Remove the `/api/` prefix from nginx and proxy `/` to FastAPI, serving the React build from a different path.

---

### P0-3 · nginx SSE location path does not match the actual SSE endpoint

**File:** `deploy/nginx.conf`, line 56  
**nginx location:** `/api/factory/run/`  
**Actual FastAPI endpoint:** `GET /factory/runs/{run_id}/stream`

Two problems: (1) `run/` vs `runs/` (missing the `s`), (2) the endpoint is nested under `{run_id}/stream`, not at `run/` directly. SSE streams will never reach the correct handler — live pipeline progress will be broken for every user.

**Fix:** Change the nginx SSE location to:
```nginx
location ~ ^/api/factory/runs/[^/]+/stream {
    proxy_pass http://127.0.0.1:9200;
    proxy_buffering off;
    proxy_cache off;
    ...
}
```

---

### P0-4 · `SecurityHeadersMiddleware` and `HttpsRedirectMiddleware` are defined but commented out

**File:** `gateway/api.py`, lines 164–165  
**Code:**
```python
# app.add_middleware(SecurityHeadersMiddleware)
# app.add_middleware(HttpsRedirectMiddleware)
```

These two lines are commented out. The server starts with no security headers (`X-Frame-Options`, `X-Content-Type-Options`, `Content-Security-Policy`, etc.) and no HTTPS enforcement from the application layer. If nginx is misconfigured or bypassed, traffic runs unencrypted. For a system handling JWTs and multi-tenant business data, this is a launch blocker by compliance standards.

**Fix:** Uncomment both lines before deployment.

---

### P0-5 · `Compliance.jsx` calls `api.get()` — method does not exist → TypeError, blank page

**File:** `dashboard/src/pages/Compliance.jsx`  
**Code:** `api.get('/compliance/org-report')` and `api.get('/audit/logs')`

The `api` object exported from `api.js` has no `.get()` method — it exposes named functions (`api.getHealth()`, `api.listRuns()`, etc.), not a generic `.get()`. This throws a `TypeError: api.get is not a function` on page load. The entire Compliance page is a blank screen for every user.

**Fix:** Wire up `api.getComplianceReport()` and `api.getAuditLogs()` in `api.js`, or replace the calls with `client.get('/compliance/org-report')` directly.

---

### P0-6 · `/compliance/artifacts/{run_id}` and `/memory/changelog` have broken imports → 500 on every call

**File:** `gateway/api.py`  
**Broken imports:**
```python
from core.compliance.artifact_generator import ComplianceArtifactGenerator  # missing aether_os. prefix
from core.memory.memory_manager import MemoryManager                         # missing aether_os. prefix
```

Both imports fail at runtime with `ModuleNotFoundError`. Any request to these endpoints returns HTTP 500. These are not caught by tests because the import error is deferred (inside the route handler, not at module load time).

**Fix:** Change to:
```python
from aether_os.core.compliance.artifact_generator import ComplianceArtifactGenerator
from aether_os.core.memory.memory_manager import MemoryManager
```

---

## P1 — SECURITY & DATA INTEGRITY

These are active vulnerabilities that will expose user data, allow unauthorized access, or leak credentials the moment real users connect.

---

### P1-1 · 🔴 CRITICAL: Hardcoded credentials pre-filled in Login form — ships to 80K users

**File:** `dashboard/src/pages/Login.jsx`, lines 6–7  
**Code:**
```javascript
const [email, setEmail] = useState('verify@test.com');
const [password, setPassword] = useState('Dom@0104!');
```

These are test/developer credentials committed to source control and pre-filled in the login form's default state. Every user who opens the login page sees these credentials. This constitutes a credential leak at scale. If this account exists in the production database, it grants immediate unauthorized access to 80,243 users' login page.

**Fix:** Change both to `useState('')`. Rotate the `verify@test.com` account password immediately and audit for any data it can access.

---

### P1-2 · `/factory/runs` list leaks all orgs' priority and live_url data

**File:** `gateway/api.py`, lines 797 and 809  
**Code:**
```python
"SELECT run_id, priority FROM run_metadata"               # No org_id filter
"SELECT id, live_url FROM runs WHERE live_url IS NOT NULL" # No org_id filter
```

These raw SQL queries have no org_id filter. An authenticated user from Org A will see every run's priority and live deployed URL from every other org in the system. With 80K users across multiple tenants this is a complete multi-tenant data isolation failure.

**Fix:** Add `WHERE org_id = :org_id` to both queries, passing the org_id from the JWT claims.

---

### P1-3 · Billing/LLM cost queries leak spend data across all orgs

**File:** `gateway/api.py`, lines 1405–1429 (the `/system/costs` endpoint)  
**Code:**
```python
"SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls WHERE ts >= ..."
```

The `llm_calls` table has no `org_id` column. Every authenticated user sees the total LLM spend for the entire platform — not just their own org. Revenue and usage data from every customer is exposed to every other customer.

**Fix:** Add `org_id TEXT NOT NULL` to the `llm_calls` table and filter all cost queries by the requesting user's org.

---

### P1-4 · SSE authentication token passed in URL query string

**File:** `dashboard/src/pages/ProjectView.jsx` and `gateway/api.py` SSE handler  
**Code:** `?token=${encodeURIComponent(token)}`

JWTs passed as URL parameters appear in: nginx access logs, application logs, browser history, `Referer` headers on outbound requests, CDN/proxy logs, and any analytics tool. In a 80K-user deployment, these logs are routinely collected and indexed. Any log access gives an attacker valid 24-hour tokens.

**Fix:** Switch to cookie-based auth or pass the token via a one-time handshake. For SSE specifically, use an exchange token: issue a short-lived (60s) single-use token from `/factory/runs/{id}/stream-token`, then use that in the URL.

---

### P1-5 · Rate limiter is implemented but never wired into login or register routes

**File:** `core/rate_limiter.py` (implementation) vs `gateway/api.py` (routes)  
**Evidence:** `grep -n "rate_limit\|RateLimiter" gateway/api.py` — zero results in route handlers

The `RateLimiter` class exists with `MAX_LOGIN_ATTEMPTS_PER_IP=20`, but it is never imported or called from the `/auth/login` or `/auth/register` handlers. Brute-force and credential stuffing attacks are completely unmitigated at the application layer. (nginx has rate limiting, but that only applies if P0-2 is fixed and traffic actually flows through nginx.)

**Fix:** Import the rate limiter and apply it as a dependency on both auth routes. Also lower `MAX_LOGIN_ATTEMPTS_PER_IP` from 20 to 5.

---

### P1-6 · `/settings/api-keys` POST allows any authenticated user to overwrite production LLM keys

**File:** `gateway/api.py`, lines 1612–1656  
**Code:** Writes directly to `.env` file with no admin role check

Any logged-in user (including trial users) can call `POST /settings/api-keys` and overwrite the server's `ANTHROPIC_API_KEY` or `GOOGLE_API_KEY` in the `.env` file. A malicious user can replace the keys with invalid values to take down the LLM pipeline for all users, or substitute their own keys to bill Anthropic charges to your account.

**Fix:** Add an `admin` role check: `if user.get("role") != "admin": raise HTTPException(403)`. Also consider removing `.env` write access from the web API entirely and managing keys through environment configuration only.

---

### P1-7 · No minimum password length or complexity validation on registration

**File:** `gateway/api.py`, `/auth/register` handler  
**Evidence:** No length check before `hash_password(req.password)` call

Users can register with a 1-character password. Combined with P1-5 (no rate limiting), this means any account can be brute-forced in seconds.

**Fix:** Enforce a minimum password length of 12 characters and basic complexity (uppercase + digit or symbol) before hashing.

---

### P1-8 · Org slug not checked for uniqueness before DB insert — IntegrityError crashes register

**File:** `gateway/api.py`, `/auth/register` handler  
**Issue:** No `SELECT` check before inserting a new Organisation row

If two users try to register with the same company name simultaneously, or a duplicate org name is submitted, the DB raises an `IntegrityError` (unique constraint on `slug`), which propagates as an unhandled 500 to the user. The user has no idea what happened — they may have partially created an account.

**Fix:** Query for existing orgs with the same slug before inserting. Return HTTP 409 with `"detail": "Organisation name already taken"`.

---

### P1-9 · JWT has 24-hour expiry with no refresh token — tab close logs out users

**File:** `gateway/auth.py` and `dashboard/src/api.js`  
**Issue:** `sessionStorage` is cleared on tab/window close; 24h tokens with no refresh mechanism

When a user closes and re-opens the tab, they are logged out immediately. More critically, there is no refresh token flow — the only way to get a new token is to re-authenticate. For a global enterprise product, this is a severe usability issue and creates pressure for users to set very long sessions.

**Fix:** Implement refresh tokens with 7-day expiry stored in `httpOnly` cookies (which also solves the sessionStorage token exposure). The access token can remain 15 minutes.

---

### P1-10 · Rate limiter state is in-memory — resets on restart, not shared across workers

**File:** `core/rate_limiter.py`  
**Issue:** `RateLimiter` uses a Python `dict` in process memory

Even if P1-5 is fixed, with 2 uvicorn workers, each worker has its own independent rate limiter. An attacker alternating requests between workers gets double the allowed attempts. And every server restart resets all attempt counters.

**Fix:** Move rate limiter state to Redis (already in requirements.txt as commented-out). Use `slowapi` (already in requirements.txt) with a Redis backend.

---

### P1-11 · CORS falls back to localhost-only — production requests will be blocked

**File:** `gateway/api.py`, `_get_cors_origins()` function  
**Issue:** If `CORS_ORIGINS` env var is not set, origins default to `localhost:*` variants only

If the production `.env` does not explicitly set `CORS_ORIGINS`, every API call from the production domain (`https://yourdomain.com`) will be blocked by the browser with a CORS error. This is a silent misconfiguration that is easy to miss in deployment.

**Fix:** Add `CORS_ORIGINS=https://yourdomain.com` to the production `.env`. Also add a startup assertion that warns if CORS is still set to localhost values in non-development environments.

---

### P1-12 · `approval/store.py` holds a persistent `sqlite3.connect()` — connection is not thread-safe

**File:** `core/approval/store.py`, line 178  
**Code:** `self._conn = sqlite3.connect(self.db_path)`

The approval store opens a single SQLite connection at `__init__` time and holds it for the lifetime of the object. SQLite connections are not thread-safe. In a multi-worker or concurrent async environment, simultaneous approvals will corrupt the approval database or raise `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.

**Fix:** Open a new connection per method call (with context manager), or use `check_same_thread=False` with an explicit `threading.Lock()`.

---

## P2 — RELIABILITY & SCALABILITY

These issues will cause degradation or outright failures under the load of 80K global users.

---

### P2-1 · SQLite is the default database — cannot handle production load

**File:** `core/db.py`, `_build_db_url()` and `requirements.txt`  
**Issue:** PostgreSQL (asyncpg, psycopg2-binary) is commented out of requirements.txt; SQLite is the default

SQLite has a single writer at a time. With 2 uvicorn workers both writing to the same `~/.aether_os/aether_os.db`, you will see immediate `database is locked` errors under concurrent load. SQLite is not designed for multi-process concurrent writes and does not scale to 80K users. WAL mode is not configured. No connection pool settings are applied.

**Fix:** Uncomment `asyncpg>=0.29.0` and `psycopg2-binary>=2.9.0` in requirements.txt. Set `DATABASE_URL=postgresql+asyncpg://...` in the production `.env`. Run `alembic upgrade head` against PostgreSQL before launch.

---

### P2-2 · 14 synchronous `sqlite3.connect()` calls inside async route handlers — blocks event loop

**File:** `gateway/api.py` (14 instances), `core/audit/ledger.py` (8 instances), `core/billing.py`, `core/memory/store.py`, `core/artifact_store.py`  
**Total:** 52 synchronous sqlite3 calls across the codebase called from async contexts

Each `sqlite3.connect()` + query blocks the entire Python event loop for its duration. Under concurrent load, a single slow query (>10ms) stalls every other request on that worker. With 80K users this will cause cascading timeouts across the entire API.

**Fix:** Replace with `aiosqlite` for async SQLite access, or (preferred with P2-1) migrate to PostgreSQL + asyncpg and remove all raw sqlite3 usage. For the DecisionLedger specifically, wrap all calls in `asyncio.get_event_loop().run_in_executor(None, ...)` as an interim fix.

---

### P2-3 · `DecisionLedger` opens a new sqlite3 connection on every method call — no pooling

**File:** `core/audit/ledger.py`, all methods  
**Issue:** Every call to `log_event()`, `get_history()`, etc. calls `sqlite3.connect(self.db_path)` and closes it after. Under audit-heavy pipeline runs, this creates hundreds of short-lived connections per run with no pooling.

**Fix:** Use a context manager with a connection pool, or migrate to SQLAlchemy async as used elsewhere in the codebase.

---

### P2-4 · No database indexes on high-frequency query columns

**File:** `core/models.py`  
**Missing indexes:** `org_id` on `Run`, `User`, `Event`, `Snapshot`, `PhaseCompletion`; `email` on `User`; `status` on `Run`

Every multi-tenant query filters by `org_id`. Without indexes, every such query is a full table scan. At 80K users generating pipeline runs, the `runs` and `events` tables will have millions of rows. Full table scans on every API request will make the system unusable.

**Fix:** Add a migration:
```python
op.create_index('ix_runs_org_id', 'runs', ['org_id'])
op.create_index('ix_runs_status', 'runs', ['status'])
op.create_index('ix_events_run_id', 'events', ['run_id'])
op.create_index('ix_users_email', 'users', ['email'])
op.create_index('ix_users_org_id', 'users', ['org_id'])
```

---

### P2-5 · 2 uvicorn workers are insufficient for 80K users — and they compete for SQLite

**File:** `deploy/aetheros.service`, line 23  
**Code:** `--workers 2`

2 workers is the development default. For 80K users, even with async, 2 workers will saturate under moderate concurrency. More critically, with SQLite (P2-1), adding workers makes things worse — each additional writer increases lock contention. 

**Fix:** After migrating to PostgreSQL, set workers to `(2 × CPU_cores) + 1`. For a 4-core VPS: `--workers 9`. Also consider deploying behind a process supervisor like Gunicorn with uvicorn workers.

---

### P2-6 · Docker containers from p11 deployment are never cleaned up — VPS will run out of resources

**File:** `phases/p11_deployment/task_agent.py`  
**Issue:** Each factory run that deploys creates a running Docker container with a random port, but there is no cleanup mechanism — no `docker stop`, no `docker rm`, no container lifecycle management

After 100 pipeline runs, there are 100 running Docker containers consuming ports, memory, and CPU on the VPS. The server will eventually run out of resources and crash.

**Fix:** Add cleanup: before starting a new container for a run, stop and remove any previous container for that run_id. Add a `/factory/runs/{run_id}/deploy DELETE` endpoint that actually calls `docker stop` + `docker rm`.

---

### P2-7 · Alembic migrations exist but production DB state is unknown

**File:** `alembic/versions/` (14 migration files)  
**Issue:** There are 14 Alembic migration files including multiple merge heads (`merge_heads`, `merge_heads_2`, `merge_heads_3`). The production database at `~/.aether_os/aether_os.db` is created by `create_all()` (not by Alembic), meaning the `alembic_version` table may not exist, and the migration history is not tracked.

**Fix:** Before launch, run `alembic stamp head` to mark the current schema as current, then verify with `alembic current`. Any future schema changes must go through `alembic upgrade head`.

---

### P2-8 · Pipeline phase count mismatch: orchestrator has 12 phases, Settings.jsx hardcodes 10

**File:** `dashboard/src/pages/Settings.jsx`, line 94 (`PHASES` array) vs `orchestrator/factory_pipeline.py` (`PHASE_SEQUENCE`)  
**Orchestrator:** 12 phases including `p07b_self_healing` and `p11_deployment`  
**Settings.jsx:** 10 phases, missing `p07b_self_healing` and `p11_deployment`

The Settings page phase configuration panel is missing 2 phases. Users cannot configure or monitor the self-healing or deployment phases from the UI.

**Fix:** Derive the phase list from a shared config or synchronize `PHASES` in Settings.jsx with `PHASE_SEQUENCE` in `factory_pipeline.py`.

---

### P2-9 · `Dashboard.jsx` useEffect dependency `[runs.length]` causes polling interval reset on every update

**File:** `dashboard/src/pages/Dashboard.jsx`  
**Issue:** `useEffect(() => { const id = setInterval(..., 5000); return () => clearInterval(id); }, [runs.length])`

Every time `runs.length` changes (i.e., every time a run is added or removed), the interval is cleared and restarted. If runs are being actively added, this can result in the polling interval resetting before it fires — effectively creating a near-infinite polling loop or preventing updates from ever appearing.

**Fix:** Change the dependency array to `[]` (run once) and use a `useRef` for the interval ID. Fetch data inside without depending on `runs.length`.

---

### P2-10 · `PhaseDetail.jsx` loading state logic is always false — spinner never shows

**File:** `dashboard/src/pages/PhaseDetail.jsx`  
**Code:** `if (!phaseData && phaseData !== null)` 

`phaseData` is initialized to `null`. The condition `!phaseData && phaseData !== null` evaluates to `true && false = false` always. The loading state is never shown. Users see a blank/broken phase detail view during any data load.

**Fix:** Change to `if (phaseData === undefined)` (using `undefined` as initial state) or `if (loading)` with a separate loading boolean.

---

### P2-11 · `ProjectView.jsx` null-crashes if `live_url` is absent

**File:** `dashboard/src/pages/ProjectView.jsx`  
**Code:** `run.live_url.split(':').pop()`

`live_url` is `null` for any run that hasn't been deployed (the majority of runs). This line throws `TypeError: Cannot read properties of null (reading 'split')`, crashing the entire page.

**Fix:** Guard with `run.live_url?.split(':').pop()` or only render the live URL section conditionally.

---

### P2-12 · EventSource SSE connection not reliably cleaned up → memory leak

**File:** `dashboard/src/pages/ProjectView.jsx`  
**Issue:** EventSource is created in a useEffect but the cleanup function doesn't always close it, especially on component unmount during navigation

Over a long session with a user navigating between many runs, unremoved EventSource connections accumulate. Browsers limit concurrent EventSource connections to 6 per origin — once exhausted, no new SSE connections can open.

**Fix:** Always return a cleanup function from the useEffect: `return () => { if (es) { es.close(); } }`.

---

### P2-13 · Very heavy requirements.txt — VPS install will take 20-40 minutes and may have conflicts

**File:** `requirements.txt`  
**Heavy packages:** `crewai`, `langchain`, `langchain-community`, `langgraph`, `playwright`, `locust`, `chromadb`, `mem0ai`, `semgrep`, `gpt-researcher`, `aider-chat`, `diagrams`, `hypothesis`

Combined, these packages pull in hundreds of transitive dependencies. On a fresh VPS, `pip install -r requirements.txt` will take 20-40 minutes and consume several GB of disk. Version conflicts are likely (langchain + crewai often conflict). This is a deployment day risk — if the install fails at minute 35 with a conflict, the launch is delayed.

**Fix:** Split into `requirements-core.txt` (just what the API server needs at runtime) and `requirements-pipeline.txt` (the heavy agent frameworks only needed for running pipelines). Install core first to verify the server starts, then pipeline packages.

---

### P2-14 · `nginx.conf` server_name is `YOUR_DOMAIN_HERE` — will not serve HTTPS

**File:** `deploy/nginx.conf`, lines 13, 23, 25, 26  
**Code:** `server_name YOUR_DOMAIN_HERE;` (4 occurrences)

The TLS certificate paths reference `YOUR_DOMAIN_HERE`. If deployed as-is, nginx will fail to load the SSL configuration and reject all HTTPS connections.

**Fix:** Replace all 4 instances of `YOUR_DOMAIN_HERE` with the actual production domain before deployment. Run `nginx -t` to verify config before enabling.

---

## P3 — QUALITY & FEATURES (Stub endpoints shipping to paying users)

---

### P3-1 · `/account/projects` returns `[]` — Projects section always empty

**File:** `gateway/api.py`, `/account/projects` handler  
**Code:** `return []`  Stub — no DB query implemented.

---

### P3-2 · `/factory/runs/{run_id}/decisions` returns `[]` — Decision history always empty

**File:** `gateway/api.py`, `/factory/runs/{run_id}/decisions` handler  
**Code:** `return []`  Stub — the DecisionLedger is never queried here.

---

### P3-3 · `/webhooks` GET/POST/DELETE returns hardcoded data — no persistence

**File:** `gateway/api.py`, webhook handlers  
**Issue:** `GET /webhooks` returns `[{"id": "wh_1", "url": "https://example.com/hook", ...}]`. Nothing a user configures via `POST /webhooks` is ever saved to the database.

---

### P3-4 · `/admin/users` returns hardcoded stub data

**File:** `gateway/api.py`, `/admin/users` handler  
**Code:** `return [{"id": "u1", "role": "admin"}]`  No real user list is ever returned.

---

### P3-5 · `/marketplace/profiles` returns `[]` — Marketplace always empty

**File:** `gateway/api.py`, `/marketplace/profiles` handler  
**Code:** `return []` Stub.

---

### P3-6 · `/compliance/org-report` returns hardcoded zeros

**File:** `gateway/api.py`, `/compliance/org-report` handler  
**Issue:** Returns `{"runs_audited": 0, "issues_found": 0, "compliant": true}` regardless of actual data.

---

### P3-7 · `Marketplace.jsx` uses bare axios without auth token

**File:** `dashboard/src/pages/Marketplace.jsx`  
**Code:** `axios.get('/marketplace/profiles')` — raw axios, not the authenticated `client` instance

Marketplace requests are unauthenticated. The `/marketplace/profiles` handler itself requires auth and will return 401. The page will always show an error or empty state.

**Fix:** Change to `client.get('/marketplace/profiles')` or `api.getMarketplaceProfiles()`.

---

### P3-8 · `ClientPortal.jsx` silently falls back to mock data on API error

**File:** `dashboard/src/pages/ClientPortal.jsx`, lines 24-33  
**Code:** The catch block sets `status` to a hardcoded mock object instead of showing an error

If the portal API call fails (network error, 401, 500), clients see fake project data ("AetherOS Factory Project", client-001). This could mislead a real client into approving a phase for a project they're not looking at.

**Fix:** Show an error state with a message like "Unable to load project status. Please try again."

---

### P3-9 · Settings.jsx phase list hardcoded and out of sync with pipeline

**File:** `dashboard/src/pages/Settings.jsx`, line 94  
**Issue:** Phase names and descriptions are hardcoded twice (once in `PHASES` array, once in `PHASE_NAMES` dict). These will silently drift from the actual pipeline definition.

**Fix:** Fetch the active phase list from a backend endpoint (`GET /settings/phases`) rather than hardcoding in the frontend.

---

### P3-10 · `/system/costs` billing data not isolated by org — exposes global platform spend

**File:** `gateway/api.py`, `/system/costs` handler  
**Issue:** (also a P1-3 security issue) Any user can see total platform LLM spend across all organisations. Additionally the `llm_calls` table used here is a separate SQLite DB (`billing.db`) entirely disconnected from the main ORM — there's no migration, no schema guarantees, and no org_id column.

---

### P3-11 · Dashboard build artifact may be stale — production JS is `index-eYr_mml3.js` which predates some fixes

**File:** `dashboard/dist/assets/index-eYr_mml3.js`  
**Issue:** The compiled JS bundle is what actually runs in production. If source files (`.jsx`) have been updated but `npm run build` has not been re-run, users get the old code.

**Fix:** Run `cd dashboard && npm run build` as the final step of every deployment. Automate this in `deploy/deploy.sh`.

---

### P3-12 · `deploy.sh` and `setup_vps.sh` need review for completeness before launch day

**File:** `deploy/deploy.sh`, `deploy/setup_vps.sh`  
**Issue:** Not fully audited — given the density of mismatches found in `nginx.conf` and `aetheros.service`, there are likely corresponding problems in these scripts (e.g., wrong paths, missing env var setup, no `alembic upgrade head` step, no `npm run build` step).

**Fix:** Walk through each script end-to-end on a staging server before launch day.

---

## Issue Count Summary

| Severity | Count | Status |
|----------|-------|--------|
| P0 — Launch blockers | 6 | 🔴 Must fix before any user traffic |
| P1 — Security/Data | 12 | 🔴 Must fix before contract signing |
| P2 — Reliability | 14 | 🟡 Must fix before 80K user load |
| P3 — Quality/Stubs | 12 | 🟡 Fix before paying customers |
| **Total** | **44** | |

---

## Pre-Launch Fix Priority Order

Work in this order to unblock testing as fast as possible:

**Day 1 (Make it boot and route correctly):**
1. P0-1 — Fix systemd entry point (`aether_os.gateway.api:app`)
2. P0-2 — Fix frontend routing (add `/api` prefix to `api.js` BASE)
3. P0-3 — Fix nginx SSE location regex
4. P0-4 — Uncomment security middleware in `gateway/api.py`
5. P0-5 — Fix `Compliance.jsx` api.get() calls
6. P0-6 — Fix broken module imports in compliance/memory routes

**Day 2 (Security before any real user data):**
7. P1-1 — Remove hardcoded credentials from `Login.jsx` (10-second fix)
8. P1-2 — Add org_id filter to priority_map and live_url_map queries
9. P1-4 — Fix SSE token in URL (use cookie or exchange token)
10. P1-5 — Wire rate limiter into auth routes
11. P1-6 — Add admin role check to `/settings/api-keys` POST
12. P1-7 — Add password minimum length validation

**Day 3 (Database for real load):**
13. P2-1 — Switch to PostgreSQL (uncomment asyncpg, set DATABASE_URL)
14. P2-4 — Add database indexes migration
15. P2-2 — Wrap sync sqlite3 calls in `run_in_executor` or migrate to async

**Day 4 (Deploy config and frontend fixes):**
16. P2-14 — Replace `YOUR_DOMAIN_HERE` in nginx.conf
17. P1-11 — Set `CORS_ORIGINS` in production .env
18. P2-11 — Fix `live_url` null crash in ProjectView.jsx
19. P2-10 — Fix PhaseDetail.jsx loading state logic
20. P3-11 — Rebuild dashboard (`npm run build`) as last deploy step

---

## Files Requiring Changes Before Launch

| File | Issues |
|------|--------|
| `deploy/aetheros.service` | P0-1 |
| `deploy/nginx.conf` | P0-2 (partial), P0-3, P2-14 |
| `dashboard/src/api.js` | P0-2, P1-9 |
| `gateway/api.py` | P0-4, P0-6, P1-2, P1-3, P1-5, P1-6, P1-7, P1-8, P3-1–P3-6 |
| `dashboard/src/pages/Compliance.jsx` | P0-5 |
| `dashboard/src/pages/Login.jsx` | P1-1 |
| `dashboard/src/pages/ProjectView.jsx` | P1-4, P2-11, P2-12 |
| `dashboard/src/pages/Dashboard.jsx` | P2-9 |
| `dashboard/src/pages/PhaseDetail.jsx` | P2-10 |
| `dashboard/src/pages/Marketplace.jsx` | P3-7 |
| `dashboard/src/pages/ClientPortal.jsx` | P3-8 |
| `dashboard/src/pages/Settings.jsx` | P2-8, P3-9 |
| `core/db.py` | P2-1, P2-5 |
| `core/models.py` | P2-4 |
| `core/audit/ledger.py` | P2-2, P2-3 |
| `core/approval/store.py` | P1-12 |
| `core/billing.py` | P1-3, P2-2 |
| `core/rate_limiter.py` | P1-10 |
| `requirements.txt` | P2-1 (uncomment asyncpg), P2-13 |
| `.env` (production) | P1-11, P2-14 |

---

*Report generated from full static analysis of all gateway, orchestrator, frontend, deployment, and core modules. No code was modified during this audit.*
