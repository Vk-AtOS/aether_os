# AetherOS Factory — Frontend Audit Report
Generated: 2026-04-25  
Scope: All 17 frontend source files + gateway/api.py

---

## SECTION 1 — BACKEND ROUTE INVENTORY

Every route in `gateway/api.py` with auth requirement and return shape:

| Method | Path | Auth | Returns |
|--------|------|------|---------|
| GET | `/` | No | Redirect → `/dashboard/` |
| GET | `/health` | No | `{status, timestamp, service, version}` |
| POST | `/auth/login` | No | `{access_token, token_type, expires_hours}` |
| POST | `/pipeline/start` | Yes | `{run_id, status, message}` — OLD pipeline (orchestrator.pipeline) |
| GET | `/pipeline/status/{run_id}` | Yes | Run detail from ledger |
| POST | `/pipeline/approve/{ticket_id}` | Yes | `{ticket_id, decision, decided_by, timestamp}` |
| POST | `/ci/webhook` | (from CI router) | CI failure handler |
| POST | `/factory/start` | Yes | `{run_id, status, message}` — NEW 10-phase factory |
| GET | `/factory/runs` | Yes | `[{id, project_name, status, current_phase, phases:{}, cost, started_at(ms), finished_at(ms)}]` |
| GET | `/factory/runs/{run_id}` | Yes | Single run with `phases:{phase_name:{status,updated_at}}` dict |
| GET | `/factory/runs/{run_id}/files` | Yes | `{run_id, tree:[{name, type, path, children?, size_bytes?, extension?}]}` |
| GET | `/factory/runs/{run_id}/file-content` | Yes | `{path, content, language, size_bytes, truncated, type}` |
| GET | `/system/health` | Yes | `{status, message, llm_provider, anthropic_available, gemini_available, ollama_available, version, tests_passing, database, memory_store}` |
| GET | `/system/costs` | Yes | `{today_usd, week_usd, total_usd, runs_today, avg_cost_per_run}` — **NO `tokens_today`** |
| GET | `/settings/api-keys` | Yes | `{anthropic, google, openai, primary_llm, ollama_model}` — masked values |
| POST | `/settings/api-keys` | Yes | `{success, provider, message}` |
| POST | `/settings/test-provider` | Yes | `{success, provider, model, message}` or `{success:false, error}` |
| POST | `/settings/phases/{phase_name}/config` | Yes | `{success, phase, enabled, priority}` — accepts ONLY 10 long-form names |
| GET | `/settings/phases/config` | Yes | Array of `{phase_name, enabled, priority}` — 10 long-form names |
| GET | `/dashboard` / `/dashboard/{path}` | No | SPA index.html |
| Portal routes | `/portal/...` | Public | Mounted from `client_portal/routes` |

**Key backend facts for bugs below:**
- `/system/costs` has **no `tokens_today` field**
- `/factory/runs` returns `phases` as a **dict**, not an array
- `/pipeline/start` expects field `requirement`, not `raw_input`
- `/settings/phases/{phase}/config` validates against 10 long-form names (`p01_intake_requirements`, etc.), not short codes
- `/factory/runs/{run_id}/files` returns a **nested tree**, not a flat array

---

## SECTION 2 — PAGE-BY-PAGE AUDIT

---

PAGE: Dashboard (Home / Overview)
ROUTE: /
COMPONENT: pages/Dashboard.jsx
SIDEBAR LINK: exists (Dashboard, icon: LayoutDashboard)

CURRENT STATE:
- Renders 4 stat cards: Active Runs, Completed Today, Total Cost Today, Tokens Today
- Renders LLM warning banners (no-LLM and Ollama-only)
- Renders a table of RUNNING-only runs (filters status === 'running' || 'RUNNING')
- Polls fetchRuns / fetchCosts / fetchHealth every 5 seconds
- API calls:
  - api.listRuns()       → GET /factory/runs        → returns real data ✓
  - api.getCosts()       → GET /system/costs         → returns real data ✓
  - api.getHealth()      → GET /system/health        → returns real data ✓

