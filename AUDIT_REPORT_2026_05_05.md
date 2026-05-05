# AetherOS Audit Report
**Date:** May 5, 2026  
**Auditor:** Claude Code (claude-sonnet-4-6)  
**Scope:** Gemini-built Phases D–12 audit and critical bug fixes

---

## COMPLETED BY GEMINI — VERIFIED WORKING

| Phase / Feature | Status |
|---|---|
| Core module structure (rate_limiter, artifact_store, decisions, compliance, security) | ✓ All present |
| Gateway routes: auth register/login, factory/start, factory/runs, preferences, marketplace | ✓ Verified 200 OK |
| Intelligence global-insights endpoint | ✓ 200 OK |
| Account projects, preferences (GET/PUT) | ✓ 200 OK |
| Factory run lifecycle: pause/resume/cancel/rerun/priority | ✓ Routes present |
| Factory run detail: stream, files, file-content, preview, test-report | ✓ Routes present |
| System health, costs, observability endpoints | ✓ Routes present |
| Deployment endpoints (deploy/undeploy/list) | ✓ Routes present |
| Settings: api-keys, test-provider, phase config | ✓ Routes present |
| Database migrations (all 10 revisions applied at head) | ✓ Confirmed |
| Client portal router | ✓ Mounted |
| CLI (aetheros.py) | ✓ Present |
| Launch materials (DEMO_SCRIPT, PRODUCT_HUNT, SHOW_HN, TWITTER_THREAD, TECHNICAL_FAQ) | ✓ Present |
| Phase directories (p00–p15) | ✓ 35 phase dirs |
| alembic migrations (10 revisions) | ✓ All at head |

---

## COMPLETED BY GEMINI — PARTIAL (API only, no frontend)

| Feature | What Exists | What's Missing |
|---|---|---|
| Preferences/workspace customisation | Backend PUT/GET `/account/preferences` works | No dedicated Settings/Preferences page in React dashboard |
| Marketplace | `POST /marketplace/publish` works | No marketplace browse/search UI; only `ClientPortal.jsx` references it |
| Compliance artifacts | Model + generator class exist | `/compliance/artifacts` and `/compliance/org-report` routes not registered in api.py |
| Decision engine | `DecisionEngine` class exists | No frontend decision panel; `/factory/runs/{run_id}/decisions` route missing |
| Parallel run comparison | Schema has `group_id` migration | No `/factory/start/parallel`, no `/factory/parallel` routes; no CompareView UI |
| Audit logs | audit.jsonl file writes observed | No `/audit/logs` API route exposing them |
| Admin panel | `ArtifactGenerator`/compliance models exist | No `/admin/users` or `/admin/kill-all` route |
| Webhook management | Webhooks model exists | No `/webhooks` CRUD route |
| Storage quota display | Storage tracking in org model | No `/account/storage` endpoint returning usage |
| SAML auth | `gateway/auth_saml.py` file exists | `/auth/saml` route not registered |
| Import codebase | — | `/account/import-codebase` route missing |
| VS Code extension | — | `vscode-extension/` directory not created |

---

## MISSING ENTIRELY

| Item | Severity |
|---|---|
| `/audit/logs` — no API route for audit log retrieval | Medium |
| `/account/storage` — no storage quota endpoint | Medium |
| `/compliance/artifacts` + `/compliance/org-report` routes | Medium |
| `/factory/runs/{run_id}/decisions` — decision review endpoint | Medium |
| `/factory/runs/{run_id}/kill` — force-kill route (only pause/cancel exist) | Low |
| `/factory/start/parallel` + `/factory/parallel` — parallel run group routes | Low |
| `/webhooks` CRUD | Low |
| `/admin/users` + `/admin/kill-all` | Low |
| `/account/import-codebase` | Low |
| `/auth/saml` route registration | Low |
| `vscode-extension/` directory | Low |
| Frontend decisions panel | Medium |
| Frontend parallel comparison view | Low |
| Frontend marketplace browse/search page | Low |
| Frontend compliance dashboard tab | Low |

---

## CRITICAL BUGS FIXED IN THIS SESSION

### Bug 1 — `code_scanner.py`: `return` outside function (SyntaxError)
**File:** `core/security/code_scanner.py`  
**Problem:** The domain-specific checks block (lines 79–107) slipped outside the `scan_project` method due to incorrect indentation. Caused `SyntaxError: 'return' outside function`.  
**Fix:** Re-indented the `if domain == "fintech"` block and `return ScanResult(...)` to be inside `scan_project`.

### Bug 2 — `decision_engine.py`: `from .db import Base` — module not found
**File:** `core/decisions/decision_engine.py`  
**Problem:** Imported `from .db import Base` but no `db.py` existed in `core/decisions/`.  
**Fix:** Created `core/decisions/db.py` that re-exports `Base` from `aether_os.core.db`.

