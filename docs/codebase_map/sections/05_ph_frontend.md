# 05_ph_frontend — Frontend generation (React/Vite/TanStack) + alternative app targets

Scope: `phases/p05_frontend/` (20 files, 11,405 LOC), `phases/p05b_mobile` (4 files, 363), `p05c_desktop` (4, 445), `p05d_cli` (5, 924), `p05e_serverless` (5, 1,134). 38 files, 14,271 LOC total. Commit 052a101. Mapped 2026-11-08. Every file was read in full. All citations are `file:line`, relative to `phases/` unless they start with another top-level dir.

Status tags: **REAL** = deterministic code that does what it claims. **LLM-DRIVEN** = output comes from an LLM call (prompt and client method named). **TEMPLATE** = string-template emitter. **STUB/HOLLOW** = looks complete but is missing pieces or is unreachable at runtime. **DEAD** = never called (checked with grep across the repo, excluding tests).

---

## 1. Summary

- **What it is.** p05 turns entities into a React 18 + Vite 6 + TypeScript + TanStack (Router/Query/Table) + Tailwind + shadcn-style project. Entities come from Domain IR (`domain_ir.json`) or from architecture/models.py/route manifests. It is mostly a **template emitter**: `code_writer.py` holds 62 `def` generators, ~5.8K LOC of f-string TSX. There is an **LLM-first overlay** for the Dashboard, entity CRUD pages, portal Home, a decorative DomainWidget, a compile-error fix loop, and a vision-critique loop. Each LLM path falls back to a template.
- **Who calls it in production.** The `s04_frontend` stage supervisor calls `p05_frontend.task_agent.run` directly (`stages/s04_frontend/supervisor.py:106-112`, `_run_sub_phase` at :310-333). That means `FrontendSupervisor` and `gate.py` (TS type-check + FK schema-contract check) are **bypassed in the pipeline** and run only in tests. The stage gate only checks sentinel files plus `result.success` (`stages/s04_frontend/supervisor.py:262-306`).
- **Alternative targets.** p05b (Expo RN), p05c (Electron), p05d (Click/Cobra CLI) and p05e (Knative or AWS SAM) are deterministic TEMPLATE emitters. They are selected by `build_profile` flags and **dispatched twice**, by s04 (`stages/s04_frontend/supervisor.py:125-213`) and again by s12 (`stages/s12_specialist/supervisor.py:104-114, 219-220`). None of them is built, compiled or tested. Several emit artifacts that cannot work (see §7).
- **Headline reality.**
  1. The deterministic React baseline very likely **does not compile as emitted**:
     - `NotFoundPage` imports `react-router-dom`, which is not a dependency (`p05_frontend/code_writer.py:2332`).
     - Template entity pages import `Pagination`, `Skeleton` and `RoleGuard` components that are never written (generators DEAD; `code_writer.py:2356,2436,2497,3544-3546`).
     - Login destructures `refresh_token` from a type that only has `access_token` (`code_writer.py:978` vs `:2615`).
     - Kanban, Calendar and CommandPalette import `<entity>Api` symbols that usually don't exist.

     The pipeline relies on the 3-round LLM `build_loop` to patch these.
  2. **Auth-token key mismatch.** `auth.ts` stores `auth_token` (`code_writer.py:837`). The LLM page prompt, the SSE hook, the WS hook and the Electron views read `localStorage['token']`. The cloud console reads `access_token`. So LLM-written CRUD pages send no JWT.
  3. Two `NameError`s silently disable features:
     - `get_llm_client` is never imported in `helpers.py`. DomainWidget generation and **all Gate-2/VLM revisions** become no-ops.
     - `_AT` and `_json` are undefined in `domain_assembler.py`.
  4. **Two divergent copies of the frontend.** The build loop patches `project/frontend`. Gate-2 revisions and run_app use `project/p05_frontend/frontend`.

---

## 2. Coverage table