KNOWN BUGS:
- BUG-D1: `costs.tokens_today` is always undefined. `/system/costs` does not return this field. The Tokens Today stat always shows "—".
- BUG-D2: `run.phases` from `/factory/runs` is a dict `{}`. PhaseBar expects an array with `.find(p => p.id === key)`. Array.isArray({}) is false → `phaseList = []` → all 26 blocks render gray. Phase progress bars are permanently empty.
- BUG-D3: Status case inconsistency. Backend stores lowercase 'running'. Filter for `r.status === 'RUNNING'` never matches. `'completed'` and `'PASSED'` are similarly mixed. Correct filter is `r.status === 'running'` only.
- BUG-D4: Interval leaks. The setInterval in `useEffect` has `[runs.length]` as dependency. Every time a run is added/removed, the old interval is cleared and a new one starts. When `runs.length === 0`, `fetchRuns` is called every 5s, but after first fetch resolves (even with an empty array), `runs.length` changes 0→0 (no change), so the effect does NOT re-run, which is fine. But if length changes 0→N, old interval clears and new one starts — the old interval is already cleared, so this is acceptable. Low severity.
- BUG-D5: No error state. If `listRuns()` throws (backend down), the loading spinner disappears and the table shows "No active runs found" — no indication of a network error.
- BUG-D6: Dashboard only shows RUNNING runs. Completed/failed runs are invisible. There is no "recent runs" section.

BACKEND WIRING:
- api.listRuns() → GET /factory/runs → returns real data ✓
- api.getCosts()  → GET /system/costs → real data ✓ (tokens_today missing from backend)
- api.getHealth() → GET /system/health → real data ✓

WHAT IT SHOULD DO (ideal state):
- Show 4 correct stats including actual token count (backend must add tokens_today)
- Show active runs table with working phase progress bars
- Show a "recent completed" section below active runs
- Show full network error state if API is unreachable

GAP: tokens_today missing from backend response; phase progress bars broken due to phases dict vs array mismatch; no completed runs shown; no error state.

---

PAGE: Projects List
ROUTE: /projects
COMPONENT: pages/ProjectsList.jsx
SIDEBAR LINK: exists (Projects, icon: List)

CURRENT STATE:
- Fetches api.listRuns() → GET /factory/runs on mount, polls every 10s
- Shows all runs (not just running), with search filter
- Each row shows: project name, status badge, 10-dot progress strip, started time, eye icon
- Row click and eye icon navigate to /project/:id
- Empty state: HexLogo + "Start First Project" button (opens modal)
- Search: filters by project_name or run_id

KNOWN BUGS:
- BUG-PL1: `run.run_id` doesn't exist. `/factory/runs` returns `id` (from ledger), not `run_id`. Navigation `navigate('/project/${run.run_id || run.id}')` falls back to `run.id` correctly, but the shortened display `(run.run_id || run.id || '').slice(0, 8)` always shows `run.id`. This is functional but inconsistent with how api.js uses `run_id` naming.
- BUG-PL2: `ProgressDots` accesses `run.phases[p]?.status` where `run.phases` is a dict. This actually WORKS correctly (dict access by key), but `getCompletedCount` logic is partially broken: if `run.phases` has entries but `run.current_phase` is also set, it uses `PHASES.indexOf(run.current_phase)` which returns -1 if the phase name doesn't exactly match the short list of 10 phase keys. The 10 hardcoded PHASES keys in ProjectsList.jsx (`p01_intake_requirements`, etc.) should match the backend's phase keys — this is likely correct.
- BUG-PL3: No error state. If `listRuns()` fails, `loading` goes false via finally, and the page shows "0 projects total" with EmptyState.
- BUG-PL4: Search does not reset when navigating away and back (state is local to component, which re-mounts). Low severity.

BACKEND WIRING:
- api.listRuns() → GET /factory/runs → returns real data ✓

WHAT IT SHOULD DO (ideal state):
- All existing behavior is correct for listing/filtering/navigating
- Add error state when API fails
- Add "sort by" controls (date, status)
- Fix run_id vs id naming inconsistency

GAP: No error state; id naming inconsistency; minor progress logic edge case.

---

PAGE: Project View ← PRIORITY (blanking on click)
ROUTE: /project/:id
COMPONENT: pages/ProjectView.jsx
SIDEBAR LINK: missing (accessed via row click in Dashboard/ProjectsList)

CURRENT STATE:
- Fetches api.getRun(id) → GET /factory/runs/{run_id}
- Fetches api.getRunFiles(id) → GET /factory/runs/{run_id}/files
- Shows: left phase sidebar, run summary card, artifact file browser (tree + content viewer), agent events log
- Phase sidebar links are <a href="#phase-{p}"> anchor tags
- "VIEW PORTAL" button navigates to /portal/{run_id}