### Bug 3 — `artifact_generator.py`: class named `ArtifactGenerator` not `ComplianceArtifactGenerator`
**File:** `core/compliance/artifact_generator.py`  
**Problem:** Class was `ArtifactGenerator`; all imports and type hints elsewhere expected `ComplianceArtifactGenerator`.  
**Fix:** Renamed primary class to `ComplianceArtifactGenerator`, added `ArtifactGenerator = ComplianceArtifactGenerator` alias for backwards compatibility.

### Bug 4 — `.env` `DATABASE_URL` relative path causing column-not-found on startup
**File:** `.env`  
**Problem:** `DATABASE_URL=sqlite+aiosqlite:///aether_os.db` (3 slashes = relative path) pointed to `./aether_os.db` in the project directory. This file had no `user_preferences` column because alembic ran migrations against `~/.aether_os/aether_os.db`. Every `/auth/register` call failed with `OperationalError: no such column: users.user_preferences`.  
**Fix:** Commented out the `DATABASE_URL` line so the server defaults to `~/.aether_os/aether_os.db` which has all migrations applied at head.

---

## REMAINING WORK BEFORE LAUNCH

Ordered by priority:

1. **Register missing API routes** (2–3 hours)
   - `/audit/logs` — read from `audit.jsonl`
   - `/account/storage` — return `org.storage_used_mb` and limit
   - `/compliance/artifacts` + `/compliance/org-report` — wire `ComplianceArtifactGenerator`
   - `/factory/runs/{run_id}/decisions` — query DecisionEngine
   - `/webhooks` CRUD — basic list/create/delete
   - `/admin/users` + `/admin/kill-all` — owner/admin-only

2. **Frontend: decisions panel** (1–2 hours)
   - Add "Decisions" tab to `ProjectView.jsx`
   - Poll `/factory/runs/{run_id}/decisions`, render pending decisions with approve/reject UI

3. **Frontend: compliance/audit tab** (1 hour)
   - Add Compliance section to Settings or a dedicated page
   - Fetch `/compliance/artifacts` and `/audit/logs`

4. **Frontend: marketplace browse page** (1–2 hours)
   - New page `Marketplace.jsx` with search + profile cards
   - Wire to `GET /marketplace/profiles` (add this route too)

5. **Frontend: account storage widget** (30 mins)
   - Add storage bar to Dashboard or Settings using `/account/storage`

6. **VS Code extension scaffold** (2–3 hours)
   - Create `vscode-extension/` with basic `package.json`, `extension.js`, and one command

7. **Parallel run comparison** (3–4 hours)
   - Add `/factory/start/parallel` route
   - Add side-by-side comparison view in frontend

8. **Fix Pydantic deprecation warnings** (30 mins)
   - `orchestrator/pipeline.py:289` — replace `.dict()` with `.model_dump()`

---

## FRONTEND STATUS

**React dashboard exists** at `dashboard/src/` with the following pages:
- `Dashboard.jsx`, `ProjectsList.jsx`, `ProjectView.jsx`, `PhaseDetail.jsx`
- `Settings.jsx`, `Login.jsx`, `NewProject.jsx`, `NewProjectWizard.jsx`
- `ClientPortal.jsx`

**Missing frontend components** (specified but not built):
- No `DecisionsPanel.jsx` or decisions tab in ProjectView
- No `ParallelCompare.jsx` or group comparison view
- No `Marketplace.jsx` browse page
- No `ComplianceDashboard.jsx` or compliance tab
- No dedicated workspace preferences page (preferences API works but no UI)
- No audit log viewer

The dashboard covers the core factory workflow (projects list → run → phase detail → files/preview). Advanced features (decisions, compliance, marketplace, parallel) are backend-only or absent.

---

## TEST RESULTS

```
165 passed, 3 skipped  (full suite, 32s)
```

All core tests pass. The 3 skipped are infrastructure-dependent (LangSmith, external LLM).

---

## RECOMMENDATION

**Not quite ready for unguided demo — but ready for a scripted/controlled demo recording.**

The happy path (register → start project → watch phases → view files) works end-to-end. The server starts cleanly, auth works, pipeline starts and streams events, and 165 tests pass.

What would break in an unscripted demo: clicking into Decisions, Compliance, Marketplace, or Admin sections — those show 404s or blank pages. For a demo recording with a prepared script those sections can be avoided.

**Estimate to full launch readiness:** 1–2 days of focused backend route registration (step 1 above) + 1–2 days of frontend component work.

---

*Report generated by Claude Code audit session, 2026-05-05*
