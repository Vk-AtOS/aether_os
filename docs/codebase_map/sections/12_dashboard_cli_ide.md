# 12 — User-facing surfaces: Dashboard (React/Vite), CLI, VS Code extension, public landing

Scope: `dashboard/` (excluding node_modules/dist), `cli/`, `vscode-extension/`, `public/`. Git HEAD 052a101. Read-only mapping.
Paths below are relative to `dashboard/src/` unless they start with another top-level folder.

## 1. Summary

- **Dashboard** is a React 19 + Vite 8 + Tailwind 4 single-page app, mounted at `/dashboard` (`main.jsx:10` `basename="/dashboard"`, `vite.config.js:11`). It has 62 source files and about 21.8K lines of code.
  - The HTTP client is one axios instance with `baseURL "/api"` (`api.js:4`). Nginx strips `/api` before forwarding to FastAPI; in dev, the Vite proxy does the same and targets `localhost:8080` (`vite.config.js:14-18`).
  - JWT and refresh token live in `localStorage` (`aether_token`, `aether_refresh_token`). On a 401, a single shared refresh call (`/auth/refresh`) runs; if it fails, the user is logged out (`api.js:28-68`).
- **Routing** (`App.jsx`): 8 public routes, about 50 protected routes nested under `Layout`, and 13 legacy redirects.
  - **Role gating is client-side only.** `useRole` decodes the JWT `role` claim without verifying it (`hooks/useRole.js:4-26`).
  - `AdminRoute` (owner|admin) wraps exactly 4 routes: `/admin/users`, `/admin/billing`, `/admin/intelligence`, `/audit` (`App.jsx:116-133`).
  - Every other page, including Guardian DB restore, Compliance, Agents, Kill-switch visibility and Marketplace publish, relies on the backend to enforce permissions.
- **Global shell**: `Layout` wraps `SettingsProvider` → `RunsProvider` → Sidebar + TopBar + `<Outlet>` + `NewProjectModal` (`components/Layout.jsx:83-89`).
  - RunsContext polls `/factory/runs`, `/system/costs` and `/system/health` every 5s while a run is active and every 10s otherwise (`contexts/RunsContext.jsx:6-78`).
  - TopBar polls `/system/health`, `/system/status` and `/system/costs` every 30s. NotificationBell polls `/notifications` every 30s.
- **Endpoint coverage**: about 160 distinct backend calls. Every path the dashboard calls matches a decorator in `gateway/` (checked with a suffix-match script plus manual spot-checks).
  - **The real failures are contract and auth mismatches, not missing routes.** The worst one: the SSE stream needs an `sse_token` (`gateway/routers/factory_run_streaming_router.py:45-70`). Only ProjectView does the token exchange. RunDetail's live log, `aether logs` in the CLI, and the VS Code "Stream Logs" command all send a JWT instead and get **401**.
- **CLI** (`cli/aetheros.py`, Typer, 498 LOC) has 12 commands. **VS Code extension** has 9 commands, a runs tree view and a webview status panel.
  - Both hardcode a 12-phase list (p01…p11). The dashboard's ProjectView has 21 phases, ProjectsList 23, and the landing page claims 29.
- **Public landing page** (`public/index.html`, 1174 LOC, three.js hero): static marketing copy ("29 phases", "~8 min", "39K+ files", ₹ pricing). It links to `/dashboard/signin` and `/dashboard/signup`.
- **Overall**: the dashboard is mostly REAL — it wires to real endpoints with no `Math.random` and no mock fallbacks. Hollow parts:
  - static framework and marketing panels: Compliance frameworks, CostDashboard levers, the Pricing demo, Billing USD prices;
  - three thin "start pipeline" entry points: NewProjectModal, PromptInput, Edit & Restart;
  - a handful of dead or unrouted files.

## 2. Coverage table

Status tags: **REAL** = wired to the backend and works · **PARTIAL** = wired, with hollow parts or bugs · **HOLLOW** = mostly static · **DEAD** = not reachable · **INFRA** = plumbing.

### Core / infrastructure
| File | LOC | Purpose | Status |
|---|---|---|---|
| main.jsx | 16 | Root: BrowserRouter basename `/dashboard`, ToastProvider | INFRA |
| App.jsx | 155 | Route table; ProtectedRoute (token exists) / AdminRoute (role owner\|admin) | INFRA |
| api.js | 248 | axios client, refresh interceptor, about 75 helper methods (20 unused — see §7) | INFRA |
| contexts/RunsContext.jsx | 112 | Adaptive polling of runs, costs and health; `latestRunId` for the portal link | INFRA |
| contexts/SettingsContext.jsx | 70 | Loads `/settings/llm-config`, `/account/usage`, `/settings/preferences`; derives activeProvider, orgName, plan | INFRA |
| contexts/ToastContext.jsx | 49 | Toast UI | INFRA |
| hooks/useRole.js | 27 | Decodes the JWT payload into role, isAdmin, canWrite (no signature check) | INFRA |
| hooks/useProjectView.js | 350 | All ProjectView state; SSE with token exchange and exponential-backoff reconnect | REAL |
| index.css | 74 | Tailwind 4 `@theme` colour tokens and `.panel` | INFRA |
| index.html | 14 | CSP meta tag (`unsafe-eval` and `unsafe-inline` allowed, for Monaco) | INFRA |
| package.json / vite.config.js / tailwind.config.js / eslint.config.js | 42/25/5/29 | Dependencies: react 19, react-router 7, axios, d3, monaco, framer-motion, highlight.js, lucide | INFRA |
| README.md | 16 | Unedited Vite template text | DEAD-doc |