| File | LOC | Purpose | Status |
|---|---|---|---|
| p05_frontend/__init__.py | 3 | exports `FrontendSupervisor` | REAL |
| p05_frontend/supervisor_agent.py | 18 | PhaseBase wrapper → task_agent + gate.py | DEAD in pipeline (s04 calls task_agent directly) |
| p05_frontend/task_agent.py | 507 | main orchestrator: profile routing, entity resolve, phases 1-9, gates, npm build, confidence | REAL (orchestrates LLM + template) |
| p05_frontend/domain_assembler.py | 592 | scaffold writer, layout-mode detection, entity page assembly (LLM→template), DomainWidget, Gate 3, Gate 2 | REAL with bugs (§7) |
| p05_frontend/code_writer.py | 5830 | 62 TSX/config string generators + 57 public aliases (`:5771-5830`) | TEMPLATE (pre-approved size). Several generators DEAD |
| p05_frontend/helpers.py | 597 | write-guard, `_generate_file`, DomainWidget LLM prompt, admin-feature derivation, customer portal, landing page, SSE hook, UI lib writer | LLM-DRIVEN + TEMPLATE. **Broken**: `get_llm_client` undefined |
| p05_frontend/llm_page_writer.py | 279 | LLM entity page, dashboard and portal home writers; `compute_template_debt` | LLM-DRIVEN (`get_llm_client().call`, task_type `code_generation`) |
| p05_frontend/ir_generators.py | 565 | Domain-IR → p05 entity dicts; IR dashboard; IR types+Zod; IR entity page with FK `<select>` | TEMPLATE (REAL); `generate_ir_dashboard_stats` DEAD |
| p05_frontend/scaffold.py | 532 | domain keyword scoring, architecture reader, models.py/main.py column scrapers, naming/type/field mappers | REAL |
| p05_frontend/prompts.py | 419 | data tables: stat labels, widget descriptions, fallback widgets, colour hints, icon/emoji maps, theme CSS, domain keywords | REAL data; `get_domain_color_hint`, `ALL_USED_ICONS` DEAD |
| p05_frontend/design_system.py | 351 | per-domain Tailwind token dict + `get_design_tokens` | REAL |
| p05_frontend/domain_pages.py | 277 | injects Social/IoT/ERP/Flags/Kanban/Calendar pages and CommandPalette; regex-patches App.tsx and Layout.tsx | TEMPLATE; patches fragile (§7) |
| p05_frontend/build_loop.py | 145 | `tsc --noEmit` + `npm run build` → LLM find/replace patches, ≤3 rounds; has `__main__` self-check | LLM-DRIVEN (`call`, `code_generation`, 2000 tok) |
| p05_frontend/preview.py | 171 | Playwright screenshot of `dist/`; VLM rubric critique; Gate-2 revision rewriter | LLM-DRIVEN (`call_vision` task_type `ui_critique`; `_generate_file` `code_refinement`). Revisions broken via helpers NameError |
| p05_frontend/gate.py | 145 | required files, entity pages, deps, tsc, FK endpoints vs `api_routes.json` | REAL but DEAD in pipeline (tests only: `tests/test_phases_later.py:61,99`) |
| p05_frontend/npm_runner.py | 83 | npm semaphore (2), package.json-hash node_modules stamp, shared cache; `run_npm_build` | REAL; `run_npm_build` DEAD (imported, never called) |
| p05_frontend/governor_integration.py | 40 | ArchitectureGovernor phantom-entity check on page names | REAL (advisory only) |
| p05_frontend/cloud_console_generator.py | 81 | `build_type=cloud_platform` → JSX cloud console | TEMPLATE |
| p05_frontend/cloud_console_app.py | 220 | console package.json, index.html, main.jsx, App.jsx (react-router-dom), vite config | TEMPLATE; `/services/*` nav has no route |
| p05_frontend/cloud_console_pages.py | 550 | console Dashboard, ServiceCatalog, ResourceExplorer (WS), CostDashboard, Settings | TEMPLATE; Settings save HOLLOW |
| p05b_mobile/__init__.py | 0 | — | — |
| p05b_mobile/supervisor_agent.py | 23 | PhaseBase wrapper | DEAD in pipeline (s04/s12 import task_agent) |
| p05b_mobile/task_agent.py | 55 | skip unless `frontend_framework=react_native`; reads `data["domain_ir"]` dict | REAL |
| p05b_mobile/rn_generator.py | 285 | Expo app: package/app.json, axios+SecureStore client, Login, per-entity List screen, navigator | TEMPLATE; detail screens/hooks promised but not emitted (HOLLOW) |
| p05c_desktop/__init__.py | 0 | — | — |
| p05c_desktop/supervisor_agent.py | 23 | wrapper | DEAD in pipeline |
| p05c_desktop/task_agent.py | 55 | skip unless `frontend_framework=electron` | REAL |
| p05c_desktop/electron_generator.py | 367 | Electron main (spawns uvicorn), preload IPC, Vite renderer, per-entity CRUD view, electron-builder | TEMPLATE; several runtime breaks (§7) |
| p05d_cli/__init__.py | 0 | — | — |
| p05d_cli/supervisor_agent.py | 23 | wrapper | DEAD in pipeline |
| p05d_cli/task_agent.py | 53 | skip unless `build_type=cli`; Go if `backend_lang=go` | REAL |
| p05d_cli/cli_generator.py | 431 | Click project (pyproject, keyring config, entry) or Cobra (root, entity, go.mod) | TEMPLATE |
| p05d_cli/cli_templates.py | 417 | Click auth/config/entity CRUD command modules (httpx + rich) | TEMPLATE (most complete alt target) |
| p05e_serverless/__init__.py | 0 | — | — |
| p05e_serverless/supervisor_agent.py | 23 | wrapper | DEAD in pipeline |
| p05e_serverless/task_agent.py | 138 | skip unless arch ∈ {serverless, event_driven}; AWS SAM if `cloud_provider=aws`/lambda target, else Knative | REAL routing |
| p05e_serverless/serverless_generator.py | 388 | Knative Service + Broker/Trigger + handler (Py/Go) + Dockerfile per entity×{created,updated,deleted} | TEMPLATE; handler path unreachable (§7) |
| p05e_serverless/lambda_generator.py | 585 | SAM template, Mangum handler, per-entity SQLAlchemy Lambda, Makefile, samconfig, README | TEMPLATE; **SAM YAML invalid** (verified by executing) |

---

## 3. Components

### 3.1 Target selection (what decides what gets generated)

| Signal (`input_data`) | Effect | Where |
|---|---|---|
| `build_profile.build_type == "cloud_platform"` | p05 emits the JSX cloud console instead of the CRUD app, then returns at confidence 0.9 with no build. Falls through to React on exception | `p05_frontend/task_agent.py:139-160` |
| `build_profile.frontend_framework == "none"` | p05 skips with success | `task_agent.py:162-170` |
| `frontend_framework` ∉ {react, ""} (e.g. react_native, electron) | p05 **still generates React** ("generator not yet implemented" log). Mobile/desktop are **additive** | `task_agent.py:171-175` |
| `frontend_framework == "react_native"` | p05b runs (s04 and s12) | `stages/s04_frontend/supervisor.py:49-51`, `stages/s12_specialist/supervisor.py:104-105`, `p05b_mobile/task_agent.py:26` |
| `frontend_framework == "electron"` | p05c runs | s04 :54-56, s12 :107-108 |
| `build_type == "cli"` | p05d runs (React is still generated too) | s04 :59-61, s12 :110-111 |
| `architecture ∈ {serverless, event_driven}` | p05e runs from s04. s12 triggers only on `serverless` (inconsistent) | s04 :64-66, s12 :113-114, `p05e_serverless/task_agent.py:19,29` |
| `cloud_provider=="aws"` or `deployment_target∈{aws,lambda,aws_lambda}` | p05e emits SAM/Lambda, else Knative | `p05e_serverless/task_agent.py:49-56` |
| `build_profile.backend_lang=="go"` (CLI) vs `backend_language` (serverless) | Go variants. **Inconsistent key names** | `p05d_cli/task_agent.py:41`, `p05e_serverless/task_agent.py:45` |

Inside the React app, **layout mode** (`detect_layout_mode`, `domain_assembler.py:274-312`) is chosen in this priority order: `designer_spec.layout_mode` → `design.layout` → `has_customer_portal` → `"dual portal"`/`"customer portal"` keyword → `_DUAL_PORTAL_DOMAINS` (`:36-41`) → `_INTERNAL_ONLY_DOMAINS` (`:44-47`) → `storefront` keywords → `admin` keywords → default `dual`.