KNOWN BUGS:
- BUG-PV1 ★ CRASH — HOOKS VIOLATION (root cause of blanking):
  Lines 298-302 call `const [curlCopied, setCurlCopied] = useState(false)` AFTER conditional early returns:
    line 233: `if (loading && !run) return <Loader />`
    line 242: `if (error) return <ErrorPanel />`
    line 272: `if (!run) return <NotFound />`
  React requires all hooks to be called unconditionally on every render. When the component renders the loading state on first mount (loading=true, run=null), it calls all hooks up to line 145 then returns early — only ~8 hooks are called. On the next render (loading=false, run=populated), all 10 hooks are called including the conditional useState. React detects a different number of hook calls between renders and throws "Rendered more hooks than during the previous render", causing the ErrorBoundary to display or the component to go blank.
  Fix: move `const [curlCopied, setCurlCopied] = useState(false)` to the top of the component with all other state declarations.

- BUG-PV2: Phase sidebar links do not navigate to PhaseDetail. They use `<a href="#phase-{p}">` (anchor scroll), but no element has id="phase-p01_intake_requirements" etc. on the page. Clicking a phase name scrolls nowhere. The PhaseDetail page at /project/:id/phase/:name is UNREACHABLE from this component.

- BUG-PV3: `run.events` may not exist. The `/factory/runs/{run_id}` backend endpoint does not explicitly add an `events` array to the ledger detail. If the ledger's `get_run_detail` doesn't return events, `run.events || []` safely returns [] and the log shows "No events recorded." Not a crash, but events never show.

- BUG-PV4: `getPhaseStatus` uses `run.phases?.[phaseId]` dict access. This works. But the phase list is hardcoded to 10 phases. If backend generates phases with different keys (e.g. `p00`, `p04a`), they won't appear in the sidebar.

- BUG-PV5: Elapsed timer. `run.started_at` is in **milliseconds** (backend converts to ms). `Date.now() - run.started_at` is in ms → `Math.floor(.../ 1000)` gives seconds. This is correct. But the elapsed timer keeps running even after the run completes (no `run.status !== 'running'` guard on the timer interval).

- BUG-PV6: File tree assumes `res.data?.tree || []`. The backend returns `{run_id, tree: [...]}`. This is correct. ✓

BACKEND WIRING:
- api.getRun(id)      → GET /factory/runs/{id} → returns real data ✓
- api.getRunFiles(id) → GET /factory/runs/{id}/files → returns real data ✓
- api.getFileContent  → GET /factory/runs/{id}/file-content → returns real data ✓

WHAT IT SHOULD DO (ideal state):
- Show live-updating phase progress as pipeline runs
- Phase sidebar items should be clickable links to /project/:id/phase/:name
- Events log should stream in real time
- Show cost accumulation
- Stop elapsed timer when run completes

GAP: Component crashes due to hooks violation (BUG-PV1); PhaseDetail is unreachable; events log never populates; elapsed timer runs forever.

---

PAGE: Phase Detail
ROUTE: /project/:id/phase/:name
COMPONENT: pages/PhaseDetail.jsx
SIDEBAR LINK: missing (unreachable from any navigation in current UI)

CURRENT STATE:
- Fetches api.getRun(id) → GET /factory/runs/{run_id}
- Extracts phase-specific data from run.phases
- Has 4 tabs: Output, Gate Result, Memory Used, Raw Artifacts
- Back button navigates to /project/:id

KNOWN BUGS:
- BUG-PD1 ★ UNREACHABLE — no navigation in the app goes to this route. ProjectView's phase sidebar uses anchor tags instead of React Router links. This entire page is dead code from a navigation perspective.

- BUG-PD2: Phase data extraction is broken. Backend returns `run.phases` as a dict: `{p01_intake_requirements: {status, updated_at}, ...}`. The code does:
  ```js
  const phases = Array.isArray(run.phases) 
    ? run.phases 
    : Object.values(run.phases || {});
  const phase = phases.find(p => p.id === name || p.name === name)
  ```
  `Object.values()` produces `[{status: 'passed', updated_at: 1234}]` — objects with NO `id` or `name` fields. `.find()` always returns `undefined`. So `phase = {}`, and `phaseData` is populated entirely with defaults: empty files, 0 confidence, no memories.