### Pages (`pages/`)
| File | LOC | Purpose | Status |
|---|---|---|---|
| Login.jsx | 280 | Password, MFA, Google/GitHub OAuth and SAML SSO login | REAL |
| Signup.jsx | 191 | Register with ToS and DPA consent | REAL |
| ForgotPassword.jsx | 106 | Request a reset email (always reports success, by design) | REAL (reset *confirm* page missing) |
| OAuthCallback.jsx | 58 | Reads tokens from the query string → localStorage | REAL |
| Pricing.jsx | 498 | Public marketing page plus Razorpay upgrade | PARTIAL |
| Legal.jsx | 107 | ToS / Privacy / DPA viewer (`fetch /api/legal/*`) | REAL |
| ClientPortal.jsx | 249 | External client approval portal | REAL (cosmetic claims) |
| Dashboard.jsx | 497 | Home: stats, trial banner, onboarding, kill switch, guardian widget, quality trend | REAL (stat bugs) |
| NewProjectWizard.jsx | 487 | 4-step wizard: template → questionnaire → stack → review/estimate → start | REAL |
| NewProject.jsx | 19 | Opens modal and redirects | **DEAD** (lazy-imported `App.jsx:13`, no Route) |
| ProjectDesigner.jsx | 520 | 6-tab full spec designer (stack, design system, compliance) → start | PARTIAL |
| ProjectsList.jsx | 429 | Run table with pause/resume/cancel/rerun | REAL |
| ProjectView.jsx | 429 | Live run cockpit: 10 tabs, SSE, deploy, GitHub, VS Code, branch | REAL |
| PhaseDetail.jsx | 403 | Per-phase output / gate / memory / artifacts | REAL |
| RunDetail.jsx | 509 | Alternative run summary page | PARTIAL (broken SSE; runtime crash on failed runs) |
| PromptInput.jsx | 192 | Project-scoped chat; can start a bare pipeline | PARTIAL |
| FrontendBuilder.jsx | 308 | Frontend spec editor per run | PARTIAL |
| BackendBuilder.jsx | 386 | Backend spec editor (entities, endpoints) plus validate | PARTIAL |
| LogViewer.jsx | 334 | Phase-grouped log view — a component rendered inside ProjectView's "Logs" tab | REAL (not routed, by design) |
| Deployments.jsx | 181 | List and undeploy deployed apps | REAL |
| SearchPage.jsx | 166 | Global run search | REAL |
| Workspaces.jsx | 359 | Workspace create/read/update/delete | PARTIAL (no runs linked to workspaces) |
| Marketplace.jsx | 309 | Skill profiles: browse, install, publish | REAL |
| ConnectorHub.jsx | 339 | `/v2/plugins` connectors: install, configure, test | REAL |
| PluginManager.jsx | 281 | `/v2/plugins/skills` code-generation skills | REAL |
| MemoryInspector.jsx | 481 | D3 memory graph, recall search, preferences, cache stats | REAL (errors hidden) |
| CostDashboard.jsx | 239 | LLM cost metrics | PARTIAL |
| Learning.jsx | 298 | Golden builds, patterns, clarification Q&A | REAL (errors hidden) |
| WebhookSettings.jsx | 331 | Outbound webhook create/read/update/delete and test | REAL |
| Settings.jsx | 548 | One long settings page (keys, LLM, Bedrock, council, LangSmith, phases, SSO, SCIM, org, region, audit export) | REAL |
| Profile.jsx | 448 | Account, MFA, password, GDPR export and erase | REAL |
| Compliance.jsx | 433 | Org compliance report, run artifact ZIPs, audit tail, framework reference | PARTIAL |
| Guardian.jsx | 546 | Threat events, DB snapshots and restore, integrity baseline | REAL |
| IntelligenceHub.jsx | 255 | AI self-assessment and analysis tools | PARTIAL |
| Agents.jsx | 276 | List and manually run backend agents | REAL |
| SystemHealth.tsx | 317 | Services, resources, SLA, observability | REAL |
| AdminUsers.jsx | 521 | Org user admin, invite, SCIM bulk import, prune artifacts | REAL |
| AuditLogs.jsx | 322 | Audit trail viewer, export, purge | PARTIAL (filters ignored by backend) |
| Billing.jsx | 467 | Plan, usage, Razorpay/Stripe, invoices | PARTIAL |
| GlobalPatternsTuning.jsx | 386 | Admin create/read/update/delete of global learned patterns | REAL |

### Components (`components/`)
| File | LOC | Purpose | Used by | Status |
|---|---|---|---|---|
| Layout.jsx | 91 | Shell | App | INFRA |
| Sidebar.jsx | 303 | Navigation; decodes role itself (`:15-41`) | Layout | INFRA |
| TopBar.jsx | 323 | ⌘K search, system status pill, OrgSwitcher (`/auth/my-orgs`, `/auth/switch-org`), provider badge, cost, NotificationBell, logout | Layout | REAL |
| NotificationBell.jsx | 148 | `/notifications`, read, read-all | TopBar | REAL |
| NewProjectModal.jsx | 289 | Quick-start modal | Layout (opened via ProjectsList "New Project") | PARTIAL |
| OnboardingBanner.jsx | 95 | 2-step checklist (API key, first run) | Dashboard | REAL |
| RerunDropdown.jsx | 296 | Continue / Edit & Restart / Re-run from phase (12 phases) / Full restart | RunControlPanel, ProjectsList, RunDetail | REAL |
| ConfirmDialog.jsx | 75 | Accessible confirm modal | ProjectsList, Webhooks, Workspaces | INFRA |
| ErrorBoundary.jsx | 50 | Per-route boundary with retry | App | INFRA |
| CostPill / EmptyState / PageLoader / Skeleton / PhaseBadge | 13/23/33/38/36 | UI atoms | various | INFRA |
| PhaseBar.jsx | 49 | 12-block progress bar (comment says it matches `PHASE_SEQUENCE`, but it is stale) | Dashboard | PARTIAL |
| ProviderBadge.jsx | 47 | Active LLM pill | Sidebar | REAL |
| StorageWidget.jsx | 33 | `/account/storage` bar | Settings | REAL |
| TraceTab.jsx | 123 | LLM traces per phase: prompt and raw response | ProjectView | REAL |
| admin/UserPanels.jsx | 99 | Invite and bulk-import panels | AdminUsers | REAL |
| intelligence/IntelligenceTools.jsx | 394 | Conflict resolver, maintenance scan, improvement loop | IntelligenceHub | REAL (thin) |
| new-project/WizardShared.jsx, WizardStep2.jsx | 105/220 | Wizard templates, default models, questionnaire | NewProjectWizard | REAL |
| project-designer/DesignerData.jsx, DesignerComponents.jsx, DesignerTabs.jsx | 405/188/493 | Designer catalogues (12 templates, 8 themes, 50 countries), RunOutput poller, tab bodies | ProjectDesigner | PARTIAL |
| project/projectConstants.js | 161 | 21-phase `PHASES`, labels, `formatEvent` (SSE → ANSI text) | 5 importers | INFRA |
| project/AppPreviewPanel.jsx | 101 | iframe of `/app-preview/` or `live_url`, device toggle | ProjectView | REAL |
| project/ClarifyingQuestionsPanel.jsx | 98 | p02b clarifying Q&A → resume | ProjectView | PARTIAL (synthesizes generic placeholder questions `:17-21`) |
| project/CouncilPanel.jsx | 175 | POST council-review; multi-model reviews | ProjectView | REAL |
| project/DecisionsPanel.jsx | 101 | List and approve/reject human-in-the-loop decisions | ProjectView | REAL |
| project/EnvVarsPanel.jsx | 79 | Generated app `.env` editor | ProjectView | REAL |
| project/FeedbackPanel.jsx | 123 | 1–5 star rating and tags → `/feedback` (feeds golden builds) | ProjectView | REAL |
| project/FileExplorer.jsx | 170 | File tree plus Monaco viewer/editor (PATCH file-content) | ProjectView | REAL |
| project/LiveFeed.jsx | 73 | Old live terminal | **none** | **DEAD** (replaced by RunEventLog.LiveFeedTab) |
| project/ProjectLivePreviewPanel.jsx | 189 | Polls `/artifacts` every 5s during the frontend phases | ProjectView | REAL |
| project/QualityPanel.jsx | 56 | Quality score breakdown | ProjectView | REAL |
| project/RunAppPanel.jsx | 129 | Start/stop the generated app; shows demo credentials | ProjectView | REAL |
| project/RunControlPanel.jsx | 127 | Summary plus pause/resume/cancel/rerun (gated on `isViewer`) | ProjectView | REAL |
| project/RunEventLog.jsx | 129 | `LiveFeedTab` (ANSI terminal) and `AgentEventsLog` | ProjectView | REAL |
| project/SpecReviewModal.jsx | 69 | Spec approval gate; "remember" turns on autonomous_mode | ProjectView | REAL |
| run-detail/RunDetailComponents.jsx | 143 | PHASE_LABELS (21), StatusBadge, PhaseRow, `LiveEventLog` (broken SSE) | RunDetail | PARTIAL |
| settings/AccountSettings.jsx | 240 | API keys, plan limits, LLM status, stats, version | Settings | PARTIAL (hardcoded `'2.45'` avg cost `:~210`; "gemini-1.5-pro" label `:166`) |
| settings/LLMSettings.jsx | 458 | OpenRouter heavy/light/fallback chain, Bedrock, Council, LangSmith | Settings | REAL |
| settings/OrgSettings.jsx | 197 | Audit CSV export, autonomous mode, delete org, data region | Settings | REAL |
| settings/PhaseSettings.jsx | 217 | Per-phase enabled/priority (21 phases), run file browser | Settings | REAL |
| settings/SecuritySettings.jsx | 190 | SAML SSO config (PUT/DELETE `/settings/sso`), SCIM token rotation | Settings | REAL |
| ui/GlassCard.jsx, ui/GradientButton.jsx, ui/SkeletonLoader.jsx | 13/23/13 | Design-system atoms | **none** | **DEAD** |
| ui/StatusBadge.jsx | 19 | Run status pill | ProjectsList | INFRA |

