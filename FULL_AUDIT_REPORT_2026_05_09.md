# AetherOS — Full Pre-Launch Audit Report
**Date:** 2026-05-09 | **Target Launch:** 2026-05-11 | **Deployment:** 80,000 employees  
**Auditors:** 4 parallel automated agents — Backend/Scale, API/Phases, Frontend/UX, Legal/Regulatory  
**Files examined:** 47 source files, 5,000+ lines of code

---

## EXECUTIVE VERDICT: NOT READY FOR LAUNCH ON MAY 11

Deploying AetherOS on May 11 to an 80,000-employee enterprise will result in:
- **Day 1:** Live streaming (SSE), pause, cancel, and resume all broken with multiple workers
- **Day 1:** The pipeline produces near-empty output — 22 of 25 phase sub-modules fail silently
- **Day 1:** Any authenticated user can escalate themselves to Enterprise plan with a single API call
- **Week 1:** Enterprise IT rejects due to missing SSO, no MFA, no SCIM, no Terms of Service
- **Week 2:** Legal team returns the product — no GDPR erasure rights, no Privacy Policy, secrets in git

**Functional rate:** ~40% of advertised features work end-to-end. The remaining 60% are stubs, broken imports, or non-functional wiring.

---

## SECTION 1 — ARCHITECTURE-LEVEL CRITICAL FAILURES
*These collapse the system immediately under production conditions.*

---

### CRIT-01 — SSE Streaming, Pause, Cancel, Resume: ALL BROKEN with Multiple Workers
**Severity: CRITICAL | File: orchestrator/events.py:14, orchestrator/factory_pipeline.py:502**

`PIPELINE_EVENTS` (event queues) and `PIPELINE_CONTROL` (pause/cancel signals) are plain Python in-process dicts. The systemd service starts 8 workers. A pipeline starts in Worker A, but an SSE client hitting Worker B finds `PIPELINE_EVENTS[run_id] = None` and immediately returns `no_stream`. Pause/cancel signals set `PIPELINE_CONTROL[run_id]` in whatever worker handles the HTTP request — if the pipeline is running in a different worker, the signal is never seen.

**Result:** Live terminal output, pause, cancel, and resume are silently broken 7/8 of the time in production. The user sees a spinning pipeline with no output.

**Fix:** Move `PIPELINE_EVENTS` and `PIPELINE_CONTROL` to Redis pub/sub. Redis is installed and running on the VPS but is completely unused.

---

### CRIT-02 — 22 of 25 Pipeline Sub-Phase Imports Fail Silently
**Severity: CRITICAL | Root cause: phases/_legacy/ not in package namespace**

All consolidated phase supervisors (P01, P04, P06, P07, P08, P09, P10) delegate to sub-phases imported as `aether_os.phases.p01_requirements`, `aether_os.phases.p04a_backend_codegen`, etc. These files only exist at `phases/_legacy/p*/`. There is no `_legacy` package alias. Every import raises `ModuleNotFoundError`, caught silently by `try/except Exception: pass` in each supervisor.

**Phases that produce ZERO real output:**
| Phase | What fails | What users see |
|---|---|---|
| P01 intake_requirements | Both sub-phases fail | Empty requirements JSON |
| P04 backend | Both sub-phases fail — no backend code generated | No backend code |
| P06 review_security | Both sub-phases fail — no code review | Fake "passed" gate |
| P07 testing | All 4 sub-phases fail — no tests run | Fake test results |
| P08 cicd_deployment | All 6 sub-phases fail — no CI/CD | Empty CI artifacts |
| P09 observability | All 4 sub-phases fail | Empty observability |
| P10 docs_delivery | All 3 sub-phases fail — no docs | No documentation |

**Phases that DO work:** P02 (architecture), P03 (scaffolding), P05 (frontend), P07b (self-healing), P11 (deployment).

**Fix:** In each consolidated `task_agent.py`, change all imports from `aether_os.phases.pXX_*` to `aether_os.phases._legacy.pXX_*`, or add `_legacy` to `sys.path` in the package `__init__.py`.

---

### CRIT-03 — `asyncpg` Commented Out — PostgreSQL Crashes at Startup
**Severity: CRITICAL | File: requirements.txt:115**

```
# asyncpg>=0.29.0   ← commented out
```

The `.env` has `DATABASE_URL=postgresql://...`. When `create_async_engine` tries to load the asyncpg driver, it fails with `ModuleNotFoundError`. The startup validator at `api.py:235` catches this and calls `sys.exit(1)`. The service crashes on boot.

**Fix:** Uncomment `asyncpg>=0.29.0` in requirements.txt and reinstall on VPS.

---

### CRIT-04 — `Request` Not Imported — Rate Limiting on Login/Register is Broken
**Severity: CRITICAL | File: gateway/api.py:36, 355, 420, 741**

`Request` is used as a type annotation in `/auth/register`, `/auth/login`, and `/factory/start` but is not imported. With `from __future__ import annotations`, FastAPI evaluates it lazily and treats it as a query string parameter named `request`, not as the Starlette Request object. As a result:

1. IP-based rate limiting (`request.client.host`) is silently broken — `.client` raises AttributeError on the injected string
2. `/auth/register`, `/auth/login`, and `/factory/start` technically require a `?request=` query param (harmless but confusing)
3. All brute-force protection on the login endpoint is non-functional

**Fix:** Add `from fastapi import Request` to the imports at `api.py:36`.