**Domain detection** (`scaffold.py:31-68`) trusts `phase_input.domain` unless it is generic (`saas` and `ecommerce` are also distrusted). Otherwise it keyword-scores `DOMAIN_KEYWORDS` (`prompts.py:371-419`) and needs a score ≥3; the default is `saas`.

### 3.2 React app pipeline (task_agent.run, `task_agent.py:128-507`)

1. **Entities** (`:183-215`):
   - IR fast path: `DomainIR.load(domain_ir_path)` → `ir_to_p05_entities` (`ir_generators.py:47-88`). This adds typed `fields`, `input_type`, `ref_entity`, and a naive `ref_table` (+"s").
   - Fallbacks: `normalise_entities(arch)` (`scaffold.py:304-346`) → models.py regex scrape (`scaffold.py:238-299`) → P67 `data["entities"]` (`scaffold.py:500-532`) → generic `items`.
   - `read_architecture` (`scaffold.py:73-156`) loads `p02_architecture_path`, inline `architecture_json`, or the `architecture.json` found by rglob. It builds `api_route_map` (table→GET path) from p04's `api_routes_path` and augments the schema with columns scraped from models.py/main.py (`scaffold.py:159-235`).
2. **Design inputs** (`:228-251`): `designer_spec.design.*` (ui_theme, transitions, colors hex, font_pairing, radius, density), `design_brief`, `user_personas`, `has_customer_portal`, `has_landing_page`, `app_brand`, `app_tagline`, `realtime_features`, `build_types`. `ui_theme` defaults to the domain theme (`_DOMAIN_THEME_MAP`, `:118-125`).
3. **Scaffold, phases 1-5** (`domain_assembler.write_scaffold_and_components`, `domain_assembler.py:50-202`). All writes go through `_write_with_guard`, which **never overwrites** (`helpers.py:51-65`).
   - Config: package.json (`code_writer.py:39-99`; React 18.3, TanStack Query 5/Router 1/Table 8, axios, zod, react-hook-form, radix, framer-motion, recharts, vitest), vite.config (`base:'/app-preview/'`, `@` alias, `/api` proxy with prefix strip; `:124-154`), tsconfig strict (`:157-182`), tailwind with per-domain/theme `brand` palette + `darkMode:'class'` (`:185-466`), postcss, index.html with OG/Twitter/JSON-LD (`:477-536`).
   - Ops files: nginx.conf (`/api/` → `container_name:app_port`, security headers, SPA fallback; `:539-590`), multi-stage Dockerfile (`:593-613`), `.env.example`, `public/_headers` (CDN), `.eslintrc.cjs`, README.
   - `index.css` composes THEME_CSS, transition, skeleton, hover-lift, micro-interaction and scroll-reveal CSS (`:742-799`).
   - `main.tsx`: QueryClient → ToastProvider → ErrorBoundary → RouterProvider (`:802-831`).
   - **Auth** `lib/auth.ts`: localStorage `auth_token`/`auth_refresh_token` get/set/clear (`:834-850`).
   - **API client** `lib/api.ts` (`_generate_api`, `:930-1007`):
     - axios `baseURL = VITE_API_URL ?? '' + ('/api' if no URL)`; `api` is an alias of it.
     - The request interceptor attaches the Bearer token. On a 401 (non-auth routes) the response interceptor clears the token and does `location.replace('/login')`, debounced.
     - `authApi.login/register` send JSON `{email,password}` to `/auth/login` and `/auth/register`.
     - Per entity it emits `<camel>Api.list/create/update(PATCH)/remove`, using `route_map[table]` or `/{table}`.
   - `types/index.ts`: interface, `XListResponse`, and `XCreate` (Omit) per entity, with nullable heuristics (`:855-927`).
   - **shadcn-style UI library**: 10 components (Button, Input, Card, Badge, Skeleton, Modal(radix), Select(radix), Toast(radix), Tooltip(radix), Table), written by `write_ui_components` (`helpers.py:507-530`; generators `code_writer.py:3987-4765`).
   - **App.tsx** (`_generate_app`, `:1010-1094`): TanStack Router with a root route, a `layout` route guarded by `beforeLoad: getToken()` → redirect `/login`, a Dashboard route at `/`, one route per entity at `/{table-with-dashes}`, `basepath '/app-preview'`.
   - **Dual portal** (`_generate_dual_app`, `:1097-1232`): customer layout at `/` with keyword-selected browsable entities, and admin layout at `/admin/*`. The admin guard decodes the JWT `role` client-side and requires `=== 'admin'` (`:1162-1206`).
   - Pages: LoginPage in 3 variants (dual = role redirect; storefront; admin) with a **hard-coded demo credentials banner** (`admin@example.com / Admin1234!`, `:2588-2875`), NotFoundPage, CustomerHome (dual), LandingPage (`has_landing_page`, `helpers.py:375-499`).
   - Hooks: `useRealtimeStream` SSE (`helpers.py:535-597`) when `realtime_features` is set; `useWebSocket` (`code_writer.py:3349-3422`) when websocket/realtime is detected.
   - Layout: dual → AdminLayout + CustomerLayout (`:1235-1370`); else `_generate_mobile_first_layout` (desktop sidebar + mobile bottom tabs + slide-in menu + dark mode; `:4984-5175`).
   - Shared components: DataTable (TanStack Table with sort and global filter; `:1855-1958`), **CrudModal** (react-hook-form; FK dropdowns; `:1961-2128`), Toaster, ErrorBoundary.