- BUG-PD3: Output tab renders `Object.entries(phaseData.files || {})` — files is always `{}` due to BUG-PD2. Tab always shows blank.

- BUG-PD4: Copy and Download buttons in `renderFileContent` have no click handlers (`<button>` with no `onClick`). Buttons are visually present but non-functional.

- BUG-PD5: Memory tab: `(mem.score * 100).toFixed(0)` — if `mem.score` is undefined (likely given BUG-PD2), renders "NaN". Not a crash but bad UX.

- BUG-PD6: Gate Result tab: hardcoded "Confidence Threshold: 0.85 (PASSED)" string is always shown regardless of actual confidence.

BACKEND WIRING:
- api.getRun(id) → GET /factory/runs/{id} → returns real data ✓
- BUT phase extraction logic is wrong → no real phase data is displayed ✗

WHAT IT SHOULD DO (ideal state):
- Show the actual LLM-generated output for that phase (files, analysis)
- Show gate confidence score and issues
- Show which memory snippets were retrieved and used
- List and allow download of raw artifacts

GAP: Page is unreachable from UI; phase data extraction always returns empty defaults; Copy/Download non-functional; entire page is effectively blank even when reached via direct URL.

---

PAGE: Settings
ROUTE: /settings
COMPONENT: pages/Settings.jsx
SIDEBAR LINK: exists (Settings, icon: Settings)

CURRENT STATE:
- On mount: parallel fetches of health, costs, runs list, phase configs
- Left 2/3: API Key Management, Phase Controls (26-phase accordion), Project File Browser
- Right 1/3: LLM Backend Status, Factory Stats, Version Info
- API calls:
  - api.getHealth()      → GET /system/health
  - api.getCosts()       → GET /system/costs
  - api.listRuns()       → GET /factory/runs
  - api.getPhaseConfigs() → GET /settings/phases/config

KNOWN BUGS:
- BUG-S1 ★ CRITICAL: GET /settings/api-keys exists (added in previous session) but Settings.jsx NEVER calls it on mount. API key input fields are always empty (`apiKeys: {anthropic: '', gemini: ''}`) even when keys are configured. User has no visual feedback that a key is already set.

- BUG-S2 ★ Phase name mismatch (26 vs 10). Settings lists 26 short-code phases:
  `['p00', 'p01', 'p02', 'p03', 'p04a', 'p04b', ..., 'p14']`
  Backend `POST /settings/phases/{phase_name}/config` validates against 10 long-form names:
  `['p01_intake_requirements', 'p02_architecture', ...]`
  Every "Save Config" call from Settings will return HTTP 400 "Invalid phase name". No save ever succeeds.

- BUG-S3: `tokens_today` missing. `GET /system/costs` returns no `tokens_today` field. "Tokens Today" in Factory Stats always shows "—".

- BUG-S4: File Browser format mismatch. `api.getRunFiles(runId)` returns `{run_id, tree: [{name, type, path, children?}]}`. Settings does `files = res.data || []` — `res.data` is `{run_id, tree: [...]}` (an object, not array). Then `files.forEach(f => ...)` iterates an object, which only iterates enumerable string keys (`run_id`, `tree`). The grouping logic `f.phase || f.path.split('/')[0]` receives `'run_id'` and `'[{...}]'` as `f`, so `f.path` is undefined. `runFiles` will be empty or garbage. File browser never shows files.

- BUG-S5: Phase configs response mismatch. `GET /settings/phases/config` returns an array:
  `[{phase_name: 'p01_intake_requirements', enabled: true, priority: 'normal'}]`
  Settings does `setPhaseConfigs(pcRes.value.data || {})` — stores array as object. Then accesses `phaseConfigs[p]` with short keys like `phaseConfigs['p00']`. Array index lookup on a long-name array returns undefined for all. `PhaseConfigPanel` always sees `config = {}`.

- BUG-S6: `hljs.highlightElement` is called but the `<code>` element has class `language-javascript` hardcoded. All file types (Python, YAML, JSON, etc.) get JavaScript highlighting.

- BUG-S7: No loading state shown during initial data fetch. On slow connections, all sections are blank until all 4 parallel requests resolve.