---

### CRIT-05 — `/pipeline/start` Always Returns Wrong run_id
**Severity: CRITICAL | File: gateway/api.py:605–636**

The endpoint creates `ExecutionContext(run_id=uuid4())` and returns that UUID to the client. Then it calls `pipeline.run()` as a background task — which internally generates its own separate UUID, saves it to the ledger, and runs the pipeline under that ID. The client's `run_id` never exists in the ledger. `/pipeline/status/{run_id}` always returns 404 for every run started via this endpoint.

**Fix:** Pass the pre-generated `run_id` into `pipeline.run()` instead of letting it generate its own.

---

### CRIT-06 — `ProtectHome=yes` in systemd Service Blocks All Database Access
**Severity: CRITICAL | File: deploy/aetheros.service:49**

The systemd unit sets `ProtectHome=yes`, which makes `~` inaccessible to the service user. The entire database (`~/.aether_os/aether_os.db`), all project files (`~/.aether_os/projects/`), and the LLM cache are stored under `~`. The service can start but immediately fails any database operation. `ReadWritePaths` is set to `/opt/aetheros /var/log/aetheros` — neither exists nor contains the data.

**Fix:** Either set `ProtectHome=no` or move the data directory to `/opt/aetheros/data` and update `core/db.py` accordingly.

---

### CRIT-07 — Factory Pipeline Produces Empty Runs Despite Showing "completed"
**Severity: CRITICAL | Combined effect of CRIT-02**

The factory pipeline (`factory_pipeline.py:296-301`) catches all phase exceptions and marks a phase `failed`, then **continues to the next phase regardless**. After all 12 phases "complete" (7 of which produce nothing due to CRIT-02), the run is marked `completed`. Users see a green "completed" run with an empty project directory and no documentation, tests, or CI/CD artifacts. This is the most damaging user-facing failure — it looks like it worked.

---

### CRIT-08 — Mass Assignment: Any User Can Escalate to Enterprise Plan
**Severity: CRITICAL | File: gateway/api.py:848**

```python
stmt = update(Organisation).where(Organisation.id == user["org_id"]).values(req)
```

`req` is raw `Dict[str, Any]` from the request body. Any authenticated user can POST:
```json
{"plan": "enterprise", "trial_runs_limit": 9999, "autonomous_mode": true}
```
This overwrites the database record with no field allowlist. Autonomous mode disables all human-in-the-loop safety gates. Plan upgrade bypasses all billing.

**Fix:** Replace with an explicit allowlist of settable fields (e.g., `org_name`, `notification_prefs`).

---

### CRIT-09 — `asyncio.create_task()` With No Reference — Pipelines Silently Dropped
**Severity: CRITICAL | File: gateway/api.py:624, 828, 1322**

```python
asyncio.create_task(_run_bg())   # no reference stored
```

Python's asyncio GC can collect an unreferenced task before it completes. For a long-running pipeline task, this means the entire multi-phase pipeline execution can be silently cancelled mid-run. The run stays in "running" state forever. No error is logged.

**Fix:** Store all task references in a module-level set: `_tasks = set()`. Add a `done_callback` to remove completed tasks.

---

## SECTION 2 — DATABASE & SCALE FAILURES

### DB-01 — Dual Database Split-Brain: Ledger Always SQLite, ORM Can Be PostgreSQL
**Severity: HIGH | File: core/audit/ledger.py:60, core/db.py:53**

`DecisionLedger` (the primary store for run history, events, and phase data) always writes to `~/.aether_os/aether_os.db` via raw `sqlite3`. The SQLAlchemy ORM writes to PostgreSQL (when `DATABASE_URL` is set). These are two separate data stores with no sync. The dashboard's run list reads from the ledger (SQLite); org/user data reads from ORM (PostgreSQL). A run created by the pipeline exists in SQLite but the org that owns it is in PostgreSQL — foreign key relationships are physically impossible to enforce.

### DB-02 — 9+ Sync `sqlite3.connect()` Calls Inside Async Route Handlers
**Severity: HIGH | File: gateway/api.py:889, 906, 920, 978, 1033, 1047, 1266, 1893, 2230**

Synchronous `sqlite3.connect()` inside `async def` route handlers blocks the entire asyncio event loop for the duration of each DB call. Under any concurrent load, this stalls all other requests until the DB call returns. These are in the hottest routes: `list_factory_runs`, `get_factory_run`, and `set_run_priority`.

### DB-03 — Connection Pool Overflow at 80K Users
**Severity: HIGH | File: core/db.py:83–89**

`pool_size=20, max_overflow=40` per worker × 8 workers = 480 max connections. PostgreSQL's default `max_connections=100`. At any significant load, connections are refused. Requires either PgBouncer or PostgreSQL reconfiguration to `max_connections=500+`.

### DB-04 — `audit_log` Index Points to Wrong Table Name
**Severity: MEDIUM | File: core/db.py:175, core/models.py:176**

DDL creates index `ON audit_logs` (plural) but the table is `audit_log` (singular). Index creation silently fails every startup (caught by `except Exception: pass`). The audit log table has no index on `org_id` — full table scan on every audit log query.

### DB-05 — Missing Foreign Key Indexes on High-Traffic Tables
**Severity: MEDIUM | File: core/models.py**

No explicit indexes on: `Event.run_id`, `Snapshot.run_id`, `PhaseCompletion.run_id`, `Decision.org_id`, `Webhook.org_id`, `Workspace.org_id`. Under load, joining or filtering by these columns causes full table scans.