4. **Entity pages and dashboard, phase 6** (`domain_assembler.assemble_domain_pages`, `:315-468`), with semaphore 4:
   - **IR path**:
     - Dashboard is LLM first (`write_dashboard_llm`), with fallback `generate_ir_dashboard_tsx`. Ecommerce/marketplace get the storefront home; others get count cards from `/stats` plus quick links (`ir_generators.py:129-203`).
     - Entity pages are LLM first (`write_entity_page_llm`), with fallback `generate_ir_entity_page` (`ir_generators.py:313-565`). The fallback is a self-contained CRUD page with typed inputs, enum `<select>`, **FK `<select>`** fed by a `useQuery` on `/{ref_table}`, lookup maps that render FK names in the table, page/limit pagination, and PATCH update.
     - Storefront mode + product-like entity → `generate_product_grid_page` (`code_writer.py:3750-3917`).
     - Then `types/index.ts` is **overwritten** with IR interfaces + Zod schemas (`ir_generators.py:210-246`; `domain_assembler.py:406`).
   - **Non-IR path**:
     - Dashboard is LLM first, with fallback `_generate_domain_dashboard` (framer-motion KPIs with hard-coded entity names per domain, mock `TREND_DATA` recharts; `code_writer.py:4768-4981`).
     - Entity pages are LLM first, with fallback `_generate_entity_page` (`code_writer.py:3425-3747`). The fallback uses DataTable + CrudModal + Pagination + TableSkeleton + RoleGuard + CSV export + toast. FK columns are any `*_id` → `type:'fk-select'` with `fkEndpoint` = IR ref or the heuristic `/api/{pluralise(col[:-3])}` (`:3478-3500`).
   - Then `run_frontend_governor` (advisory; `governor_integration.py:10-40`) and `write_domain_pages` (`domain_pages.py:143-277`). The latter adds:
     - Social/IoT/ERP/Flags pages from `phases/patterns/frontend_patterns_{c,d,e}`.
     - Kanban, always for `project_management/saas/crm/hrm`, hard-wired to entity `tasks` (`:160-231`).
     - Calendar for `healthcare/erp/hospitality/fitness`, hard-wired to `appointments`/`events` (`:164-246`).
     - CommandPalette (`:257-277`).

     It regex-patches App.tsx and Layout.tsx (`:23-140`).
5. **DomainWidget, phase 7** (`domain_assembler.generate_domain_widget`, `:205-271` → `helpers._generate_domain_component`, `helpers.py:102-216`). The LLM prompt combines `DOMAIN_COMPONENT_DESC`, a colour hint (designer hex or `DOMAIN_COLOR_HINTS`), RAG context (`retrieval_ranker` + `context_compressor`), golden few-shots (`core.learning.golden_retriever`) and many style rules. It is called with `client.call(prompt, task_type="ui_component", max_tokens=2000)`. On success it writes `components/DomainWidget.jsx` and splices it into `{/* DOMAIN_WIDGET_SLOT */}`. **Currently always fails** (`NameError`, §7).
6. **Customer portal, phase 8**: a template `pages/customer/Home.tsx` + `AboutPage.tsx` (`helpers.py:234-370`), then `write_portal_home_llm` overwrites Home.tsx (`llm_page_writer.py:70-127`; `task_agent.py:377-403`). **These pages are never routed in App.tsx** (no route references `pages/customer/*`).
7. **Tests, phase 9**: vitest config, setup, `LoginPage.test.tsx`, `Dashboard.test.tsx` (`code_writer.py:2195-2269`; `task_agent.py:405-411`). LoginPage is rendered without a RouterProvider while it calls `useNavigate`, so it likely fails when run. The Dashboard test mocks only `apiClient`, not `api`.
8. **Gate 3, admin requirements** (`domain_assembler.run_gate3_approval`, `:471-521`). `_derive_admin_features` maps IR workflow triggers through `CUSTOMER_TO_ADMIN_MAP` (`helpers.py:221-229`). In non-autonomous mode it calls `DecisionEngine.request_approval` + `publish_event(PhaseApprovalRequired, gate_3)` + `await_decision`. **The result is discarded**: `admin_features` is never used after `task_agent.py:422`.
9. **Finalise**: writes root `docker-compose.yml` (app + frontend, SQLite default, `SECRET_KEY` default `changeme…`; `code_writer.py:3927-3969`). It copytrees `output_dir/frontend` → `project_dir/frontend` **only if the latter doesn't exist** (`task_agent.py:433-438`), then writes `frontend_meta.json` (template_debt_pct, model_used, degraded) (`:441-457`).
10. **Build** (`task_agent.py:459-487`), skipped when `ENVIRONMENT=test`: npm install with a hash stamp and shared cache under semaphore(2), then `run_build_loop` (`build_loop.py:91-128`). Each round runs `npx tsc --noEmit` + `npm run build`. The last 3,000 chars of errors go to the LLM, which returns JSON find/replace patches applied with `str.replace(…,1)`. The loop stops after 3 rounds or when a round applies 0 patches.
11. **Gate 2, preview** (`domain_assembler.run_gate2_preview`, `:524-592`):
    - Playwright screenshot of `output_dir/frontend/dist` (rebuilding there if absent; `preview.py:15-75`).
    - Autonomous mode: `vlm_rubric_critique` (5-dimension rubric, `call_vision`; `preview.py:84-119`) → `apply_gate2_revisions` × 2 rounds.
    - Human mode: a DecisionEngine `portal_preview_approval`; the reply text becomes revision instructions. `apply_gate2_revisions` rewrites every `pages/*.tsx` + DomainWidget + Layout via `_generate_file(task_type="code_refinement")` (`preview.py:122-171`).
12. **Return**: `confidence = 0.6·build_ok + 0.3·(tsc_errors==0) + 0.1·(1-template_debt)` (`task_agent.py:503-507`). `success = build_success`. `output_path = project_dir/frontend`.

### 3.3 Cloud console (`build_type=cloud_platform`)

`cloud_console_generator.py:40-81` writes a JSX app: react-router-dom, recharts, inline dark styles. Its pages call `/api/platform/stats|events`, `/api/services/{name}/launch` (polling `/api/resources/{id}/status`), `/api/{type}s`, `ws /ws/resources`, `/api/billing/current|invoice/current` and `/api/settings/api-keys`, all with `localStorage['access_token']` (`cloud_console_pages.py`). These endpoints presumably come from p19_service_catalog (not verified here). The output is not copied to `project/frontend` and not built.

### 3.4 Alternative targets: what each emits