BACKEND WIRING:
- api.getHealth()       → GET /system/health    → real data ✓
- api.getCosts()        → GET /system/costs     → real data ✓ (tokens_today absent)
- api.listRuns()        → GET /factory/runs     → real data ✓
- api.getPhaseConfigs() → GET /settings/phases/config → real data ✓ (but frontend mismatch)
- api.saveApiKeys()     → POST /settings/api-keys → real data ✓
- api.testProvider()    → POST /settings/test-provider → real data ✓
- api.savePhaseConfig() → POST /settings/phases/{phase}/config → 400 always (name mismatch)
- GET /settings/api-keys → real data ✓ (never called by frontend)

WHAT IT SHOULD DO (ideal state):
- Load and display current API key status (masked) on mount
- Phase accordion uses correct long-form phase names matching backend
- File browser correctly parses nested tree response
- Phase configs load and display current saved values
- tokens_today populated from a real source

GAP: API key fields never pre-populated (GET never called); all phase saves fail (name mismatch); file browser always empty (format mismatch); phase config display always blank (array vs dict mismatch).

---

PAGE: Client Portal
ROUTE: /portal/:id  (outside auth protection — public route)
COMPONENT: pages/ClientPortal.jsx
SIDEBAR LINK: exists (Client Portal → /portal/demo — hardcoded demo ID)

CURRENT STATE:
- Public route, no JWT required
- On mount: api.getPortalStatus(id) → GET /portal/{id}/status (uses bare axios, no auth header)
- Falls back to hardcoded mock data on any API error
- Shows: stage stepper (6 stages), hardcoded specification content, approve + feedback forms
- Approve calls api.approvePortalPhase(id, true, 'Approved via portal') → POST /portal/{id}/approve
- Feedback calls api.sendPortalFeedback(id, feedback, phase) → POST /portal/{id}/feedback

KNOWN BUGS:
- BUG-CP1 ★ HARDCODED CONTENT. The "Current Specifications" section shows hardcoded bullet points about "payroll", "leave management", "PostgreSQL legacy database". This is completely unrelated to the actual project. The portal API returns real phase data (GET /portal/{id}/phase/{phase}) but this component never calls it.

- BUG-CP2: Sidebar link is hardcoded to `/portal/demo`. The `demo` project ID will always fail the real API call and fall back to mock data. There is no way to access a real project's portal from the sidebar — the link is cosmetic only.

- BUG-CP3: `currentStageIndex` bug. `stages.findIndex(...)` returns -1 when `status.current_phase` doesn't match any stage phases. The expression `stages.findIndex(...) || 0` does NOT default to 0 when findIndex returns -1, because -1 is truthy. So `currentStageIndex = -1`. In the stage stepper, `i < currentStageIndex` (i < -1) is always false, so no stages are shown as completed. The active stage `i === currentStageIndex` (i === -1) is also never true. All stages render as future/inactive. Stepper is permanently broken when the current phase isn't in the hardcoded list.

- BUG-CP4: `status.project_name` is accessed on line 95 without optional chaining: `<h1>Project Review: {status.project_name}</h1>`. Because of the mock fallback in catch, `status` is never null at render time. But the real API response shape is unknown — if `project_name` is missing, this renders "Project Review: ".

- BUG-CP5: `handleFeedback` uses `alert()` for both success and failure. This is jarring UX.

- BUG-CP6: Stage stepper's `stages` array is hardcoded and references old phase codes (`p00`, `p01`, `p04b`, etc.) that don't match the current 10-phase system. Architecture is shown as a single `p02` stage, which may not reflect the actual pipeline.

BACKEND WIRING:
- api.getPortalStatus(id)       → GET /portal/{id}/status       → real data or mock fallback
- api.approvePortalPhase(id...) → POST /portal/{id}/approve     → real endpoint (if portal router loaded)
- api.sendPortalFeedback(id...) → POST /portal/{id}/feedback    → real endpoint (if portal router loaded)
- api.getPortalPhase(id, phase) → GET /portal/{id}/phase/{phase} → NEVER CALLED

WHAT IT SHOULD DO (ideal state):
- Show the actual project name and description from the API
- Display the actual specification/deliverable for the current phase
- Show a stage stepper that correctly reflects the actual pipeline phases
- Allow the client to download artifacts
- Show phase-specific approval requests based on which gate is waiting

GAP: All content is hardcoded mock data; portal phase detail endpoint never called; stage stepper permanently broken; sidebar link is cosmetically wrong; no real phase-by-phase deliverable shown.

---