### CLI / VS Code / public
| File | LOC | Purpose | Status |
|---|---|---|---|
| cli/aetheros.py | 498 | Typer CLI `aether` (12 commands) | PARTIAL (`logs` and `download` broken) |
| cli/setup.py | 25 | `aetheros-cli` 2.0.0, entry point `aether=cli.aetheros:main` | PARTIAL (`find_packages()` run from inside `cli/` won't find the `cli` package) |
| cli/__init__.py | 0 | — | INFRA |
| vscode-extension/package.json | 96 | 9 commands, activity bar view container, 3 settings | PARTIAL (`media/icon.png` is referenced but missing, so `vsce package` fails) |
| vscode-extension/src/extension.ts | 206 | Command registrations, status bar, auto-refresh | REAL |
| vscode-extension/src/client.ts | 99 | fetch wrapper: login, runs, start, cancel, open-in-vscode, health, stream | PARTIAL (stream returns 401) |
| vscode-extension/src/runsProvider.ts | 65 | Tree of runs ("x/12 phases") | REAL |
| vscode-extension/src/statusPanel.ts | 108 | Webview run status (no HTML escaping, scripts disabled) | REAL |
| vscode-extension/tsconfig.json | 14 | — | INFRA |
| public/index.html | 1174 | Marketing landing page | HOLLOW (static by nature) |
| public/js/landing.js | 139 | three.js icosahedron, reveal-on-scroll, tilt | REAL |
| public/js/vendor/three.min.js | — | three.js | used |
| public/js/vendor/gsap.min.js, ScrollTrigger.min.js | — | Vendored, never loaded (only three.js has a `<script>` tag, `index.html:1171`) | **DEAD** |

## 3. Sitemap / route table

Base URL `/dashboard`. "Gate": P = public · A = authenticated (token present) · ADM = AdminRoute (owner|admin from the JWT). Sidebar groups: **Main** · **Platform** (collapsible) · **Tools** (collapsible) · **Admin** (only if isAdmin) · footer (Client Portal, Profile, Sign out).

| Path | Page | Gate | Nav | Endpoints called (all under `/api`) | User can… |
|---|---|---|---|---|---|
| `/login` (`/signin` → here) | Login | P | — | POST `/auth/login`, POST `/auth/mfa/confirm`, GET `/auth/saml/metadata` (probe), redirects to `/auth/oauth/{google,github}` and `/auth/saml/login?org=` | Password login, TOTP MFA, OAuth, SAML SSO |
| `/signup` | Signup | P | — | POST `/auth/register` | Create org and owner (ToS and DPA required, password ≥10 chars) |
| `/forgot-password` | ForgotPassword | P | — | POST `/auth/password-reset-request` | Request a reset link |
| `/pricing` | Pricing | P | Dashboard trial banner | GET `/billing/plans`, GET `/account/usage`, POST `/billing/create-order`, POST `/billing/verify-payment` (Razorpay) | View plans, upgrade |
| `/legal?doc=` | Legal | P | Login footer | GET `/legal/{tos,privacy,dpa}` | Read legal documents |
| `/auth/callback` | OAuthCallback | P | — | none (reads `?token&refresh_token`) | Finish OAuth |
| `/portal/:id` | ClientPortal | P (sends token if present) | Sidebar "Client Portal" (latest run), RunDetail, ProjectView | GET `/portal/{id}/status`, POST `/portal/{id}/approve`, POST `/portal/{id}/feedback` | External client sees stage, approves, sends feedback |
| `/` | Dashboard | A | Main | `/factory/runs`, `/system/costs`, `/system/health` (context), GET `/factory/analytics/quality-trend`, `/guardian/status`, `/guardian/stats`, `/account/usage`, `/settings/api-keys`, POST `/admin/kill-all` | Overview; admin kill switch (`:288`); non-admins see only their own runs (client-side filter `:240`) |
| `/new` | NewProjectWizard | A (hidden from viewers in Sidebar `:63`) | Main "New Project", TopBar button | GET `/templates`, `/settings/llm-config`, `/settings/active-provider`; POST `/factory/estimate`, `/factory/upload-requirement`, `/factory/fetch-repo`, `/factory/import-schema`, `/factory/start` | Guided project creation |
| `/designer`, `/designer/:id` (`/new-project` → here) | ProjectDesigner | A | from Wizard "Configure in Designer" | `/settings/llm-config`, POST `/factory/estimate`, `/factory/upload-requirement`, `/factory/fetch-repo`, `/factory/import-schema`, `/factory/start`; polls GET `/factory/runs/{id}` every 3s | Full spec: stack, design system, compliance country and flags |
| `/projects` | ProjectsList | A | Main | `/factory/runs` (context), POST pause/resume/cancel/rerun, POST `/factory/start` | List, filter, control, rerun |
| `/project/:id` | ProjectView | A | links from lists | see §4.3 (about 30 endpoints) | Live cockpit |
| `/project/:id/phase/:name` | PhaseDetail | A | ProjectView phase click | GET `/factory/runs/{id}`, `/files`, `/file-content` | Inspect a phase |
| `/runs/:runId`, `/dashboard/runs/:runId` | RunDetail | A | not in nav | GET `/factory/runs/{id}`, `/factory/runs/{id}/events`, EventSource `/factory/runs/{id}/stream?token=JWT` (**401**), pause/resume/cancel/rerun/deploy/undeploy/download | Run summary |
| `/workspaces` | Workspaces | A | Main | GET/POST `/workspaces`, PUT/DELETE `/workspaces/{id}` | Workspace create/read/update/delete |
| `/search?q=` | SearchPage | A | Main, TopBar ⌘K | GET `/factory/search?q&limit=30` | Search runs |
| `/deployments` | Deployments | A | Main | GET `/factory/deployments`, DELETE `/factory/runs/{id}/deploy` | List live apps, undeploy |
| `/marketplace` | Marketplace | A | Main | GET `/marketplace/profiles`, `/marketplace/installed`; POST `/marketplace/install/{id}`, `/marketplace/publish`; DELETE `/marketplace/profiles/{id}` | Install, uninstall, publish (with price) |
| `/settings`, `/settings/sso` | Settings | A (no in-page gate) | Main | see §4.11 | All org configuration |
| `/intelligence` | IntelligenceHub | A | Platform | GET `/intelligence/global-insights`, `/intelligence/quality-benchmark`; POST `/intelligence/{arch-governor/review, tradeoff-engine/analyze, truth-engine/validate, conflict-resolver/detect, conflict-resolver/resolve, maintenance-engine/scan, improvement-loop/cycle?run_id=}` | Run AI analyses |
| `/health` | SystemHealth | A | Platform | GET `/system/health`, `/system/metrics` (falls back to `/health/metrics`), `/health/sla`, `/health/observability` (15s poll) | SRE view |
| `/guardian` | Guardian | A (**no gate on restore**) | Platform | GET `/guardian/{status,stats,events,snapshots}`; POST `/guardian/events/{id}/resolve`, `/guardian/snapshots`, `/guardian/scan`, `/guardian/restore/{id}`, `/guardian/update-baseline` | Threats, DB snapshot and restore, baseline |
| `/agents` | Agents | A (restricted agents need role owner/admin/enterprise `:20,:127`) | Platform | GET `/agents`, `/factory/runs`; POST `/agents/{name}/run` | Run an agent manually |
| `/compliance` | Compliance | A (but `/audit/logs` returns 403 for non-admins, which breaks the whole page) | Platform | GET `/factory/runs`, `/compliance/org-report`, `/audit/logs`, `/compliance/artifacts/{runId}` (blob) | Compliance posture, evidence ZIP |
| `/connectors` (+ 2 redirects) | ConnectorHub | A | Tools | GET `/v2/plugins/catalog?type=connector`, `/v2/plugins/installed`; POST `/v2/plugins/install`, `/v2/plugins/installed/{id}/test`; PUT `/v2/plugins/installed/{id}/config`; DELETE `/v2/plugins/installed/{id}` | Third-party connectors |
| `/skills` | PluginManager | A | Tools | GET `/v2/plugins/skills`, POST `/v2/plugins/skills/generate` | Generate code from a skill |
| `/memory` | MemoryInspector | A | Tools | GET `/memory/graph?limit&offset`, `/settings/preferences`, `/system/costs`; POST `/memory/search` | Explore cross-run memory |
| `/costs` | CostDashboard | A | Tools | GET `/system/costs` | LLM spend |
| `/settings/webhooks` (`/webhooks` → here) | WebhookSettings | A | Tools | GET/POST `/webhooks`, PUT/DELETE `/webhooks/{id}`, POST `/webhooks/{id}/test` | Outbound webhooks (7 events) |
| `/learning` | Learning | A | Tools | GET `/learning/{stats,golden-builds,context,clarifications}`, POST `/learning/clarifications/{id}/answer` | Self-improvement data |
| `/frontend-builder`, `/project/:id/frontend-builder` | FrontendBuilder | A | Tools | GET/POST `/factory/runs/{id}/frontend-spec` | Edit the frontend spec (needs a run id to save) |
| `/backend-builder`, `/project/:id/backend-builder` | BackendBuilder | A | Tools | GET/POST `/factory/runs/{id}/backend-spec`, POST `/validate-spec` | Edit the backend spec |
| `/prompt`, `/project/:id/prompt` | PromptInput | A | Tools | GET `/factory/runs/{id}`, POST `/factory/runs/{id}/chat`, POST `/factory/start` | Chat with a project |
| `/profile` | Profile | A | footer | GET `/account/usage`, `/settings/api-keys`, `/auth/mfa/status`, `/account/data-export`; POST `/auth/change-password`, `/auth/mfa/{setup,verify-setup,disable}`; DELETE `/account` | MFA, password, GDPR |
| `/admin/users` | AdminUsers | **ADM** | Admin | GET `/admin/users`; POST `/admin/users/{id}/{role,reactivate,reset-password,deactivate}`, `/admin/users/invite`, `/scim/v2/Users` (with the user JWT), `/admin/prune-artifacts` | User lifecycle |
| `/audit` | AuditLogs | **ADM** | Admin | GET `/audit/logs`, `/audit/logs/export?format=csv`; DELETE `/audit/logs/purge?days_to_keep=` | Audit trail |
| `/admin/billing` (`/billing` → here) | Billing | **ADM** | Admin | GET `/account/usage`, `/billing/plans`, `/billing/invoices`, `/billing/stripe/portal`; POST `/billing/create-order`, `/billing/verify-payment`, `/billing/stripe/checkout`, `/billing/cancel` | Subscription |
| `/admin/intelligence` | GlobalPatternsTuning | **ADM** | Admin | GET `/intelligence/global-insights`; POST/PUT/DELETE `/intelligence/global-patterns[/{id}]` | Tune global patterns |
| `*` | NotFound | — | — | — | — |

Legacy redirects: `/dashboard/connector-hub`, `/dashboard/tools/{connectors,skills,memory,costs,webhooks,frontend-builder,backend-builder,prompt,learning}`, `/billing`, `/webhooks`, `/new-project`, `/signin`.
**Unrouted**: `NewProject.jsx` (dead). `LogViewer.jsx` is a component used in ProjectView, not a page.
**Missing route**: `/reset-password`. The backend email builds `{frontend_url}/reset-password?token=` (`gateway/routers/auth_password_router.py:144`), and no UI calls `/auth/password-reset-confirm`, so the password-reset flow can't be finished from the UI.

Global chrome on every protected page:
- TopBar: active-run pill, ⌘K search overlay → `/search`, system status pill (`/system/status`, falling back to health), OrgSwitcher, provider badge, today's cost, New → `/new`, NotificationBell, logout.
- Sidebar: footer org name, ProviderBadge, Profile, Sign out (POST `/auth/logout`).

## 4. Key UX flows

### 4.1 Signup / login / MFA / SSO / session
1. **Signup** (`Signup.jsx:49-75`)
   - Client-side checks: passwords match, length ≥10, both ToS and DPA checkboxes ticked.
   - POST `/auth/register {email,password,org_name,terms_accepted,dpa_accepted}` → stores tokens → `/`.
   - Copy says "Start Free Trial". The ToS/DPA links open `/api/legal/{tos,dpa}` raw.
2. **Login** (`Login.jsx`)
   - On mount: if a token exists, redirect to `/` (`:35`). A `?error=` param is shown. GET `/api/auth/saml/metadata` is probed; if it returns 2xx, the SSO button appears (`:45`).
   - POST `/auth/login` (`:61`). If the response has `mfa_required`, the 6-digit form is shown and POST `/auth/mfa/confirm {mfa_token, code}` follows (`:87`). Otherwise `api.setToken` → `/`.
   - OAuth: `window.location=/api/auth/oauth/{google|github}` (`:203,:210`). The backend redirects to `/dashboard/auth/callback?token=&refresh_token=` (tokens in the URL, `OAuthCallback.jsx:12-27`).
   - SAML: `/api/auth/saml/login?org=slug` (`:234`).
   - Bug: `/auth/mfa/confirm` is not excluded from the 401 interceptor (`api.js:35-36`), so a wrong code triggers the logout/redirect logic.
3. **MFA enrolment** (`Profile.jsx:135-170`)
   - POST `/auth/mfa/setup` returns `{secret, provisioning_uri}` (shown as an otpauth link and the raw secret; no QR image). POST `/auth/mfa/verify-setup {code}`. POST `/auth/mfa/disable {code}`. Status comes from GET `/auth/mfa/status`.
   - No session management: no list of active sessions, no revoke.
4. **Session**
   - Tokens are in localStorage. The refresh interceptor deduplicates concurrent refreshes (`api.js:44-48`); `action:'re_authenticate'` forces logout.
   - Org switching: POST `/auth/switch-org` → new tokens → full page reload (`TopBar.jsx:38-50`).
5. **Password reset**: ForgotPassword works (always shows success). The reset landing page is missing (§3).

### 4.2 New-project entry points (five ways to call `POST /factory/start`)
| Entry | Payload richness | Where |
|---|---|---|
| **Wizard** `/new` | `{raw_input (compiled from 7 questions + repo context ≤3000 chars), project_name, domain, model_preference, priority, client_id, tech_preferences{backend,frontend,database}, codebase_mode new\|existing, designer_spec{frontend,backend,design.ui_theme}, existing_schema?}` | `NewProjectWizard.jsx:239-251` |
| **Designer** `/designer` | Everything above, plus `designer_spec.{frontend(state, forms, fetch), backend(orm, auth, api_style), infra(deploy, cache, queue, storage, email), features(multi_tenancy, audit_log, rate_limiting, webhooks_out, realtime, payments, i18n), design(4 hex colours, fonts, radius, layout, density, theme, motion…)}`, `production_country`, `compliance_flags{data_sensitivity, personal/biometric/children data, residency, deployment_type}` | `ProjectDesigner.jsx:203-223` |
| **NewProjectModal** (ProjectsList "New Project") | `{raw_input, project_name, domain (8 keys including industrial, saas_multitenant, logistics), client_id}` — the "recommended stack and compliance" shown is display-only | `NewProjectModal.jsx:105` |
| **PromptInput** with no run id | `{raw_input}` only; ignores the returned run_id and goes to `/projects` after 2s | `PromptInput.jsx:70-75` |
| **Edit & Restart** (ProjectsList, ProjectView) | `{raw_input, project_name, domain, client_id}` — drops the original designer_spec, tech preferences and compliance | `ProjectsList.jsx:140`, `useProjectView.js:245-250` |

- Wizard steps: (1) template plus new/existing mode → (2) questionnaire, doc upload (`/factory/upload-requirement`), repo fetch (`/factory/fetch-repo`, GitHub/GitLab/SSH), schema import (`/factory/import-schema`) → (3) stack, model, priority → (4) review plus cost estimate (`/factory/estimate`) → Start, or hand off to the Designer through query params. The Designer ignores the `backend`, `frontend` and `db` params, and `req` is double-encoded.
- Designer tabs: Understand · Tech Stack · Design · Compliance (50 countries) · Preview (complexity, estimate, model, priority, Save Spec JSON) · Output (RunOutput polls every 3s).
  - **Bug**: the tab guard blocks index 4 (Preview) instead of 5 (Output) when no run exists, so model and priority can't be chosen before launch (`ProjectDesigner.jsx:486-491`).
  - **Bug**: RunOutput treats `run.phases` as an array, but it is a dict (`DesignerComponents.jsx:145-164`).
  - `font_scale` and `card_style` are collected but never sent.

### 4.3 Live run view — ProjectView `/project/:id` (`pages/ProjectView.jsx` + `hooks/useProjectView.js`)
- **Polling**: GET `/factory/runs/{id}` every 4s while running or paused (`useProjectView.js:92-99`). GET `/files` on load and on completion.
- **SSE**: POST `/factory/runs/{id}/sse-token` (30-second, single-use token) → `EventSource /factory/runs/{id}/stream?sse_token=` (`:142-152`). Reconnects with exponential backoff up to 30s (`:135-140`).
  - `llm_chunk` text is buffered into lines. `formatEvent` renders `phase_start`, `phase_complete`, `file_written` and `pipeline_complete` as ANSI-coloured lines (`projectConstants.js:130-160`).
  - `spec_review_ready` → GET `/spec` → SpecReviewModal. `app_started` → appRunning. `pipeline_complete` → refetch.
  - Feed capped at 300 lines.
- **Left rail**: 21 phases with status, duration, a p07 test badge, a branch button on hover (POST `/branch {branch_phase, extra_input}`), progress bar, ETA.
- **Header actions**:
  - priority cycle (POST `/priority`), security grade A–F (client heuristic on p06 finding count `:110-116`);
  - Launch App or Deploy to localhost (POST/DELETE `/deploy`), View Portal, ZIP (GET `/download` blob);
  - GitHub push modal (POST `/push-github {github_token, repo_name}`), VS Code (POST `/open-in-vscode`), Add Feature (branch run).
- **Panels**:
  - SpecReviewModal: POST `/approve-spec {action}`; "remember" also POSTs `/account/settings {autonomous_mode:true}`.
  - RunControlPanel: pause, resume, cancel, RerunDropdown.
  - Once complete: QualityPanel (GET `/quality`), compliance card (GET `/compliance`), FeedbackPanel (POST `/feedback {rating,tags,comment}`).
  - ClarifyingQuestionsPanel → POST `/resume {clarifying_answers}`.
  - ProjectLivePreviewPanel (polls `/artifacts` every 5s); AgentEventsLog.
- **Tabs** (`ProjectView.jsx:352-362`):
  - Live (terminal) · Logs (LogViewer, grouped by `[phase]` prefix)
  - Artifacts (FileExplorer + Monaco; edit → PATCH `/file-content`, hidden for viewers)
  - Preview (static `index.html` srcDoc or live iframe) · App Preview (only when `live_url` exists)
  - Env Vars (GET/PATCH `/envvars`) · Run App (POST/DELETE `/run-app`, `/run-app/status`, `/preview-credentials` → iframe `/app-preview/`)
  - Trace (GET `/traces`, `/traces/{id}`) · Council (POST `/council-review`) · Decisions (GET `/decisions`, POST `/decisions/{id}/decide`)
- **Role gating** is `isViewer` only: priority, the RunControlPanel buttons, and file editing. Deploy, GitHub push, branch, spec approval and clarifying answers are open to viewers in the UI.

### 4.4 Run detail — RunDetail `/runs/:runId` (secondary page, no nav entry)
- Single page, no tabs.
  - Header actions: refresh, cancel, pause/resume, RerunDropdown, deploy/undeploy, portal, ZIP, Live App.
  - Stats tiles: quality, LLM cost, council verdict, phase count.
  - Live SSE panel; failure plus suggestions panel; needs_review council panel; 21-phase table; last 50 events (GET `/factory/runs/{id}/events`); 10s poll.
- **Bugs**:
  - `LiveEventLog` opens `EventSource('/api/factory/runs/{id}/stream?token=<JWT>')` (`RunDetailComponents.jsx:104-106`), but the backend requires `sse_token`, so it gets a 401.
  - `XCircle` is used at `RunDetail.jsx:420` but never imported (`:4-20`), causing a ReferenceError crash whenever a failed run has an error message.
  - Edit & Restart navigates to `/new-project` with `state.prefill`. That route is a `<Navigate>` to `/designer`, so the state is lost.

### 4.5 Admin console (owner|admin)
- **Users** (`AdminUsers.jsx`): paged search with role and status filters, inline role change (the role list includes `owner`), deactivate/reactivate, reset password (temp password shown in an alert and copied to the clipboard), bulk deactivate, invite (temp password shown if email fails), bulk CSV import through POST `/scim/v2/Users` using the user JWT (backend accepts this as a "dev/back-compat" fallback, `gateway/routers/scim_router.py:47`), artifact pruning with a dry run first (`/admin/prune-artifacts {ttl_days:30, dry_run}`).
- **Audit Logs**: filters for action, from/to and user, CSV export, purge (≥30 days, acknowledgement checkbox). The backend only honours `page, limit, action, from_ts` (`gateway/routers/compliance_router.py:55-60`), so the date and user filters do nothing.
- **Billing**: details in §4.8.
- **Global Patterns**: create/read/update/delete on patterns with editable success_rate, usage_count and quality score. The form is prefilled with 0.9 / 8.0, so admins can seed made-up "learned" statistics.
- **Elsewhere, not route-gated**:
  - Dashboard Emergency Kill Switch (POST `/admin/kill-all`, isAdmin only, `Dashboard.jsx:288`).
  - Settings → audit export (GET `/api/admin/audit-logs/export`, raw fetch, `Settings.jsx:364`).
  - SSO/SCIM, delete org, data region, autonomous mode — all on the ungated Settings page.

### 4.6 Compliance (`Compliance.jsx`)
- Org report tiles from GET `/compliance/org-report`: runs, approval rate, scans, regions, models.
- Per-run rows with an evidence ZIP (GET `/compliance/artifacts/{runId}`), and an audit tail of the first 50 rows.
- Static reference panels: `INDIA_FRAMEWORKS` (90 lines, `:5-95`) and 5 global frameworks (`:309-315`), plus an EU AI Act badge. These are not tied to the org's state.
- Promise.all includes `/audit/logs`, which returns 403 for members and viewers, so the whole page errors for non-admins.
- Related surfaces:
  - Designer Compliance tab sends `production_country` and `compliance_flags`.
  - Settings DataRegionPanel (`global|eu|us|apac|uk` → POST `/account/settings {data_region}`).
  - ProjectView compliance card (GET `/factory/runs/{id}/compliance`).
  - Signup ToS/DPA consent; Profile GDPR export (GET `/account/data-export`) and erase (DELETE `/account`).

### 4.7 Guardian (`Guardian.jsx`)
- 30s poll of status, stats, events (severity filter) and the last 20 snapshots.
- Threat hero card showing 24h severity counts; counters (today, week, all-time, auto-recoveries, by type).
- Tabs: Threats and Snapshots.
- Actions: Resolve event, Snapshot Now, Scan Now (failure hidden: "scan endpoint may not exist", `:241`), **Restore DB from snapshot**, **Refresh integrity baseline**. Both bold actions are visible to every authenticated role; only the backend can stop a viewer.
- Dashboard shows a Guardian widget (GET `/guardian/status`, `/guardian/stats`).

### 4.8 Billing / pricing
- **Pricing** (public):
  - GET `/billing/plans`. Razorpay flow: POST `/billing/create-order` → checkout.razorpay.com → POST `/billing/verify-payment`.
  - Hardcoded demo terminal (ClinicPro, 39,814 files, 7m29s `:26-54`) and stats (29 phases, ~8 min, 39K+).
  - Fallback plan grid $0/$49/$199 (`:408`). The FAQ says Stripe.
- **Billing** (admin):
  - India orgs (detected from `usage.country`) use Razorpay; others use Stripe (POST `/billing/stripe/checkout`, GET `/billing/stripe/portal`). Cancel (India only), invoices.
  - **Bugs**: USD prices hardcoded `pro ? 29 : 149` (`Billing.jsx:357`). The Stripe `success_url` is `${origin}/billing?…`, missing the `/dashboard` basename, so the return handler never fires (`:115`). Invoice amounts always shown as `$` cents/100.
- **Inconsistent price points**: landing page ₹0 / ₹999 / ₹4,999; Pricing fallback $49 / $199; Billing $29 / $149.

### 4.9 Marketplace / plugins / connectors
- **Marketplace**: browse and search profiles, install (POST `/marketplace/install/{id}`), uninstall (DELETE `/marketplace/profiles/{id}` — this path reads like deleting the profile itself), publish with a price (POST `/marketplace/publish`, open to any role).
- **ConnectorHub** (`/v2/plugins`): catalogue of connectors, Connect form generated from `config_schema` (secret fields masked), Test, Edit Config, Uninstall. Install, uninstall and test have no catch blocks, so failures become unhandled promise rejections.
- **PluginManager** (`/v2/plugins/skills`): parameter forms hardcoded client-side (`:24-52`); Generate → files, deps and env vars, with copy.

### 4.10 Intelligence hub
- **`/intelligence`**:
  - Load: GET `/intelligence/global-insights` and `/intelligence/quality-benchmark`.
  - "Run Analysis" fires POST `arch-governor/review {run_id:'global'}`, `tradeoff-engine/analyze`, `truth-engine/validate` (20s client timeout).
  - Tools: Conflict Resolver (detect → resolve), Maintenance Engine scan (deps, code debt or run health), Improvement Loop cycle (`?run_id=`).
  - Field mismatch: the hub reads `insights`/`items` from global-insights, but GlobalPatternsTuning reads `global_patterns`/`stats` from the same endpoint, so the Insights card is likely always empty.
- **`/learning`**: stats, golden builds (fed by FeedbackPanel ratings of 4 or more), patterns, clarification answers.
- **`/memory`**: D3 force graph (`/memory/graph`), recall search (`/memory/search`), stored preferences, LLM cache stats.

### 4.11 Settings (single scrolling page; `/settings/sso` only scrolls to the SSO panel, `Settings.jsx:19-23`)
- **Main column**:
  - ApiKeyPanel: anthropic, gemini, openrouter → POST `/settings/api-keys`, POST `/settings/test-provider`.
  - PlanLimitsPanel: GET `/orgs/me/usage`.
  - ModelConfigPanel: OpenRouter heavy/light model and fallback chain from GET `/settings/models` (Pro-only models disabled); PUT `/settings/llm-config`, POST `/settings/models/test`.
  - BedrockPanel: AWS keys, region, heavy/light model, set as primary. **Bug**: the Test button sends only `{provider:'bedrock'}` and ignores the keys just typed (`Settings.jsx:255-258`).
  - CouncilPanel: enabled, strict/permissive → PUT `/settings/council-config`.
  - LangsmithPanel: GET/POST `/settings/langsmith`.
  - PhaseControlsPanel: 21 phases, enabled/priority → POST `/settings/phases/{p}/config`.
  - FileBrowserPanel: run files through highlight.js.
- **Side column**:
  - LLMStatusPanel; FactoryStatsPanel (avg cost falls back to hardcoded `'2.45'`).
  - SSOPanel (IdP entity ID, SSO URL, X.509 → PUT/DELETE `/settings/sso`).
  - SCIMPanel (shows base URL `/api/scim/v2`; rotate → POST `/settings/scim/rotate`; token shown once).
  - AuditExportPanel (raw fetch to `/api/admin/audit-logs/export`).
  - OrgConfigPanel (autonomous_mode → POST `/account/settings`; Delete org → DELETE `/account/org`, type the org name to confirm).
  - DataRegionPanel; VersionInfoPanel.
- **No in-page role check**: members and viewers see SSO, SCIM, org delete and API-key controls.

## 5. CLI and VS Code extension

### 5.1 CLI — `aether` (`cli/aetheros.py`; config in `~/.aetheros/config.json` as `{url, token, email}`; talks to the gateway directly, without `/api`)
| Command | Endpoint(s) | Notes |
|---|---|---|
| `login --url --email --password` | POST `/auth/login` | No MFA handling (an `mfa_required` response has no `access_token`, so login fails with a KeyError). Refresh token not stored. |
| `logout` | POST `/auth/logout` | Deletes the local config |
| `whoami` | GET `/account/usage` | Plan, org |
| `run "<req>" [-d domain] [-n name] [-t template] [-w]` | POST `/factory/start {raw_input, domain, project_name?, template_id?}` | `-w` → `_do_watch` polls GET `/factory/runs/{id}` |
| `ls` | GET `/factory/runs` | Table with a 12-phase bar |
| `status <id>` | GET `/factory/runs/{id}` | Phase table (12 phases) |
| `logs <id>` | GET `/factory/runs/{id}/stream` with Bearer header | **Broken**: the backend needs `?sse_token=` (401) |
| `cancel <id>` | POST `/factory/runs/{id}/cancel` | |
| `download <id> [-o dir]` | GET `/factory/runs/{id}/artifacts`, then GET `/factory/artifacts/{art_id}/download` | **Broken**: no `/factory/artifacts/{id}/download` route exists in `gateway/`. The working ZIP path is `/factory/runs/{id}/download`. |
| `open <id>` | — | Opens `{url with :8000/:8080→:3000}/project/{id}` — wrong host and missing the `/dashboard` basename |
| `config [--url] [--token] [--show]` | — | |
| `health` | GET `/health` | |

Packaging: `cli/setup.py` sits inside `cli/` and declares entry point `cli.aetheros:main` with `find_packages()`. Installing from `cli/` won't include the `cli` package.

### 5.2 VS Code extension — `aetheros-factory` 1.0.0 (`vscode-extension/`)
Settings: `aetheros.gatewayUrl` (default `http://localhost:8000`), `aetheros.token` (JWT stored in plain user settings), `aetheros.autoRefreshSeconds`.
| Command | Endpoint(s) |
|---|---|
| `aetheros.configure` | prompts for URL, email, password → POST `/auth/login` (no MFA) → saves token |
| `aetheros.newRun` | POST `/factory/start {raw_input, domain (7 choices), project_name?}` |
| `aetheros.listRuns` / `refreshRuns` / status bar | GET `/factory/runs?limit=N` (auto-refresh, minimum 5s) |
| `aetheros.showStatus` | GET `/factory/runs/{id}` → webview (12 phases, no HTML escaping, scripts disabled) |
| `aetheros.streamLogs` | GET `/factory/runs/{id}/stream` with Bearer header — **401** (needs sse_token) |
| `aetheros.cancelRun` | POST `/factory/runs/{id}/cancel` (menu `when` clause `viewItem != completedRun` is meaningless because contextValue is always `run`) |
| `aetheros.openDashboard` | opens gatewayUrl with :8000→:3000 (no `/dashboard`) |
| `aetheros.openProjectFolder` | POST `/factory/runs/{id}/open-in-vscode` → `vscode.openFolder` (only works if the gateway shares the local filesystem) |
Views: activity bar container `aetheros`, with tree views `runsView` ("Factory Runs") and `statusView` (declared, no provider registered). `media/icon.png` is missing.

### 5.3 Public landing page (`public/index.html`, `public/js/landing.js`)
- Static marketing: nav (Platform, How it works, Pipeline, Pricing) and CTAs to `/dashboard/signin` and `/dashboard/signup`.
- Lists a 29-phase pipeline: p00 Research, p00b Data Archaeology, p01b Integration Discovery, p02c Permission Modeling, p04b Business Logic, p04c Integration Codegen, p11e Enterprise Deployment, p15 Handoff Package, …
- Pricing ₹0 / ₹999 / ₹4,999; footer "API Status" link → `/api/health`.
- landing.js: three.js hero, IntersectionObserver reveal, card tilt. No API calls. gsap and ScrollTrigger are vendored but not loaded.

## 6. Plane mapping

| Plane | UI surfaces |
|---|---|
| **SDLC** (build pipeline) | Wizard `/new`, Designer `/designer`, NewProjectModal, PromptInput, ProjectsList, ProjectView (phases, spec gate, clarifying Q&A, branch/Add Feature, rerun-from-phase), PhaseDetail, Frontend/Backend Builders, FileExplorer (edit generated code), GitHub push, ZIP, VS Code open; CLI `run/ls/status/cancel`; VS Code `newRun` |
| **STLC** (testing / quality) | ProjectView p07 test badge, QualityPanel (auth/validation/test coverage, Docker), Council review panel, security grade (p06), Dashboard quality trend chart (`/factory/analytics/quality-trend`), FeedbackPanel → golden builds, BackendBuilder validate-spec, Settings Council strict mode. **No dedicated test-results page.** |
| **SRE / observability** | SystemHealth `/health` (services, CPU/mem/disk, SLA p50/p95, LangSmith), TopBar status pill, Dashboard health and no-LLM warnings, CostDashboard, TraceTab (LLM traces), AgentEventsLog, LogViewer, Settings LangSmith, Guardian auto-recovery counters; CLI `health` |
| **Security** | Login MFA/OAuth/SAML, Profile MFA and password, Settings SSO/SCIM, Guardian (threats, integrity baseline, snapshots), ProjectView security grade, Agents (red_team, policy, stability_guardian restricted), API-key management |
| **Compliance** | `/compliance` (org report, evidence ZIPs, framework reference), Designer Compliance tab (country, data flags), Settings Data Region, AuditLogs and audit export, Signup ToS/DPA consent, Legal page, Profile GDPR export and erase, ProjectView run compliance card |
| **Deployment** | ProjectView Deploy/Stop (`/deploy`), Run App panel (`/run-app` → `/app-preview/`), App Preview iframe, `/deployments` list and undeploy, RunDetail deploy/undeploy, Env Vars editor |
| **Admin control** | `/admin/users`, `/audit`, `/admin/billing`, `/admin/intelligence`, Dashboard kill switch, Settings (org config, autonomous mode, delete org, phase enable/priority, LLM routing), prune artifacts, OrgSwitcher |
| **API management / integrations** | Settings ApiKeyPanel (LLM provider keys) and Bedrock; WebhookSettings (outbound events `run.*`, `phase.completed`, `decision.requested`, `deploy.completed`); SCIM token; ConnectorHub (`/v2/plugins` connectors); Marketplace and PluginManager. **Missing: no UI to mint personal or org API tokens for programmatic access** — CLI and VS Code reuse the login JWT. |
| **Human-in-the-loop / governance** | SpecReviewModal (approve-spec), DecisionsPanel, ClarifyingQuestionsPanel, ClientPortal approve/feedback, autonomous_mode toggle |
| **Learning / AI knowledge** | IntelligenceHub, Learning, MemoryInspector, GlobalPatternsTuning |
| **Commercial** | Pricing, Billing, trial banner, plan limits, storage widget |
| **Collaboration / tenancy** | Workspaces (cosmetic), OrgSwitcher, NotificationBell, ClientPortal |

## 7. Reality check

### 7.1 Broken against the backend (verified in `gateway/`)
1. **SSE auth mismatch**: `/factory/runs/{id}/stream` requires `?sse_token=` (`gateway/routers/factory_run_streaming_router.py:45-70`). These clients get a 401:
   - RunDetail LiveEventLog (`?token=JWT`, `RunDetailComponents.jsx:105`)
   - CLI `logs` (Bearer header, `cli/aetheros.py:308-314`)
   - VS Code `streamLogs` (Bearer header, `vscode-extension/src/client.ts:76-80`)

   Only `useProjectView.js:144-152` works.
2. **CLI `download`** calls `/factory/artifacts/{id}/download`, which has no matching route.
3. **Password reset confirm**: the email link goes to `/reset-password?token=`. There is no SPA route for it and no caller of `/auth/password-reset-confirm`.
4. **AuditLogs filters** `from_date`, `to_date` and `user_id` are ignored by the backend (`compliance_router.py:55-60`). Export ignores all filters.
5. **Compliance page** fails entirely for non-admins (`/audit/logs` returns 403 inside Promise.all).
6. **Stripe return URL** is missing `/dashboard` (`Billing.jsx:115`).
7. **IntelligenceHub insights field mismatch** (`insights|items` vs `global_patterns`).
8. **Response-shape disagreement**: CostDashboard expects `this_month/targets/cache/history` from `/system/costs`; RunsContext and TopBar expect `today_usd/tokens_today`. Needs a check against the backend.

### 7.2 Frontend bugs
- `RunDetail.jsx:420` uses `XCircle` without importing it, so the page crashes on failed runs.
- RunDetail's Edit & Restart → `/new-project` state is lost.
- ProjectDesigner tab guard off by one (`:486-491`). RunOutput treats the phases dict as an array.
- ProjectView spec-review banner can't open the modal (circular condition `:325`).
- Dashboard "Completed Today": `new Date(started_at)` with epoch seconds (`:248`). "Tokens (Month)" shows `tokens_today` (`:257`). `useProjectView.js:105` does `Date.now() - run.started_at`, so the units disagree across pages.
- Settings Bedrock test ignores the entered credentials (`Settings.jsx:255-258`).
- MemoryInspector ResizeObserver never attaches (graph fixed at 800px). Pagination refetches everything twice.
- Profile: MFA "disabled" success message never shows. A usage failure skips loading MFA status.
- `/auth/mfa/confirm` is not excluded from the 401 interceptor.
- Learning golden-build links use a raw `<a href="/project/…">` without `/dashboard`.
- ConnectorHub and PluginManager: no catch blocks, so failures are unhandled promise rejections.
- Errors masked as empty states: Learning, MemoryInspector, Guardian scan, ForgotPassword (by design), ProjectsList actions (`/* silent fail */` at `:118,:130,:147`).
- Workspaces "View Projects →" goes to `/projects?workspace=`, which ProjectsList ignores. No creation flow sends a workspace id, so workspaces don't scope anything in the UI.

### 7.3 Hollow / hardcoded
- Compliance: `INDIA_FRAMEWORKS` and the global framework grid (static reference text styled as status).
- CostDashboard: `COST_TARGET=0.35`, "80K users" projection, "Prompt caching 90%", "Context compression ~70%", budget default 500000.
- Pricing: fake LivePipelineDemo, "29 phases / ~8min / 39K+ files / 100%", fallback $0/$49/$199, FAQ says Stripe.
- Billing: USD 29/149 hardcoded. Landing page: ₹ pricing and the 29-phase marketing list.
- ClientPortal: "End-to-End Encrypted" badge, fixed "proceed to Architecture" copy.
- AccountSettings: avg cost fallback `'2.45'`, Gemini label "gemini-1.5-pro". Settings default OpenRouter models (`minimax/minimax-m2.5:free` and others, `:41-45`).
- ClarifyingQuestionsPanel: synthesizes "Please clarify ambiguous field N" placeholders when details are missing (`:17-21`).
- FrontendBuilder: device preview toggle does nothing. Builders without a run id are client-only toys.
- PluginManager parameter forms, NewProjectModal DOMAIN_DATA stacks and compliance, Designer model list (`claude-sonnet-4-6`, `gemini-2.0-flash`, `qwen2.5-coder:7b`), Wizard DEFAULT_MODELS: all hardcoded catalogues.
- PromptInput: `SCOPE_GUARD` defined but unused. Canned "started the pipeline" message.

### 7.4 Dead / unrouted
- `pages/NewProject.jsx` (lazy-imported, no Route)
- `components/project/LiveFeed.jsx`
- `components/ui/GlassCard.jsx`, `GradientButton.jsx`, `SkeletonLoader.jsx`
- `public/js/vendor/gsap.min.js`, `ScrollTrigger.min.js`
- `dashboard/README.md` (Vite template)
- VS Code `statusView` (declared, no provider)
- **Unused `api.js` helpers (20)**: `login`, `getOrgSettings`, `deleteOrg`, `approveAction` (`/pipeline/approve/{ticket}`), `getPortalPhase`, `installMarketplaceProfile`, `fetchGitHubRepo` (`/factory/fetch-github-repo` — pages use `/factory/fetch-repo`), `searchMemory`, `getPreferences`, `updatePreferences`, `updateWebhook`, `testWebhook`, `updateWorkspace`, `uninstallMarketplaceProfile`, `getInstalledProfiles`, `reactivateUser`, `resetUserPassword`, `getInvoices`, `cancelSubscription`. Pages call the same paths through raw `api.client`. About 60% of call sites bypass `api.js`.

### 7.5 Phase-list drift (six different lists)
| Location | Count | Notes |
|---|---|---|
| `components/project/projectConstants.js:3-25`, `settings/PhaseSettings.jsx:5-11`, `run-detail/RunDetailComponents.jsx:4-26` | 21 | p01…p14_client_portal |
| `pages/ProjectsList.jsx:12-36` | 23 | adds p00_research, p04b_business_logic |
| `components/RerunDropdown.jsx:6-19`, `components/PhaseBar.jsx:4-17`, `cli/aetheros.py:38-43`, VS Code `runsProvider.ts:13` and `statusPanel.ts:3` | 12 | p01…p11 |
| `pages/LogViewer.jsx:25-47` | ~21 | plus any extra phases from the run |
| `public/index.html`, Pricing copy | 29 | marketing |

The brief says ~50 backend phases. No UI fetches the phase list from the backend, so phases such as p00b, p01b, p02c, p04c, p11e and p15 never appear in progress bars or rerun menus.

### 7.6 Security-relevant UI observations (for the security plane)
- Role checks are cosmetic: an unverified JWT decode (`useRole.js`, `Sidebar.jsx:15-41`). Guardian restore and baseline, Settings SSO/SCIM/org delete, Marketplace publish, Deploy and GitHub push have no UI gate for members or viewers.
- Tokens live in localStorage (XSS-exposed), and the CSP allows `unsafe-inline` and `unsafe-eval` (`dashboard/index.html:5`).
- OAuth tokens are passed in the URL query (`OAuthCallback.jsx`).
- ProjectView preview iframe uses `sandbox="allow-scripts allow-same-origin"` with srcDoc of generated HTML (`ProjectView.jsx:407`), which defeats the sandbox. AppPreviewPanel uses the same pair for `/app-preview/` (same origin).
- Bulk SCIM import uses the user JWT on `/scim/v2/Users` (backend dev fallback).
- `<a href="/api/portal/{id}/download">` (`ProjectView.jsx:306`) sends no Authorization header, so either the endpoint is public or the link fails.
- VS Code stores the JWT in plain settings. The CLI stores it in `~/.aetheros/config.json` (no file-permission hardening seen).
- Agents page sends free-text `project_path` and `file_path` to `/agents/{name}/run`; the backend must validate them.

## 8. Open questions (for the lead to cross-check)
1. Is `GET /portal/{id}/download` intentionally unauthenticated? Same question for `/portal/{id}/status|approve|feedback`, which the public `/portal/:id` route uses.
2. Which `/system/costs` response shape is canonical: CostDashboard's `this_month/targets/cache/history`, or RunsContext's `today_usd/tokens_today`?
3. Is `started_at` epoch seconds or milliseconds in the run API? Pages disagree (Dashboard, useProjectView, Compliance, Deployments).
4. What is the canonical phase sequence (the brief says ~50)? Should the UI fetch it, for example from `/settings/phases/config`?
5. Does `/intelligence/global-insights` return `insights` or `global_patterns`?
6. Does DELETE `/marketplace/profiles/{id}` uninstall for the org, or delete the published profile?
7. Does the backend enforce roles on Guardian restore and baseline, `/settings/sso`, `/settings/scim/rotate`, DELETE `/account/org`, `/marketplace/publish`, `/factory/runs/{id}/deploy` and `push-github` for viewers and members?
8. Does the pipeline consume the FrontendBuilder and BackendBuilder specs (`/frontend-spec`, `/backend-spec`), Designer `compliance_flags` and `production_country`, and `tech_preferences`?
9. Does `/factory/start` accept NewProjectModal's domain keys (`industrial`, `saas_multitenant`, `logistics`) and the Wizard's generic `model_preference` IDs (`claude-sonnet`, `gemini-flash`, `qwen-coder`)?
10. Are workspaces supposed to scope runs? No UI sends a `workspace_id`, and ProjectsList ignores `?workspace=`.
11. Is there a programmatic API-token feature (personal access tokens) on the backend with no UI, given that CLI and VS Code reuse the short-lived login JWT with no refresh?
12. Should `/api/admin/audit-logs/export` (Settings) and `/audit/logs/export` (AuditLogs page) be consolidated? They are two separate export endpoints.