---

## SECTION 3 — AUTHENTICATION & MULTI-TENANCY FAILURES

### AUTH-01 — Production Secrets Committed to Git Repository
**Severity: CRITICAL | File: .env**

The `.env` file is committed to the repository and contains:
- `AETHER_SECRET_KEY=Pbe7dmgEcSz3lQ6V59qKQS4aan6zkepV6BgOLEySty4` — the JWT signing key
- `AETHER_ADMIN_PASSWORD=Nu_xxABPTiVHy5itkbcvzw`
- `AETHER_ONE_ZT_SECRET=-pHxQ1LEWUZR6A1XGQqozZ4fyEIQqbxgwC5YlkIEDSE`

Anyone with repository access can forge valid JWT tokens for any user/org. **These must be rotated immediately, regardless of all other fixes.**

### AUTH-02 — SAML/SSO is Dead Code (Flask Stub Never Mounted)
**Severity: CRITICAL | File: gateway/auth_saml.py**

`auth_saml.py` is a standalone Flask app (`app = Flask(__name__)`). It is never imported by or mounted into the FastAPI application. The SAML routes (`/saml/login`, `/saml/callback`) do not exist at runtime. The `SamlConfig` database model exists but has no functional backend. For 80,000 employees, SSO is a hard requirement — IT teams will not issue email/password credentials at this scale.

### AUTH-03 — No Token Revocation or Logout
**Severity: HIGH | File: gateway/auth.py:55, gateway/api.py**

JWT tokens expire after **7 days** (`expires_hours=168`). There is no `/auth/logout` endpoint, no token blacklist, no `jti` claim. A terminated employee's token remains valid for up to 7 days. If the JWT secret is rotated (e.g., after a breach), all 80,000 users are simultaneously logged out. `core/identity/engine.py:363` has `revoke_token()` but it is never called by the active auth path.

### AUTH-04 — Login Does Not Check Account Deactivation
**Severity: HIGH | File: gateway/api.py:437**

The login query: `select(User, Organisation).join(Organisation).where(User.email == req.email)` has no `User.is_active == True` filter. A deactivated/terminated user can still authenticate. There is also no admin endpoint to deactivate a user — only role changes exist.

### AUTH-05 — Rate Limiting is Per-Worker (8× More Permissive Without Redis)
**Severity: HIGH | File: core/rate_limiter.py:38–44**

When Redis is absent, an in-memory `_MemoryStore` is used per worker. With 8 workers, an attacker gets 20 login attempts × 8 workers = **160 effective attempts** before hitting any limit. The SSE token store (`api.py:1259`) has the same problem — SSE tokens issued by Worker A are unknown to Worker B, causing 7/8 failure rate on SSE token validation.

### AUTH-06 — Cross-Tenant Data Leak: Changelog Endpoint Missing Org Check
**Severity: CRITICAL | File: gateway/api.py:1167**

`POST /factory/runs/{run_id}/memory/changelog` queries `select(Run).where(Run.id == run_id)` with no `Run.org_id == user["org_id"]` check. Any authenticated user who knows (or guesses) a run UUID from another organization can write data to that run.

### AUTH-07 — `GET /intelligence/global-insights` is Unauthenticated
**Severity: HIGH | File: gateway/api.py:1058**

No `Depends(get_current_user)`. Returns aggregate data including `domain` and `raw_input` snippets from all completed runs across all organizations. Accessible by anyone on the internet.

### AUTH-08 — API Keys Hashed with SHA-256, Not bcrypt
**Severity: MEDIUM | File: gateway/auth.py:36**

`hashlib.sha256(api_key.encode()).hexdigest()` — a fast non-password hash. A database breach immediately enables offline rainbow table attacks on all API keys. Should use `bcrypt` or `argon2`.

### AUTH-09 — JWT Exposed in URL (Two Locations)
**Severity: MEDIUM | File: gateway/api.py:1344, dashboard/src/pages/Compliance.jsx:40**

1. `GET /factory/runs/{run_id}/stream?token=<JWT>` — legacy SSE token path still active; JWT appears in nginx access logs
2. `window.location.href = /api/compliance/artifacts/{runId}?token=${token}` — full JWT in URL for compliance download; logged in browser history and server access logs

### AUTH-10 — PhaseConfig Has No org_id (Changes Affect All Orgs)
**Severity: MEDIUM | File: core/models.py:117, gateway/api.py:1869**

Phase enable/disable configuration is global — one organization's admin changes phase settings for all organizations simultaneously. No org scoping on phase configs.

### AUTH-11 — No MFA (Multi-Factor Authentication)
**Severity: HIGH | File: N/A — missing entirely**

No TOTP, SMS, hardware key, or any second factor. Most enterprise security policies and cyber insurance requirements mandate MFA. Absence will block procurement.

---

## SECTION 4 — COMPLETE API STUB INVENTORY

The following endpoints exist and respond 200 OK but return fake/empty data:

| Endpoint | What It Returns | Impact |
|---|---|---|
| `POST /account/settings` | `{status:"ok"}` but sets ANY column including `plan` | CRITICAL security |
| `GET /factory/runs/{id}/kill` | `{success:true}` — pipeline not stopped | Run cannot be killed |
| `POST /admin/kill-all` | `{killed_count:0}` — nothing killed | Emergency stop broken |
| `GET /webhooks` | `[]` — always | No webhooks |
| `POST /webhooks` | `{id:"w_1"}` — fake ID | Webhooks never saved |
| `DELETE /webhooks/{id}` | `{success:true}` — always | No-op |
| `GET /marketplace/profiles` | `[]` — always | Marketplace empty |
| `POST /marketplace/publish` | `{status:"published"}` — not saved to DB | Publishing is fake |
| `GET /account/projects` | `[]` — always | Projects list empty |
| `GET /account/projects/search` | `[]` — always | Search broken |
| `GET /intelligence/quality-benchmark` | Hardcoded `{score:92.5}` | Not real metrics |
| `GET /system/health` | Hardcoded `{tests_passing:153, database:"healthy"}` | Not real health |
| `GET /compliance/org-report` | Hardcoded zeros | Not real compliance |

---

## SECTION 5 — PIPELINE & AGENT ARCHITECTURE

### PIPE-01 — Human-in-the-Loop Gate Never Actually Pauses the Pipeline
**Severity: HIGH | File: orchestrator/factory_pipeline.py:296-301**

`PhaseBase._escalate()` creates an approval ticket and emits a bus message. The factory pipeline catches `BaseException` from each phase and continues to the next phase unconditionally. The `GATED_HUMAN` state in the state machine is never entered. Human approval requests are emitted into the void.

### PIPE-02 — Kill Switch UI Does Not Exist
**Severity: HIGH | File: gateway/api.py:2044, 2049**

`POST /factory/runs/{run_id}/kill` and `POST /admin/kill-all` are stubs (see above). No frontend UI element exposes either endpoint. There is no emergency stop for the system.

### PIPE-03 — Orchestrator Testing Phase Hardcodes Pass Results
**Severity: HIGH | File: orchestrator/pipeline.py:493**

```python
"passed": True,  # TODO: wire actual test runner via phases/p07_testing
```
Tests are generated as code strings but never executed. `passed=True` is hardcoded regardless of actual test quality. Autonomous mode self-test hardcodes `tests_passed=10, coverage_percent=85` with no Docker or test runner invocation.

### PIPE-04 — Named Agent Registry is Empty (14 Agents Declared, 0 Implemented)
**Severity: HIGH | File: agents/base.py, agents/tools/__init__.py**

14 agent names are declared in `AgentName` enum (`POLICY`, `RISK`, `SNAPSHOT`, `MEMORY_KNOWLEDGE`, `RED_TEAM`, `STABILITY_GUARDIAN`, etc.). `agents/tools/` is an empty package. The `default_agent_registry` singleton is never populated. The entire agent mesh is a declaration with zero runtime behavior.

### PIPE-05 — `core/memory/matcher.py` Always Fails on Import
**Severity: HIGH | File: core/memory/matcher.py:12**

```python
from aether_os.phases.p08_cicd.patch_reuse.fingerprint import FailureFingerprint
```
`p08_cicd` does not exist as a package (all in `_legacy/`). This import fails at module load. `ProjectMatcher` (used by `memory_service.py`) is always broken, meaning cross-run similarity search (`/memory/search`) always returns empty matches.

### PIPE-06 — `orchestrator/pipeline.py` Still Uses Bare `core.` Import
**Severity: HIGH | File: orchestrator/pipeline.py:258**

```python
from core.memory.memory_manager import MemoryManager  # should be aether_os.core.
```
Raises `ModuleNotFoundError` at runtime whenever the old Pipeline completes a run, silently crashing the memory-save step.

### PIPE-07 — Generated Apps Ship With CORS Wildcard
**Severity: HIGH | File: phases/p03_scaffolding/task_agent.py:67**

```python
allow_origins=["*"]
```
Every application AetherOS generates for clients ships with a CORS wildcard by default, regardless of security requirements. Every deliverable has an OWASP A05 finding baked in from creation.

### PIPE-08 — `run_change_request()` Starts a Full New Pipeline (Not a Patch)
**Severity: MEDIUM | File: orchestrator/factory_pipeline.py:484**

Calls `self.run()` with the change description. Does not reuse, diff, or patch the existing project. A change request produces a brand new project with no continuity from the original.

### PIPE-09 — State Machine Mismatch (26-Phase Names vs 12-Phase Reality)
**Severity: MEDIUM | File: orchestrator/factory_pipeline.py**

`PHASE_TO_STATE` maps old 26-phase names (`p00_intake`, etc.) to `PipelineState` values. The factory pipeline uses 12 new phase names. No mapping exists. Phase completion states in the UI may show stale/wrong values.

### PIPE-10 — CI Webhook Router Silently Never Mounts
**Severity: MEDIUM | File: gateway/api.py:271**