PAGE: New Project (Modal Trigger)
ROUTE: /new
COMPONENT: pages/NewProject.jsx + components/NewProjectModal.jsx
SIDEBAR LINK: exists (New Project, icon: PlusCircle)

CURRENT STATE:
- NewProject.jsx at /new: immediately triggers the modal via outlet context and redirects to /projects
- Modal contains: Project Name (optional), Requirements (required), Domain selector
- On submit: api.startPipeline({raw_input, project_name, domain, client_id}) → POST /pipeline/start
- On success: navigate to /project/{run_id}

KNOWN BUGS:
- BUG-NP1 ★ WRONG ENDPOINT. `api.startPipeline()` calls `POST /pipeline/start`. This endpoint expects the Pydantic model `PipelineStartRequest` with field `requirement` (not `raw_input`). The frontend sends `raw_input` which is not a declared field — FastAPI will raise a 422 Unprocessable Entity validation error. The pipeline NEVER starts.

- BUG-NP2 ★ WRONG FACTORY. Even if the field name were fixed, `POST /pipeline/start` invokes the OLD `orchestrator.pipeline` (not the 10-phase factory). The factory pipeline that populates `/factory/runs` is at `POST /factory/start`. Any run started via the modal will:
  1. Not appear in `/factory/runs` (different ledger path)
  2. Cause the subsequent redirect to `/project/{run_id}` to hit `GET /factory/runs/{run_id}` which returns 404
  3. ProjectView shows the error state immediately

- BUG-NP3: `client_id: 'client-001'` is hardcoded. This is minor but worth noting.

- BUG-NP4: `NewProject.jsx` at `/new` calls `ctx.openNewProject()` and immediately calls `navigate('/projects', {replace:true})` in the same `useEffect`. Both run synchronously. The modal opens AND the route changes to /projects. The modal renders fine because it lives in Layout (parent), but the UX is confusing — the user lands on /projects with a modal open over it. The /new route in the sidebar is essentially a shortcut to "open modal from /projects".

BACKEND WIRING:
- api.startPipeline() → POST /pipeline/start → 422 validation error (wrong field name) ✗
- Should target       → POST /factory/start  → correct 10-phase factory ✗

WHAT IT SHOULD DO (ideal state):
- Call POST /factory/start with {raw_input, project_name, domain, client_id}
- On success, navigate to /project/{run_id} (the returned run_id from /factory/start)
- That run should appear in /factory/runs and ProjectView should load correctly

GAP: Wrong endpoint and wrong field name — the modal is completely non-functional end-to-end. No project is ever created from the UI.

---

## SECTION 3 — NAVIGATION AUDIT

Every navigation action in the app:

| Source | Action | Target | Method | Valid? |
|--------|--------|--------|--------|--------|
| Sidebar | Dashboard link | `/` | NavLink (React Router) | ✓ |
| Sidebar | New Project link | `/new` | NavLink (React Router) | ✓ route exists, but quirky UX |
| Sidebar | Projects link | `/projects` | NavLink (React Router) | ✓ |
| Sidebar | Client Portal link | `/portal/demo` | NavLink (React Router) | ✗ hardcoded demo ID, always mock data |
| Sidebar | Settings link | `/settings` | NavLink (React Router) | ✓ |
| TopBar | New Project button | Opens modal | `onNewProject()` callback | ✓ |
| TopBar | Logout button | `/login` | `navigate('/login')` React Router | ✓ |
| Dashboard | Project name click | `/project/${run.run_id \|\| run.id}` | `navigate()` React Router | ✓ functional |
| Dashboard | Eye icon | `/project/${run.run_id \|\| run.id}` | `navigate()` React Router | ✓ functional |
| Dashboard | NEW PIPELINE button | `/new` | `navigate('/new')` React Router | ✓ |
| ProjectsList | Row click | `/project/${run.run_id \|\| run.id}` | `navigate()` React Router | ✓ functional |
| ProjectsList | Eye icon | `/project/${run.run_id \|\| run.id}` | `navigate()` React Router | ✓ functional (e.stopPropagation present) |
| ProjectsList | New Project button | Opens modal | `ctx.openNewProject()` | ✓ |
| ProjectView | Back nav | `/projects` | `navigate('/projects')` React Router | ✓ |
| ProjectView | Phase sidebar items | `#phase-{name}` (same page scroll) | `<a href="#">` anchor | ✗ IDs don't exist; PhaseDetail unreachable |
| ProjectView | VIEW PORTAL button | `/portal/${run.run_id \|\| run.id}` | `navigate()` React Router | ✓ correct route (public) |
| PhaseDetail | Back button | `/project/${id}` | `navigate()` React Router | ✓ |
| Login | Post-login redirect | `/` | `navigate('/')` React Router | ✓ |
| NewProjectModal | Post-submit | `/project/${runId}` | `navigate()` React Router | ✗ run_id comes from wrong endpoint, results in 404 |
| 401 interceptor | Auto-redirect | `/login` | `_navigate('/login')` React Router | ✓ (navigate wired in App.jsx) |
| ProtectedRoute | Unauthenticated | `/login` | React Router `<Navigate>` | ✓ |
| Unknown routes | Wildcard | `/` | React Router `<Navigate>` | ✓ |