| Target | Output dir | Emits | Auth | API paths |
|---|---|---|---|---|
| p05b Expo RN | `<p05b_mobile>/mobile/` | package.json (Expo 50, RN 0.73, react-navigation, react-query, axios, secure-store), app.json, App.tsx, `src/api/client.ts`, LoginScreen, `<Entity>ListScreen` per entity, AppNavigator (`rn_generator.py:260-285`) | JWT in SecureStore `access_token` | `${API_BASE}/api/{table}` (`:90,173`) |
| p05c Electron | `<p05c_desktop>/desktop/` | main.js (spawns `python -m uvicorn main:app` from resources/backend when packaged), preload (`getApiBase` IPC), package.json, electron-builder.yml (bundles `../backend/**/*.py`), vite.config, `src/index.html`, main.jsx, App.jsx, `<Entity>View.jsx` CRUD (`electron_generator.py:340-367`) | reads `localStorage['token']`; nothing ever sets it (no login UI) | `${apiBase}/{table}s`, PUT update |
| p05d Click | `<p05d_cli>/cli/` | pyproject (click/httpx/rich/keyring), config.py (keyring token + API URL), cli.py, `commands/{auth,config,<entity>}.py` (list/get/create/update/delete, `--json`, `--interactive`) | `auth login` → keyring | `{API}/auth/login`, `/auth/me`, `/{table}s`, PUT |
| p05d Cobra | `<p05d_cli>/cli/` | main.go, go.mod, cmd/root.go, `cmd/<entity>.go` (list/create only, no auth) | none | `{api}/{table}s` |
| p05e Knative | `<p05e_serverless>/serverless/<table>-<event>/` ×3 per entity | knative-service.yaml (scale-to-zero, secrets), broker-trigger.yaml (filter `com.<slug>.<entity>.<event>`), Dockerfile, handler.py (FastAPI `/invoke`, `/healthz`) or main.go, requirements | none | POST `{API_BASE}/{entity}s/events` |
| p05e AWS SAM | `<p05e_serverless>/serverless/aws/` | template.yaml (API GW, MainApp Mangum proxy, ≤8 per-entity functions, deps layer, `Auth: NONE`, CORS `*`), `src/handler.py` (Mangum, `from main import app`), `src/<name>_handler.py` (raw SQLAlchemy CRUD), requirements ×2, samconfig.toml, Makefile, README (`p05e_serverless/task_agent.py:56-117`) | none | `/{name}s`, `/{name}s/{id}` |

All alt targets read `input_data["domain_ir"]` (a dict) rather than `domain_ir_path`. In the pipeline, s02 lists `domain_ir` as an output (`stages/s02_architecture/supervisor.py:19,61`). With no entities, every target falls back to a single `item` entity.

---

## 4. Control flow and data flow

```
s02 (domain_ir_path, domain_ir, architecture_json) ─┐
s03/p04 backend (api_routes_path → route_map, backend_output_path → models.py) ─┤
p04_uiux_design (designer_spec, design_tokens, css_custom_properties, ui_pages) ─┤──► s04_frontend.run_task
s01 intake (user_personas, has_customer_portal, app_brand, realtime_features,   ─┘        │
           build_profile, raw_input, build_types)                                         ▼
                                                    p05_frontend.task_agent.run (always)
                                                    ├─ cloud_platform? → cloud console (JSX), return
                                                    ├─ entities ← IR | arch | models.py | data.entities | items
                                                    ├─ scaffold (templates) → output_dir/frontend
                                                    ├─ pages: LLM (llm_page_writer) → fallback template
                                                    ├─ domain pages + CommandPalette (regex patch App/Layout)
                                                    ├─ DomainWidget (LLM, broken) / portal Home (LLM)
                                                    ├─ Gate 3 (DecisionEngine, result unused)
                                                    ├─ copytree → project/frontend (only if absent)
                                                    ├─ npm install + build_loop (LLM patches) ON project/frontend
                                                    └─ Gate 2 screenshot/VLM/revisions ON output_dir/frontend
                                                    ▼
                                         then p05b/c/d/e conditionally (also re-run by s12)
```

- **Inputs actually consumed by p05**: `build_profile`, `domain_ir_path`, `p02_architecture_path`/`architecture_json`/`project_dir`, `api_routes_path`, `backend_output_path`/`p04_backend_path`/`backend_main_py`, `entities`/`architecture.entities`, `designer_spec.design.*`, `design_brief.color_scheme.primary`, `user_personas`, `has_customer_portal`, `has_landing_page`, `app_brand`, `app_tagline`, `realtime_features`, `build_types`, `raw_input`, `project_name`, `domain`, `autonomous_mode`/`decision_mode`/env `AUTONOMOUS_MODE`, `org_id`, `services` (cloud), plus nginx `container_name`/`app_port`.
- **p04_uiux_design** writes `design_tokens`, `css_custom_properties` and `ui_pages` (`phases/p04_uiux_design/task_agent.py:104-110`). **p05 reads none of these three.** It only reads `designer_spec`, and uses its own `design_system.py` tokens for LLM prompts.
- **Outputs**:
  - `TaskResult.output_path = <project>/frontend`. s04 republishes it as `frontend_output_path` (`stages/s04_frontend/supervisor.py:116-122`), and s06 testing consumes that (`stages/s06_testing/supervisor.py:10,78`).
  - Metadata comes from `frontend_meta.json`. `component_count` is never set, so s04 reports 0 (`supervisor.py:240`).
  - Files: `<project>/p05_frontend/frontend/**`, `<project>/frontend/**` (first-run copy), `<project>/docker-compose.yml`, `<project>/p05_frontend/frontend_meta.json`, `customer_portal_preview.png`.
  - **run_app** prefers `<project>/p05_frontend/frontend` over `<project>/frontend` (`core/run_app/process_manager.py:152-158`; preview entry serves `p05_frontend/frontend/dist`, `core/run_app/process_manager_helpers.py:306`). That is the copy the build loop did **not** patch (§7). run_app rewrites the vite `base` and `.env` to `/app-preview` (`process_manager.py:166-180`).
  - Events: `PhaseApprovalRequired` (gate_3, gate_2) via `core.pipeline_state.publish_event`. The screenshot URL is `/api/artifacts/{run_id}/p05_frontend/customer_portal_preview.png` (`domain_assembler.py:579-582`).
  - `accumulated_context["governor_report_p05"]`.

---

## 5. Plane mapping