`from aether_os.phases.p08_cicd.webhook import ci_router` — this import fails silently (p08_cicd doesn't exist as a package). The `POST /ci/webhook` route is never registered. CI/CD webhook integrations are entirely non-functional.

---

## SECTION 6 — FRONTEND / UX FAILURES

### FE-01 — `DecisionsPanel` Crashes with TypeError on Mount
**Severity: CRITICAL | File: dashboard/src/components/DecisionsPanel.jsx:11, 32**

```javascript
const res = await api.get(`/factory/runs/${runId}/decisions`);
await api.post(`...`);
```
The `api` object has no `.get()` or `.post()` methods. This throws `TypeError: api.get is not a function` instantly on mount. DecisionsPanel is imported in the components directory but not yet used in any page — it is broken dead code that will crash if ever mounted.

### FE-02 — Marketplace "Install" Button Has No Handler
**Severity: CRITICAL | File: dashboard/src/pages/Marketplace.jsx:116**

The Install button has no `onClick`. The `api.installMarketplaceProfile()` method exists in `api.js` but is wired to nothing. The backend endpoint (`/marketplace/install/:id`) also does not exist in `gateway/api.py`. Both the frontend and backend sides are unimplemented.

### FE-03 — ClientPortal Shows Hardcoded Payroll Demo Data
**Severity: HIGH | File: dashboard/src/pages/ClientPortal.jsx:143–162**

"Core Requirements" section is static HTML: "automated payroll processing," "employee self-service portal," "PostgreSQL legacy database." Every client who opens their portal sees this same fake payroll spec regardless of their actual project. The `status.specification` from the API is fetched but never rendered.

### FE-04 — Compliance Page Renders White Cards in Dark App
**Severity: HIGH | File: dashboard/src/pages/Compliance.jsx:64–115**

All card elements use `bg-white`, `bg-gray-100`, `bg-gray-50`, `text-gray-400`. The rest of the app uses the dark theme (`--color-surface: #0a0a0f`). The Compliance page renders as glaring white boxes inside a near-black layout.

### FE-05 — Compliance Page Shows `undefined` for All Run IDs
**Severity: HIGH | File: dashboard/src/pages/Compliance.jsx:86, 89**

Uses `run.id` but the backend returns `run_id` (confirmed in `api.py:831`). All run IDs render as `undefined`. Download URLs become `/api/compliance/artifacts/undefined`.

### FE-06 — SSE Has No Reconnect Strategy
**Severity: CRITICAL | File: dashboard/src/pages/ProjectView.jsx:427–430**

```javascript
es.onerror = () => { es.close(); esRef.current = null; };
```
On any network hiccup, proxy timeout, or server restart, the SSE connection closes and is never re-established. The user sees a permanently frozen terminal for the remainder of the pipeline run with no notification. Given that SSE is already broken across workers (CRIT-01), this compounds the failure.

### FE-07 — No User Management UI (80K Employees, No Admin Panel)
**Severity: CRITICAL | Missing entirely**

The backend has `GET /admin/users` and `POST /admin/users/{user_id}/role`. Zero frontend pages call them. No UI to list, invite, deactivate, or bulk-manage users. Onboarding 80,000 employees one at a time via API calls is impossible.

### FE-08 — No Role-Based UI Differentiation
**Severity: CRITICAL | Missing entirely**

The frontend has no concept of `role`. Admins and regular users see exactly the same interface. Admin-only actions (kill switch, org-wide settings) are absent from the UI entirely.

### FE-09 — No SAML/SSO Login Page
**Severity: CRITICAL | File: dashboard/src/pages/Login.jsx**

Login page only supports email/password. No SSO button, no "Login with Azure AD / Okta / Google Workspace." For 80,000 employees this is a hard blocker.

### FE-10 — Multiple Redundant Polling Loops for Same Endpoint
**Severity: MEDIUM | File: Layout.jsx:13, Sidebar.jsx:17, Dashboard.jsx, ProjectsList.jsx**

Four separate independent polling loops hit `GET /api/factory/runs` on different intervals (5s, 10s, 15s). No shared cache. At 80K users × 4 polls per 5 seconds = catastrophic DB load from the UI alone.

### FE-11 — No Pagination on Any List
**Severity: HIGH | All list pages**

All list views fetch all records with no limit/offset. With hundreds or thousands of runs, the initial page load becomes unusable and the DOM grows unboundedly.

### FE-12 — No ARIA Labels on Any Interactive Element
**Severity: HIGH | All pages/components**

Zero `aria-label`, `aria-describedby`, `role="dialog"`, or `aria-modal` attributes in the entire codebase. No keyboard focus trapping in modals. Color contrast of muted text (#64748b on #0a0a0f ≈ 4.0:1) likely fails WCAG AA. Enterprise procurement frequently requires WCAG 2.1 AA certification.

### FE-13 — No Mobile Layout
**Severity: HIGH | File: dashboard/src/components/Layout.jsx:27**

Sidebar is always rendered at `w-60`. No hamburger menu, no responsive breakpoints on the outer layout. On screens narrower than ~800px, the layout overflows with `overflow-hidden` cutting off content. Dashboard uses `grid-cols-4` with no breakpoints.

### FE-14 — Tailwind v4 Config Conflict
**Severity: LOW | File: dashboard/tailwind.config.js**

`tailwind.config.js` (v3-style) is silently ignored in Tailwind v4. The active config is `index.css @theme {}`. Any developer editing `tailwind.config.js` expecting it to take effect will be confused.

### FE-15 — Additional Broken/Missing UI
| Finding | File | Severity |
|---|---|---|
| Dashboard "NEW PIPELINE" navigates to wrong route `/new` | Dashboard.jsx:133 | MEDIUM |
| `typeFilter` state declared but no UI uses it | ConnectorHub.jsx:164 | LOW |
| `CostPill` component defined but never imported | CostPill.jsx | LOW |
| `DecisionsPanel` component defined but never mounted | DecisionsPanel.jsx | CRITICAL (if mounted) |
| `tailwind.config.js` dead (Tailwind v4 ignores it) | tailwind.config.js | LOW |
| Settings file browser hardcodes `language-javascript` for all files | Settings.jsx:424 | LOW |
| NewProjectWizard only shows Ollama models (not Anthropic/Gemini) | NewProjectWizard.jsx:107 | MEDIUM |
| ErrorBoundary RETRY resets state but doesn't remount — can loop crash | ErrorBoundary.jsx:29 | MEDIUM |
| Login and ClientPortal have no ErrorBoundary wrapping | App.jsx:41,42 | MEDIUM |
| Compliance and Marketplace not in sidebar nav | Sidebar.jsx | MEDIUM |
| `CostDashboard` missing leading `$` in "On target" message | CostDashboard.jsx:117 | LOW |
| ClientPortal Privacy Policy / ToS links are inert `<span>` elements | ClientPortal.jsx:208 | LOW |
| ConnectorHub, PluginManager, Marketplace use light-theme in dark app | Multiple files | HIGH |

---

## SECTION 7 — LEGAL & REGULATORY COMPLIANCE

### LAW-01 — No Terms of Service, EULA, or Data Processing Agreement
**Severity: CRITICAL | Enterprise Contract Blocker**

No ToS, EULA, DPA, or Privacy Policy exists anywhere in the codebase or repository. An enterprise company cannot legally deploy software without a binding license agreement and a DPA (required under GDPR Article 28 for any data processor). This single gap is sufficient for a Fortune 500 legal team to reject the software before any technical review.

### LAW-02 — GDPR: No Right to Erasure (Article 17)
**Severity: CRITICAL | GDPR Fine: Up to 4% of Global Turnover**

No API endpoint deletes or anonymizes user data. The `AuditLog` table stores IP addresses and user activity with no retention limit, no deletion cascade, and no purge mechanism. `LLMCacheEntry` stores prompts potentially containing PII. `Snapshot` stores file content (may contain PII from requirements).

### LAW-03 — GDPR: No Right to Data Portability (Article 20)
**Severity: HIGH | GDPR Article 20**

No `/account/data-export` or Subject Access Request endpoint exists. Users cannot retrieve all data held about them.

### LAW-04 — GDPR: No Privacy Policy at Registration (Article 13)
**Severity: CRITICAL | GDPR Article 13**

`/auth/register` collects email addresses with no consent capture, no consent timestamp, and no Privacy Policy link. This is a non-negotiable GDPR requirement.

### LAW-05 — GDPR: LangSmith Tracing Enabled by Default, Data Leaves EU
**Severity: HIGH | GDPR Article 44 (Cross-Border Transfers)**

`LANGCHAIN_TRACING_V2=true` in `.env` defaults to on. User requirement prompts are sent to LangSmith (US-based) on every pipeline run without user disclosure or consent. The compliance report endpoint hardcodes `"data_processing_locations": ["us-east-1"]` — factually wrong and legally material for EU deployments.

### LAW-06 — EU AI Act: Risk Classification is Hardcoded "Medium Risk"
**Severity: HIGH | EU AI Act Article 13**

`Compliance.jsx:66` hardcodes `<span>Medium Risk</span>`. AetherOS generates AI systems for HR, finance, and critical infrastructure (all referenced in `core/domain_engine.py:79-199`). These could be Annex III high-risk under the EU AI Act. Presenting a hardcoded "Medium Risk" badge as a risk assessment is a material misrepresentation. `core/policy/compliance.py` has a real compliance engine that is never connected to this page.

### LAW-07 — No Backup / Disaster Recovery Plan
**Severity: HIGH | Contractual Liability**

No backup configuration, RTO/RPO documentation, or recovery runbook exists. The `deploy/setup_vps.sh` does not configure database backups. The default database is a single SQLite file with no replication.

### LAW-08 — No SLA Mechanism
**Severity: HIGH | Contractual**

The pricing page mentions "SLA Guarantees" for the Enterprise tier (`api.py:554`) but there is no backing implementation, uptime monitoring, or contractual definition. Promising SLAs with no mechanism to measure or enforce them is contractual liability.

### LAW-09 — No SCIM (User Provisioning)
**Severity: HIGH | Enterprise IT Requirement**

No SCIM 2.0 endpoints (`/scim/v2/Users`, `/scim/v2/Groups`). Bulk provisioning from Active Directory, Azure AD, or Okta is impossible. HR offboarding cannot automatically revoke access.

### LAW-10 — FastAPI Auto-Docs Exposed in Production
**Severity: MEDIUM | OWASP A05**

`/docs` (Swagger UI) and `/redoc` are accessible publicly in production, exposing the full API schema including all internal endpoints, request/response shapes, and authentication mechanisms.

### LAW-11 — Data Residency Hardcoded Incorrectly
**Severity: HIGH | GDPR Article 44, Contractual**

`api.py:1986`: `"data_processing_locations": ["us-east-1"]` — hardcoded in the compliance report regardless of where the server is deployed. An EU-hosted VPS reports US data processing. This is factually wrong and legally material.

---

## SECTION 8 — SECURITY VULNERABILITIES (OWASP)

| ID | OWASP | Finding | Severity | File:Line |
|---|---|---|---|---|
| SEC-01 | A01 | Mass assignment on `/account/settings` — any user can set `plan=enterprise` | CRITICAL | api.py:848 |
| SEC-02 | A02 | JWT signing key committed to git | CRITICAL | .env |
| SEC-03 | A01 | Cross-tenant run access (missing org_id in changelog query) | CRITICAL | api.py:1167 |
| SEC-04 | A05 | SAML dead code — SSO non-functional | CRITICAL | auth_saml.py |
| SEC-05 | A07 | No token revocation — 7-day JWT | HIGH | auth.py:55 |
| SEC-06 | A07 | Login no account active check | HIGH | api.py:437 |
| SEC-07 | A01 | Unauthenticated global-insights exposes cross-tenant data | HIGH | api.py:1058 |
| SEC-08 | A05 | `FORCE_HTTPS` defaults to false | HIGH | api.py:156 |
| SEC-09 | A02 | API keys hashed with SHA-256, not bcrypt | MEDIUM | auth.py:36 |
| SEC-10 | A07 | JWT in URL for SSE (logged in nginx) | MEDIUM | api.py:1344 |
| SEC-11 | A07 | JWT in URL for compliance download (logged in browser history) | MEDIUM | Compliance.jsx:40 |
| SEC-12 | A03 | Prompt injection — user requirements passed to LLM unsanitized | MEDIUM | api.py:606 |
| SEC-13 | A05 | Generated apps ship with `allow_origins=["*"]` | HIGH | p03_scaffolding/task_agent.py:67 |
| SEC-14 | A05 | `unsafe-inline` in Content-Security-Policy | MEDIUM | api.py:151 |
| SEC-15 | A02 | Legacy hardcoded JWT fallback secret in identity.py | MEDIUM | core/identity/identity.py:20 |
| SEC-16 | A04 | Symlink escape bypasses path traversal guard | LOW | api.py:1660 |
| SEC-17 | A05 | FastAPI /docs and /redoc publicly accessible | MEDIUM | api.py |
| SEC-18 | A06 | Wide version pinning, no automated CVE scanning | MEDIUM | requirements.txt |
| SEC-19 | A10 | Webhook URL field stored without SSRF validation | MEDIUM | core/models.py:157 |
| SEC-20 | A07 | Rate limiting 8× more permissive without Redis (per-worker) | HIGH | core/rate_limiter.py:44 |

---

## SECTION 9 — MISSING ENTERPRISE FEATURES

The following features are required for an 80,000-employee enterprise deployment and do not exist:

| Feature | Priority | Notes |
|---|---|---|
| SAML 2.0 / OIDC SSO | CRITICAL | auth_saml.py is dead code; needs full FastAPI integration |
| SCIM 2.0 provisioning | HIGH | No bulk user management from identity provider |
| Multi-Factor Authentication | HIGH | Required by enterprise security policies and cyber insurance |
| User management admin UI | CRITICAL | No frontend for listing, inviting, or deactivating users |
| Role-based UI (admin vs member vs viewer) | HIGH | All roles see identical interface |
| Kill switch UI | HIGH | Backend stubs exist but no UI and stubs don't work |
| Token revocation / logout endpoint | HIGH | `/auth/logout` missing entirely |
| Audit log export (CSV/JSON) | HIGH | Table exists, export endpoint missing |
| Run list pagination | HIGH | All runs fetched on every load |
| Run search/filter (by status, date, domain) | HIGH | Only text search exists |
| Webhook management UI | MEDIUM | Backend is stub; frontend missing |
| User profile / password change page | MEDIUM | No way to change password |
| Theme personalisation (dark/light) | MEDIUM | Hardcoded dark only |
| Mobile responsive layout | HIGH | Sidebar always visible, no hamburger |
| WCAG 2.1 AA accessibility | HIGH | Zero ARIA labels anywhere |
| Notification system | MEDIUM | No in-app or email notifications |
| Org switcher for multi-tenant users | MEDIUM | No UI for org context |
| Bulk pipeline operations | MEDIUM | No multi-select or bulk cancel/pause |
| Database backup & restore | CRITICAL | No backup mechanism at all |
| Privacy Policy / ToS in UI | CRITICAL | Required at registration under GDPR |
| Data export (GDPR Subject Access Request) | CRITICAL | Missing API + UI |
| Right to erasure endpoint | CRITICAL | Missing entirely |

---

## SECTION 10 — WHAT ACTUALLY WORKS (End-to-End)

| Feature | Status | Notes |
|---|---|---|
| User registration + login (email/password) | ✅ Working | Email must be unique; JWT issued correctly |
| JWT authentication | ✅ Working | AETHER_SECRET_KEY correctly validated |
| Org isolation in DB queries | ✅ Working | Most routes correctly filter by org_id |
| `/factory/start` → pipeline launch | ✅ Working | Launches FactoryPipeline correctly |
| P02 Architecture generation | ✅ Working | LLM call with domain-aware fallback |
| P03 Scaffolding | ✅ Working | 10 domain templates, directory structure created |
| P05 Frontend generation | ✅ Working | CDN React SPA or vanilla-JS fallback |
| P07b Self-healing | ✅ Working | pytest + LLM fix loop functional |
| P11 Docker deployment | ✅ Working | Builds and runs container, polls /health |
| Run status polling | ✅ Working | `/factory/runs/{run_id}` returns phase status |
| File browser | ✅ Working | Tree + file content with path traversal guard |
| LLM fallback chain | ✅ Working | Anthropic → Gemini → Ollama graceful degradation |
| Cost tracking | ✅ Working | TokenBudgetManager correctly tracks usage |
| Settings (API keys, phase config) | ✅ Working | Reads/writes .env and phase_configs table |
| Audit logs | ✅ Working | AuditLog table populated; /audit/logs endpoint functional |
| API key creation + auth | ✅ Working | aesk_ prefix tokens, SHA-256 hash (see SEC-09) |
| Client portal (public project view) | ✅ Working | Except hardcoded spec content (FE-03) |
| Phase enable/disable | ✅ Working | phase_configs table correctly controls pipeline |
| Memory search | ⚠️ Partial | Returns empty due to PIPE-05 (matcher.py import fail) |
| Compliance artifacts ZIP | ⚠️ Partial | Generates zip but compliance content is stub |
| SSE streaming | ⚠️ Single-worker only | Broken with multiple workers (CRIT-01) |
| Pause / Cancel / Resume | ⚠️ Single-worker only | Broken with multiple workers (CRIT-01) |
| Human approval gate | ❌ Not working | Gate exists but pipeline ignores it |
| Webhooks | ❌ Stub | All responses hardcoded |
| Marketplace | ❌ Stub | Returns empty list; install button has no handler |
| Agent mesh | ❌ Not implemented | 14 agent names declared; 0 implemented |
| Backend code generation (P04) | ❌ Broken import | Sub-phases fail silently; no backend code produced |
| Security review (P06) | ❌ Broken import | Always passes; no review runs |
| Tests (P07) | ❌ Broken import | All 4 sub-phases fail; tests never run |
| CI/CD (P08) | ❌ Broken import | All 6 sub-phases fail; no CI/CD produced |
| Documentation (P10) | ❌ Broken import | All 3 sub-phases fail; no docs produced |

---

## SECTION 11 — PRIORITY FIX LIST (By Launch Impact)

### Must Fix Before Any Demo (System Won't Work)
1. **CRIT-02** — Fix `_legacy/` import path: update all consolidated task_agents to import from `aether_os.phases._legacy.*`
2. **CRIT-03** — Uncomment `asyncpg>=0.29.0` in requirements.txt
3. **CRIT-04** — Add `from fastapi import Request` to api.py imports
4. **CRIT-06** — Fix `ProtectHome=yes` in aetheros.service
5. **AUTH-01** — Rotate all secrets in `.env`, add `.env` to `.gitignore`
6. **CRIT-09** — Store `asyncio.create_task()` references to prevent GC

### Must Fix Before Enterprise Deployment
7. **CRIT-01** — Move PIPELINE_EVENTS/PIPELINE_CONTROL to Redis
8. **CRIT-08** — Fix mass assignment in `/account/settings` with field allowlist
9. **AUTH-03** — Implement `/auth/logout` with Redis token blacklist
10. **AUTH-02** — Wire SAML SSO into FastAPI (or implement OIDC)
11. **AUTH-04** — Add `User.is_active == True` filter to login query
12. **AUTH-06** — Add `org_id` check to changelog endpoint
13. **CRIT-05** — Fix `/pipeline/start` run_id mismatch
14. **DB-02** — Wrap sync sqlite3 calls in `asyncio.to_thread()`
15. **DB-03** — Add PgBouncer or set `max_connections` appropriately

### Required for Legal Compliance
16. **LAW-01** — Draft ToS, EULA, DPA, Privacy Policy
17. **LAW-02** — Implement `DELETE /account` (GDPR erasure)
18. **LAW-03** — Implement `GET /account/data-export` (GDPR portability)
19. **LAW-04** — Add consent capture + Privacy Policy link at registration
20. **LAW-05** — Make LangSmith opt-in (`LANGCHAIN_TRACING_V2=false` default)
21. **LAW-07** — Implement database backup (pg_dump cron or managed DB)
22. **SEC-13** — Remove `allow_origins=["*"]` from scaffolding template

### Quality of Life / Enterprise Polish
23. **FE-07** — Build user management admin UI
24. **FE-09** — Build SAML/SSO login page
25. **FE-11** — Add pagination to all list views
26. **FE-10** — Replace 4 polling loops with shared React Context + single interval
27. **FE-12** — Add ARIA labels for WCAG 2.1 AA
28. **FE-13** — Make layout responsive (hamburger sidebar)
29. **FE-04/FE-14/FE-15** — Audit all pages for dark-theme consistency
30. **PIPE-01** — Wire human-in-the-loop gate to actually pause pipeline

---

## SECTION 12 — ESTIMATED REMEDIATION TIMELINE

| Phase | Work | Duration |
|---|---|---|
| **Phase 0: Emergency Fixes** | Items 1–6 above (system won't boot/work) | 1–2 days |
| **Phase 1: Core Functionality** | Items 7–15 (scale + auth) | 1–2 weeks |
| **Phase 2: Legal Compliance** | Items 16–22 (GDPR, ToS, backup) | 1–2 weeks (legal review needed) |
| **Phase 3: Enterprise Features** | Items 23–30 (admin UI, SSO, UX) | 2–3 weeks |
| **Phase 4: Pipeline Completion** | Fix _legacy imports, wire agents, implement stubs | 2–4 weeks |

**Realistic production-ready date for 80K-employee deployment: 6–8 weeks from today.**

May 11 is feasible only for a **limited internal beta** (single organization, no enterprise SSO, with all warnings disclosed to the client).

---

*Audit conducted: 2026-05-09 | Scope: 47 source files, 2,351-line gateway, 12 pipeline phases, 6 orchestrator files, 13 React pages, 15+ components | Total findings: 210+*