**Summary of broken navigation:**
1. Sidebar "Client Portal" always opens demo/mock portal
2. Phase sidebar items in ProjectView never reach PhaseDetail
3. Post-modal-submit navigates to a run that doesn't exist in /factory/runs

---

## SECTION 4 — COMPONENT CRASH AUDIT

For each component that renders lists/objects from API data:

### Dashboard.jsx
| Guard | Present? | Notes |
|-------|----------|-------|
| Array.isArray() for runs | No (but initialized as []) | runs.filter() is safe |
| Optional chaining on run.cost | Yes (.cost?.toFixed(2)) | ✓ |
| Optional chaining on costs.today_usd | Yes (?.toFixed(2)) | ✓ |
| Loading state | Yes ("Loading factory status...") | ✓ |
| Error state | MISSING | fetch failure shows empty table, no error |
| Empty state for runs | Yes ("No active runs found") | ✓ |

**Missing: error state. PhaseBar receives dict instead of array — always blank but no crash.**

---

### ProjectsList.jsx
| Guard | Present? | Notes |
|-------|----------|-------|
| Array.isArray() for runs | No (initialized as []) | runs.filter() is safe |
| Optional chaining on run.project_name | Yes (?.toLowerCase()) | ✓ |
| Optional chaining on run.started_at | Yes (ternary guard) | ✓ |
| Loading state | Yes (full-page loading text) | ✓ |
| Error state | MISSING | failure → shows EmptyState, no indication |
| Empty state | Yes (EmptyState component) | ✓ |

**Missing: error state. ProgressDots logic has edge case with negative indexOf.**

---

### ProjectView.jsx ★ CRITICAL
| Guard | Present? | Notes |
|-------|----------|-------|
| Array.isArray() for events | No (run.events \|\| []) | safe |
| Optional chaining on run.phases | Yes (run.phases?.[phaseId]) | ✓ |
| Optional chaining on run.started_at | Yes | ✓ |
| Loading state | Yes (Loader2 spinner) | ✓ |
| Error state | Yes (AlertTriangle panel) | ✓ |
| Empty state for file tree | Yes ("No artifacts yet") | ✓ |
| **useState after conditional return** | **VIOLATED** | ✗ CRASH — line 299-300 |
| FileTree items.map | No explicit guard | items from tree, could be empty array safely |

**Critical: useState hook called after 3 early returns → Rules of Hooks violation → component blanks/crashes.**

---

### PhaseDetail.jsx
| Guard | Present? | Notes |
|-------|----------|-------|
| phaseData null guard | Yes (loading message) | ✓ |
| Optional chaining on phaseData.memories | Yes (?.map) | ✓ |
| Optional chaining on phaseData.files | Yes (\|\| {}) | ✓ |
| gate_result.issues guard | Indirect (empty array default) | ✓ |
| Error state | MISSING | fetch failure → setPhaseData with defaults, silently wrong |
| mem.score guard | MISSING | (mem.score * 100) could be NaN |

**No crash risk but all data is always default due to phase extraction bug (BUG-PD2).**

---

### Settings.jsx
| Guard | Present? | Notes |
|-------|----------|-------|
| Array.isArray() for runs in dropdown | No (initialized as []) | runs.map() safe |
| Optional chaining on health | Yes (health?.anthropic_available) | ✓ |
| Optional chaining on costs.avg_cost_per_run | Yes (?.toFixed(2)) | ✓ |
| runFiles dict iteration | Object.entries(runFiles) | safe for empty object |
| files.forEach format guard | MISSING | expects flat array, gets tree object — see BUG-S4 |
| Loading state | MISSING | all panels blank during initial fetch |
| Error state | MISSING | promise rejections are caught but not displayed |
| Empty state for file browser | Yes (3 states: no run, loading, no files) | ✓ |