| Plane | What lives here |
|---|---|
| **SDLC (codegen)** | Entire React emitter. LLM page writers. IR → types/Zod/forms. Domain pages. Alt targets. Build loop (compile → LLM patch). |
| **STLC (testing)** | Emits vitest config + 2 smoke tests (`code_writer.py:2195-2269`; the login test likely fails without a router). `gate.py` tsc + FK schema-contract check (pipeline-dead). `build_loop` tsc/vite as a compile gate. Playwright screenshot + VLM rubric (visual QA). No E2E, a11y or contract tests generated here. |
| **SRE / ops** | nginx.conf gzip/caching/SPA, Dockerfile HEALTHCHECK, compose healthcheck (`code_writer.py:539-613,3927-3969`). npm concurrency semaphore + node_modules hash cache (`npm_runner.py`). 25-min phase watchdog (`task_agent.py:132`, applied in places). Knative autoscaling annotations. SAM X-Ray `Tracing: Active`. |
| **Security** | Client-side route guards only (JWT presence; dual-portal role decoded client-side, `code_writer.py:1162-1206`). RoleGuard (generator DEAD). 401 auto-logout. nginx/`_headers` security headers (X-Frame-Options, nosniff, Referrer-Policy; **no CSP/HSTS**). JWT in localStorage. SSE/WS pass the token in the query string. **Demo credentials baked into login pages.** Compose `SECRET_KEY` default `changeme`. SAM `Auth: NONE` + CORS `*` + SQL built from request-body keys (`lambda_generator.py:318-324`, SQL-injection vector). CLI stores the token in keyring (good). |
| **Compliance** | none (no consent/PII/audit artifacts; `index.html` sets `robots index,follow`). |
| **Deployment** | Frontend Dockerfile (node build → nginx), root docker-compose, CDN `_headers`, Electron builder, Expo app.json, Knative manifests, SAM template/samconfig/Makefile. Hard-coded `/app-preview` base and basepath tie the bundle to the AetherOS preview host (§7). |
| **Admin control** | Gate 3 admin-feature approval and Gate 2 preview approval via `core.decisions.decision_engine` (human-in-loop; skipped in autonomous mode). Dual-portal generated `/admin` area. Cloud console Settings/API keys. |
| **API management** | Generated axios client + per-entity API objects from p04's `api_routes.json` route map (`scaffold.py:121-154`). `gate.py` FK endpoint vs routes check (pipeline-dead). Vite and nginx `/api` prefix-strip proxies. SAM API Gateway. |
| **Observability / learning** | `frontend_meta.json`: template_debt_pct, model_used, degraded (`task_agent.py:441-457`). Governor violation report. Golden-example retrieval + KG/RAG for DomainWidget (`helpers.py:84-145`). s04 `record_stage_output`. |
| **Design / UX** | `design_system.py` tokens, `prompts.py` palettes/themes/skeleton/transition CSS, per-domain tailwind palettes, dark mode, framer-motion, landing/storefront/portal templates. |

---

## 6. Interfaces and dependencies

**Inbound callers**:
- `stages/s04_frontend/supervisor.py:106-213` imports `aether_os.phases.p05*.task_agent` and calls `run(phase_input, memory_ctx, output_dir)`.
- `stages/s12_specialist/supervisor.py:219-220` does the same for p05b-e.
- `phases/p05_frontend/__init__.py` exports `FrontendSupervisor` (unused by stages).
- Tests: `tests/test_phases_later.py:30-99` (arch reader, full run, gate), `tests/test_l6_l8_phases.py` (Knative, cloud console mocks).

**Outbound (core)**:

| Dependency | Used for | Site |
|---|---|---|
| `core.llm.client.get_llm_client().call(prompt, task_type, max_tokens)` | page/dashboard/home (`code_generation`, 4-6K tok, 120 s), build fix (2K, 60 s), widget (`ui_component`), revisions (`code_refinement`) | `llm_page_writer.py:104,171,255`; `build_loop.py:79`; `helpers.py:77,190` |
| `get_llm_client().call_vision(prompt, img_bytes, task_type="ui_critique")` | VLM rubric | `preview.py:108-112` |
| `core.domain_ir` (`DomainIR`, `AetherType`, `TS_TYPE_MAP`, `ZOD_TYPE_MAP`) | IR load / typing | `task_agent.py:14`, `ir_generators.py:16` |
| `core.decisions.decision_engine` (`Decision`, `request_approval`, `await_decision`) | Gates 2/3 | `domain_assembler.py:19,494-508,568-588` |
| `core.pipeline_state.publish_event`, `orchestrator.events.ACTIVE_RUN_ID` | SSE approval events | `domain_assembler.py:21-22` |
| `core.projects.get_project_manager().get_output_dir` | output dirs | `supervisor_agent.py:14`; s04 `:319` |
| `core.architecture_governor.ArchitectureGovernor` | phantom entity check | `governor_integration.py:21-25` |
| `core.llm.retrieval_ranker`, `core.llm.context_compressor`, `core.learning.golden_retriever` | RAG + few-shot | `helpers.py:89-93,123-128` |
| `phases.utils.memory_hint` | memory hint into widget prompt | `task_agent.py:23,230` |
| `phases.patterns.frontend_patterns_c/d/e` | Feed/Followers, DeviceFleet/SensorChart, ApprovalQueue/FlagAdmin TSX constants | `domain_pages.py:171-216` |
| External processes | `npm`, `npx tsc`, `vite`, `python3 -m playwright`, `python3 -m http.server` | `build_loop.py`, `npm_runner.py`, `preview.py`, `task_agent.py:470` |

**Env vars**: `ENVIRONMENT=test` (skips LLM and build), `AUTONOMOUS_MODE`, `PRIMARY_LLM` (sets the `degraded` flag only).

**Generated-code contracts with the backend**:
- `/auth/login` JSON `{email,password}` → `{access_token, refresh_token?}`, with an optional `role` claim in the JWT.
- List endpoints return either an array or `{items,total,page,page_size}`.
- Update is PATCH (web/IR) but PUT (CLI/Electron/SAM).
- `/stats` returns `total_<table>` (IR dashboard). `/carts` is called by the storefront layout (that layout is DEAD).

---

## 7. Reality check

**A. Compile blockers in the deterministic baseline.** These are by inspection; nothing was built in this mapping. Each one is either always emitted or emitted on common paths.
1. `NotFoundPage.tsx` imports `{ Link } from 'react-router-dom'` (`code_writer.py:2332`). react-router-dom is absent from package.json (`:55-76`), and NotFoundPage is always written and imported by App.tsx (`:1052,1157`).
2. Template entity pages (non-IR fallback) import `../components/Pagination`, `../components/Skeleton` and `../components/RoleGuard` (`code_writer.py:3544-3546`). Their generators `_generate_pagination/_generate_skeleton/_generate_role_guard` (`:2356,2436,2497`) have **no alias and no caller**: DEAD. The ui `Skeleton.tsx` lives in `components/ui/`, not `components/`.
3. All 3 LoginPage variants do `const { access_token, refresh_token } = await authApi.login(...)` (`:2615,2707,2814`) while `authApi.login` is typed `post<{ access_token: string }>` (`:978`). That is TS2339 under `strict`.
4. `TasksKanbanPage` imports `tasksApi` (`domain_pages.py:227` → `code_writer.py:5231`). It is written for every `saas` (the **default** domain), crm, hrm and project_management app, whether or not a `tasks` entity exists. The Calendar has the same problem with `appointmentsApi`/`eventsApi` (`domain_pages.py:238-240`).
5. CommandPalette derives api names from page *file stems* lowercased (`domain_pages.py:259-263`): `OrderItemPage` → `orderitemApi`, and it even includes `TasksKanbanPage` → `taskskanbanApi`. api.ts exports `orderItemsApi` from table names (`code_writer.py:986`). The import is added to App.tsx (`domain_pages.py:119-124`), but the tag is never rendered because App.tsx has no `<RouterProvider>` (that lives in main.tsx) (`domain_pages.py:126-136`). Result: a broken import and a dead feature.
6. In **dual** layout mode, `_patch_app_tsx` emits `getParentRoute: () => layoutRoute` (`domain_pages.py:43`), but the dual App.tsx defines no `layoutRoute` (`code_writer.py:1162-1206`). Dual is the default layout mode, so this fires whenever a domain/kanban/calendar page is added.

Net effect: the stage depends on `build_loop`'s LLM patching. That is 3 rounds, 2,000 output tokens, and 3,000 chars of error context (`build_loop.py:20-27,79`). If patching fails, `success=False` and the s04 gate fails (`stages/s04_frontend/supervisor.py:300-304`).

**B. Runtime and logic bugs.**
7. **Token key mismatch.**
   - `auth.ts` uses `auth_token` (`code_writer.py:837`).
   - The LLM entity-page prompt mandates `localStorage.getItem('token')` (`llm_page_writer.py:243`). The LLM pages use raw `fetch` and bypass the axios client, so they send no JWT and get no 401 redirect.
   - `useSSE`, `useWebSocket` and `useRealtimeStream` also read `'token'` (`code_writer.py:3321,3375`; `helpers.py:574`).
   - The cloud console reads `access_token`. Electron reads `token` and never sets it.
8. **Double `/api` prefix on template FK dropdowns.** `fkEndpoint = '/api/{plural}'` (`code_writer.py:3491`; also IR refs `domain_assembler.py:430`) is fetched through `apiClient`, whose baseURL already ends in `/api` (`:949-951`), giving `/api/api/categories`. `gate.py` strips `/api` when comparing (`gate.py:130`), so it would not catch this even if it ran.
9. **`get_llm_client` is never imported in `helpers.py`** (used at `:77,190`; no import anywhere in the file).
   - `_generate_domain_component` raises `NameError` outside its try. The caller swallows it at debug level (`domain_assembler.py:261-262`), so **DomainWidget is never generated**.
   - `_generate_file` raises too, so `apply_gate2_revisions` logs a warning per file (`preview.py:170-171`). **Autonomous VLM critique and human Gate-2 feedback never change any file**, yet the VLM calls still cost tokens.
10. `domain_assembler.py:427` uses `_AT.FK`. The module imports `AetherType`, not `_AT`. The branch is only reachable when the IR has no entities, so it is effectively dead plus a latent NameError.
11. `domain_assembler.py:512` uses `_json.loads` (undefined, since the module imports `json`). A JSON-array human answer at Gate 3 is silently discarded.
12. **Gate 3's result is unused.** `admin_features` is returned (`task_agent.py:422-427`) and never read. The human approval has no effect on output.
13. **Divergent frontend copies.**
    - copytree to `project/frontend` happens only `if not exists` (`task_agent.py:434-438`). On re-runs the build sees a stale copy.
    - `build_loop` patches `project/frontend` (`:461,481`), while Gate 2 screenshots and revises `output_dir/frontend` (`:491-501`), rebuilding a second `dist` there (`preview.py:25-31`).
    - run_app serves `p05_frontend/frontend` first (`core/run_app/process_manager.py:152-158`), i.e. the **unpatched** copy.
14. **`/app-preview` hard-coded.** vite `base:'/app-preview/'` (`code_writer.py:131`) and router `basepath:'/app-preview'` (`:1089,1227`) break the generated standalone Docker/nginx deployment, which serves at `/` (`:593-613`). The 401 handler does `location.replace('/login')` without the basepath (`:968`), as do the `<a href="/...">` links in the domain dashboard and admin layout (`:4840`, `:1281`).
15. `_write_with_guard` never overwrites (`helpers.py:53-54`). Re-runs keep stale scaffold, and the root `docker-compose.yml` from p05 won't replace or merge a pre-existing one.
16. **Customer portal pages are never routed.** `pages/customer/Home.tsx` and `AboutPage.tsx` (`helpers.py:349,367`; `task_agent.py:399`) get no route in either App.tsx generator. The LLM portal-home call (120 s) is therefore wasted.
17. The template DomainWidget fallback is a stub (`return null`, `helpers.py:216`). The `DOMAIN_FALLBACK_WIDGETS` table is looked up (`:117`) but never returned. `.jsx` imported into strict TS without `allowJs` would also error (TS7016) if the widget ever succeeded.
18. `_sse_import` uses `{{ }}` in a non-f-string (`code_writer.py:3526`), which would emit literal `import {{ useSSE }}`. It is latent: `realtime_features` is never passed (`domain_assembler.py:453`), and there is no `useSSE.ts` writer call (`_generate_use_sse_hook` aliased only, `:5807`), so the realtime path for entity pages is DEAD.
19. WS reconnect "exponential back-off" is a constant 8 s (`code_writer.py:3398`).
20. IR FK `ref_table` uses naive `+ "s"` (`ir_generators.py:66-69,338-340`), e.g. `category` → `categorys`. The template path uses `pluralise` (`scaffold.py:351-362`). The IR dashboard links are `/{table}` paths with underscores→dashes, but stat keys are `total_{table}` from `/stats` (`ir_generators.py:155`), so the backend contract is unverified.
21. `api.ts` type names come from `to_type_name(table)` (`code_writer.py:937-939`), while IR `types/index.ts` uses `entity.name` (`ir_generators.py:218`). Irregular plurals (e.g. people→Person) cause import errors.
22. The non-IR domain dashboard has no `DOMAIN_WIDGET_SLOT` and hard-codes KPI entities (`patients`, `users`, `subscriptions`…) plus mock `TREND_DATA` (`code_writer.py:4772-4800,4872-4880`). In practice it shows fake charts.
23. The cloud console sidebar links to `/services/{name}` with no matching `<Route>` (`cloud_console_app.py:93-96,191-197`). The Settings "Save Notifications" button has no handler (`cloud_console_pages.py:543-545`). The console output never reaches `project/frontend`, and the dead `gate.py` would flag missing `App.tsx`/`main.tsx`/TanStack deps.
24. Duplicate dispatch: alt targets run in s04 **and** s12, writing to the same per-phase dir, and the two disagree on `event_driven` (s04 `:64-66` vs s12 `:113`).