**Missing: loading state on initial load; no error display; file format mismatch causes silent empty browser.**

---

### ClientPortal.jsx
| Guard | Present? | Notes |
|-------|----------|-------|
| loading guard | Yes (returns early) | ✓ |
| status null guard | No explicit check after loading | status always set (mock fallback) |
| status?.current_phase | Optional chaining in findIndex | ✓ |
| feedback.trim() guard | Yes (button disabled) | ✓ |
| Error state | MISSING | errors only shown via alert() |
| Empty state | No (mock fallback prevents empty) | ✓ functionally |

**No crash risk due to mock fallback, but content is always wrong.**

---

### NewProjectModal.jsx
| Guard | Present? | Notes |
|-------|----------|-------|
| requirements validation | Yes (empty check) | ✓ |
| Error state | Yes (error message block) | ✓ |
| Loading state | Yes (spinner + disabled state) | ✓ |
| err.response?.data?.detail | Optional chaining | ✓ |
| res.data?.run_id | Optional chaining | ✓ |

**No crash risk. Error is surfaced. But backend call fails with 422 (BUG-NP1).**

---

## SECTION 5 — CRITICAL BUGS PRIORITY RANKING

| Priority | Bug | Component | Impact |
|----------|-----|-----------|--------|
| P0 | BUG-PV1: useState after conditional returns | ProjectView | Crashes on every project click |
| P0 | BUG-NP1: Wrong endpoint field (`raw_input` vs `requirement`) | NewProjectModal | Modal never creates a project |
| P0 | BUG-NP2: Wrong factory endpoint (`/pipeline/start` vs `/factory/start`) | NewProjectModal | Even with field fix, wrong pipeline |
| P1 | BUG-S2: Phase name mismatch (26 short vs 10 long) | Settings | All phase config saves fail with 400 |
| P1 | BUG-S1: GET /settings/api-keys never called | Settings | API key fields always blank |
| P1 | BUG-S4: File browser parses tree as flat array | Settings | File browser always empty |
| P1 | BUG-PD2: Phase data extraction always returns defaults | PhaseDetail | Page always blank |
| P2 | BUG-PV2: Phase links use anchors instead of navigate() | ProjectView | PhaseDetail unreachable |
| P2 | BUG-D2: phases dict passed to PhaseBar instead of array | Dashboard | Phase progress bars all gray |
| P2 | BUG-CP3: findIndex returns -1, stage stepper broken | ClientPortal | Stepper always shows no progress |
| P2 | BUG-CP1: Hardcoded payroll content in portal | ClientPortal | Wrong content always shown |
| P3 | BUG-D1, BUG-S3: `tokens_today` missing from /system/costs | Dashboard, Settings | Token count always "—" |
| P3 | BUG-PD1: PhaseDetail route unreachable from UI | PhaseDetail | Entire page is dead code |
| P3 | BUG-CP2: Sidebar portal link hardcoded to /portal/demo | Sidebar | Portal always shows demo/mock |
| P3 | BUG-S5: Phase configs stored as array but accessed as dict | Settings | Config values always blank |

---

## SECTION 6 — COMPONENT INVENTORY (additional files found)

Components found via glob that were not in the original audit list:

- `components/ProviderBadge.jsx` — imported in Sidebar but not in the original file list. Renders an LLM provider status badge in the sidebar footer.
- `components/CostPill.jsx` — exists but imported nowhere in the audited files. Dead code or intended for TopBar replacement.

---

## SUMMARY

The frontend has **solid architectural bones**: React Router setup is correct, auth/401 interceptor works, ErrorBoundary wraps all routes, api.js is clean with a single axios client. The design system (Tailwind classes, component structure) is coherent.

**However, the app is currently non-functional end-to-end:**
1. **You cannot create a project** — the modal calls the wrong endpoint with the wrong field
2. **Project View crashes** on every click due to a hooks violation
3. **Settings saves nothing** — phase names don't match backend validation
4. **Portal always shows hardcoded mock content**
5. **PhaseDetail is unreachable** and blank even when visited directly

The gap between "visually complete" and "functionally working" is roughly 8 targeted bug fixes, mostly in the data-wiring layer rather than the component structure.