**C. Alternative-target defects (STUB/HOLLOW)**:
- **Mobile**: list items navigate to `'{Pascal}Detail'` (`rn_generator.py:187`), but no Detail screens are emitted and none are registered in the navigator. The `use<Entity>` hooks in the docstring (`:20`) are never written. `FlatList data={data}` breaks on paginated `{items}` responses. "Home" is just the first entity's list.
- **Desktop**:
  - `index.html` is written to `src/` (`electron_generator.py:357`) while Vite's root is the project dir, so `vite`/`vite build` can't find an entry.
  - `spawn(..., ['--port', API_PORT])` passes a number (`:53`). Node requires string args.
  - `(await r.json()).items ?? await r.json()` reads the body twice (`:293`).
  - URL `/{table}s` has no `/api` and double-pluralises.
  - There is no login.
- **CLI**:
  - The generated `config.py` uses an undefined `logger` in `reset_config` (`cli_generator.py:99,103`).
  - Paths are `/{table}s` with no `/api` (`cli_templates.py:247`).
  - The Go create body is built inside a raw backtick string with escaped quotes, producing invalid JSON (`cli_generator.py:265,298`).
  - Go has no auth and no get/update/delete.
  - Hatchling flat-module packaging (`[project.scripts] slug="cli:cli"`) is unverified.
- **Knative**:
  - The Broker delivers to the service root `/`, but the handler only serves `POST /invoke` (`serverless_generator.py:109`), so events would hit 404/405.
  - Underscored table names produce invalid k8s DNS names (`:28,353`).
  - The Go Dockerfile copies a `go.mod/go.sum` that is never generated (`:308`).
  - It targets an unverified backend endpoint `/{entity}s/events`.
  - The image registry is a placeholder.
- **AWS SAM**:
  - `gen_sam_template` output is **invalid YAML**. The outer `textwrap.dedent` margin collapses to 0 because the inserted entity blocks are at column 0, so the body stays indented 8 spaces while `<Entity>Function:` starts at column 0. Verified by executing it: `'...Method: ANY\n\nOrderFunction:\n  Type: ...'` (`lambda_generator.py:46-98,100-193`).
  - The template's `Handler: {name}_handler` keeps the entity's case, but the file is written lower-cased (`p05e_serverless/task_agent.py:88`), so `Order_handler` ≠ `order_handler.py`.
  - `src/handler.py` imports `main.app`, which is never copied into `src/`.
  - Per-entity UPDATE interpolates request-body keys into SQL (SQL injection).
  - `Auth: NONE`, CORS `*`.

**D. File-size rule.** Only `code_writer.py` (5,830, pre-approved) exceeds 600 lines. Near the limit: `helpers.py` 597, `domain_assembler.py` 592, `lambda_generator.py` 585, `cloud_console_pages.py` 550.

**E. Dead or duplicated code.**
- DEAD:
  - Supervisors (5 files) and `gate.py`, in the pipeline.
  - `npm_runner.run_npm_build`.
  - `_generate_layout` (incl. the premium storefront layout, `code_writer.py:1534-1852`) and `_generate_dashboard` (`:2878-3019`): aliased and imported into task_agent, never called.
  - `_generate_page_with_motion`, `_generate_use_sse_hook`, `_generate_pagination/_skeleton/_role_guard`.
  - `ir_generators.generate_ir_dashboard_stats`.
  - `prompts.get_domain_color_hint`, `ALL_USED_ICONS`.
  - `llm_page_writer`'s ImportError fallback for `design_system` (the module exists; the comment at `:20` is stale).
  - task_agent's unused imports (`DOMAIN_*`, `generate_layout`, `generate_dashboard`, `run_npm_build`…).
- Duplicated:
  - `THEME_CSS/SPEED_MS/TRANSITION_CSS/SKELETON_CSS` are imported from prompts and then redefined in `code_writer.py:636-739`.
  - `DOMAIN_COLOR_HINTS` appears in both `helpers.py:28-48` and `prompts.py:186-207`.
  - Customer-keyword tuples are repeated (`code_writer.py:1105-1109,1302-1306`).
  - Hero gradients are repeated.

---

## 8. Open questions

1. Does the build loop in practice fix A1-A6? Run telemetry (`frontend_meta.json`, the s04 `record_stage_output` quality scores) would show the real `success`/`tsc_errors` rates. Does a later stage (s07 healing) patch the frontend again, and which copy does it patch?
2. Which copy is canonical downstream: `<project>/frontend` (TaskResult/s06) or `<project>/p05_frontend/frontend` (run_app, Gate 2)? Is the divergence intentional?
3. Does p04's generated backend return `refresh_token`, a `role` JWT claim, `/stats` with `total_<table>`, `{items,total}` pagination, and accept PATCH plus JSON (not OAuth2 form) at `/auth/login`? (Cross-check with section 03.)
4. Is `input_data["domain_ir"]` (a dict) actually populated by s02 in production? Alt targets depend on it; only tests set it explicitly. Otherwise every alt target emits a single `item` entity.
5. Why are p05b-e dispatched in both s04 and s12? Which one is intended to own them?
6. Should p05 consume p04_uiux_design's `design_tokens`/`css_custom_properties`/`ui_pages` (currently ignored)?
7. Are cloud-console endpoints (`/api/platform/*`, `/api/services/*/launch`, `/api/billing/*`, `/ws/resources`) provided by p19_service_catalog? (Out of scope here.)
8. Is the `/app-preview` base expected to be rewritten for production delivery (s09/s11), or are delivered Docker images shipped broken?
