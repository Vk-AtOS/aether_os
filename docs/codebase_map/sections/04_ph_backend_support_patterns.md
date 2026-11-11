# 04_ph_backend_support_patterns — Backend support phases (p04, p04b, p04c) + pattern library
Scope: phases/p04_backend, phases/p04b_business_logic, phases/p04c_integration_codegen, phases/patterns · 44 .py files · 9,517 LOC · Commit 052a101 · Mapped 2026-11-08

Every file was read in full. Claims were checked by grep across the repo, by running `ast.parse` on every `*_CODE` template string, and by import probes with `.venv/bin/python`.

## 1. Summary

- **What it is.** The backend stage `s03_backend` (`stages/s03_backend/supervisor.py`) runs four parts in order:
  - `p04_backend`: a router. For Python it calls p04a to generate FastAPI code, then UI/UX design. For Go and TypeScript it uses its own deterministic generators.
  - `p04b_business_logic`: writes the workflow engine and business rules (2 LLM calls with template fallbacks), plus email, Stripe and S3 service scaffolds.
  - `p04c_integration_codegen`: one client per integration. Named templates cover Stripe, SendGrid, Twilio, OpenAI/Anthropic and RAG. Unknown integrations get one LLM call each, with a stub fallback.
  - `phases/patterns`: a library of FastAPI routers and React pages kept as Python string templates. Two independent selection paths inject it.
- **Stage-level only.** The p04/p04b/p04c `supervisor_agent.py` and `gate.py` files are **not in the phase registry**:
  - `orchestrator/phase_sequence.py:111` registers only `s03_backend`.
  - s03 calls each `task_agent.run()` directly (`stages/s03_backend/supervisor.py:236-345`).
  - So all six supervisor/gate files are dead in the active pipeline.
- **CRITICAL: p04_backend cannot be imported at HEAD.**
  - `phases/p04_backend/task_agent.py:17` imports `aether_os.phases.p04b_uiux_design`, which does not exist. The directory is `phases/p04_uiux_design`.
  - Verified: `.venv/bin/python -c "import aether_os.phases.p04_backend.task_agent"` gives `ModuleNotFoundError`.
  - s03 catches this (`stages/s03_backend/supervisor.py:282`) and returns `success=False` with no `backend_output_path`, so the s03 gate fails (`:198-205`).
  - Net effect: no backend is generated through the registered path at HEAD.
  - Introduced by commit `0686b19`, "fix(A2): move function-scoped imports to module level". The same commit left `_os` undefined (`task_agent.py:129,164`).
- **Two pattern templates are syntactically broken.** `ast.parse` fails on both:
  - `MULTI_TENANT_CODE` (template line 29: an import block was mangled by commit `d81e33c`, the A2 first pass).
  - `AGENTIC_AI_CODE` (template line 244: `"\n".join` inside a `'''` string becomes a real newline).
  - p04a's pattern injector writes them anyway, as `multi_tenant.py` and `agent.py`. Neither is ever imported by `main.py`.
- **Pattern injection is two uncoordinated systems:**
  - (A) `p04a_backend_codegen/pattern_injector.py`: keyword match on `raw_input` and `build_types`; writes 8 patterns as flat `src/*.py`. Only websocket, stripe, marketplace and erp are mounted in `main.py` (`templates_main.py:487-516`).
  - (B) `orchestrator/phase_hooks.py:317-342`: `PatternSelector` substring-matches the domain IR after s03. Its target path `project_dir/p04_backend/...` does not match where s03 writes (`project_dir/s03_backend/p04_backend/...`), so files land in orphan dirs.
  - The substring triggers over-fire. Verified: an IR containing "Profile delivery news" selects websocket, file_upload and social_graph.
- **Security of generated code is weak in several patterns:**
  - Stripe router: refund, cancel, invoices, usage and subscription have no auth; the webhook upgrades every user with a NULL customer ID.
  - ERP approvals: no approver-role check, so self-approval is possible.
  - RBAC `owner_or_role` trusts a client-supplied `resource_owner_id`.
  - Agent `/run` has no auth and exposes a `write_file` tool.
  - Uploads: download and delete have no auth.
  - WebSocket broadcast uses HS256 with `SECRET_KEY` defaulting to `""`.
- **FE↔BE contracts do not match.** The social, IoT and ERP frontend pages (`frontend_patterns_c/d/e`) call routes and response shapes the backend pattern routers do not provide.

## 2. Coverage table

| File | LOC | Purpose | Status |
|---|---|---|---|
| p04_backend/__init__.py | 3 | exports BackendSupervisor | DEAD (registry uses s03) |
| p04_backend/supervisor_agent.py | 18 | PhaseBase wrapper → task_agent.run + gate | DEAD (not in phase_sequence; s03 bypasses) |
| p04_backend/gate.py | 121 | ast syntax check, main.py/FastAPI check, api_routes.json check | DEAD (only via supervisor) |
| p04_backend/task_agent.py | 426 | language router; Python → p04a + route extraction + smoke test + governor + p04_uiux | BROKEN (import error :17; `_os` NameError :129). LLM-DRIVEN repair: `_smoke_repair` → `client.call(task_type="code_fix", max_tokens=4000)` :71 |
| p04_backend/go_generator.py | 474 | Go/Gin+GORM+zerolog+Prometheus monolith/multiservice | TEMPLATE (has bugs, §7) |
| p04_backend/go_grpc_generator.py | 193 | .proto + Go gRPC server for grpc services | TEMPLATE/STUB (RPC bodies return empty, :103-125) |
| p04_backend/node_generator.py | 396 | TS/Fastify+drizzle+zod+vitest | TEMPLATE (broken SQL, placeholder tests) |
| p04b_business_logic/__init__.py | 0 | — | — |
| p04b_business_logic/supervisor_agent.py | 24 | PhaseBase wrapper, passes phase_input to gate | DEAD |
| p04b_business_logic/gate.py | 90 | upstream-confidence flags + service-file ast check | DEAD; flags it writes (`p04b_gate_flags`) are read by nobody |
| p04b_business_logic/task_agent.py | 395 | workflow SMs, service scaffolds, email templates, 2 LLM calls, main.py import patching | LLM-DRIVEN (prompt_a :220 / prompt_b :273, `llm.call(task_type="code_generation", max_tokens=12000)` :244,:296) + TEMPLATE fallback |
| p04b_business_logic/helpers.py | 278 | fallback WorkflowEngine/BusinessRules templates, HTML email wrapper, DomainIR recovery | TEMPLATE + LLM-DRIVEN recovery (reuses p02b `_PASS1_PROMPT`/`_PASS4_PROMPT`, `llm.call(task_type="analysis", max_tokens=4096)` :248) |
| p04b_business_logic/logic_generators.py | 160 | per-workflow StateMachine, EmailService, StripeService, S3Service strings | TEMPLATE (EmailService is HOLLOW: prints, no HTML :75-86) |
| p04c_integration_codegen/__init__.py | 0 | — | — |
| p04c_integration_codegen/supervisor_agent.py | 22 | PhaseBase wrapper (output_dir from `project_dir` or `/tmp`) | DEAD |
| p04c_integration_codegen/gate.py | 25 | client-file name heuristic | DEAD |
| p04c_integration_codegen/task_agent.py | 322 | named template or LLM httpx client per integration; integration_manager.py | REAL orchestration + LLM-DRIVEN (`llm.call(prompt, task_type="code_generation", max_tokens=2500)` :265) + TEMPLATE stub `_fallback_client` |
| p04c/templates/__init__.py | 31 | NAMED_TEMPLATES map | REAL (matching is buggy, §7) |
| p04c/templates/stripe.py | 127 | async StripeClient via run_in_executor | TEMPLATE |
| p04c/templates/sendgrid.py | 103 | async EmailClient (SendGrid SDK) | TEMPLATE |
| p04c/templates/twilio.py | 94 | SMS/WhatsApp client | TEMPLATE |
| p04c/templates/openai_ai.py | 173 | OpenAI/Anthropic unified AIClient | TEMPLATE |
| p04c/templates/rag.py | 156 | ChromaDB or in-memory RAG service | TEMPLATE |
| patterns/__init__.py | 240 | `Pattern` dataclass, 6 factories, `PatternSelector.select/apply_all` | REAL (used by phase_hooks only) |
| patterns/pattern_name_resolver.py | 122 | `models.X` substitution for IoT/Social | REAL but effectively NO-OP (§7) |
| patterns/file_upload.py | 111 | uploads router (disk + in-memory registry) | TEMPLATE; selector path only |
| patterns/rbac.py | 99 | `require_role`, `require_any_role`, `owner_or_role` deps | TEMPLATE; selector path only, never imported by generated code |
| patterns/websocket.py | 126 | ConnectionManager + WS room + JWT broadcast | TEMPLATE; both paths; mounted via p04a |
| patterns/stripe.py | 341 | billing router (checkout, webhook, subscription, cancel, invoices, usage, refund) | TEMPLATE; both paths; mounted via p04a |
| patterns/multi_tenant.py | 414 | Org/OrgMember models, OrgMiddleware, invites | BROKEN TEMPLATE (SyntaxError); p04a path only, never mounted |
| patterns/agentic_ai.py | 529 | ReAct loop, tool registry, SSE, conversations | BROKEN TEMPLATE (SyntaxError); p04a path only, never mounted |
| patterns/marketplace.py | 398 | listings, bids, escrow state machine | TEMPLATE; p04a path; mounted |
| patterns/erp_approval.py | 309 | multi-level purchase-request approvals | TEMPLATE; p04a path; mounted |
| patterns/iot_timeseries.py | 52 | `get_iot_code`, constants | TEMPLATE shim |
| patterns/iot_timeseries_templates.py | 564 | IoT router string (readings, alerts, commands, dashboard) | TEMPLATE; never mounted |
| patterns/social_graph.py | 53 | `get_social_code`, constants | TEMPLATE shim |
| patterns/social_graph_templates.py | 569 | social router string (follow, feed, hashtags, search, notifications, likes) | TEMPLATE; never mounted |
| patterns/frontend_patterns.py | 47 | re-export barrel | DEAD (no importers) |
| patterns/frontend_patterns_a.py | 378 | KanbanBoard, CommandPalette TSX | DEAD |
| patterns/frontend_patterns_b.py | 188 | NotificationCenter TSX | DEAD |
| patterns/frontend_patterns_b2.py | 453 | SettingsPage TSX (5 tabs) | DEAD |
| patterns/frontend_patterns_c.py | 276 | FeedPage, FollowersPage TSX | TEMPLATE, used by `p05_frontend/domain_pages.py:171` |
| patterns/frontend_patterns_d.py | 265 | DeviceFleetPage, SensorChartPage TSX | TEMPLATE, used by `domain_pages.py:188` |
| patterns/frontend_patterns_e.py | 352 | ApprovalQueuePage, FlagAdminPage TSX | TEMPLATE, used by `domain_pages.py:204,213` |

No file is over 600 lines. The largest are `social_graph_templates.py` (569) and `iot_timeseries_templates.py` (564).

## 3. Components

### 3.1 p04_backend — backend language router
- **`run()`** (`task_agent.py:260-426`):
  - Reads `build_profile.backend_lang`. `"go"` goes to `_run_go_backend` (:192) and `"typescript"` to `_run_node_backend` (:238). Anything else is Python.
  - Python, sub-task 1: `p04a_run(phase_input, memory_ctx, output_dir/"backend_codegen")` (:276-278). On success it merges r.metadata into `phase_input.input_data` and sets `backend_output_path` (:281-282).
  - **Route extraction** (:288-346), three regex strategies over `src/main.py` and `src/routers/crud.py`:
    1. Explicit `@app|router.<method>("path")` decorators.
    2. `APIRouter(prefix=...)` expands to 5 CRUD routes.
    3. `include_router` / `generate_crud_router` args.
    - Writes `api_routes.json` and sets `input_data["api_routes_path"]`. The p05 frontend uses this to wire API calls.
  - **Startup smoke test** `_startup_smoke_test` (:85-189): `py_compile` on main.py, then exec of the code above `app = FastAPI` with `DATABASE_URL` pointed at a temp SQLite file. One LLM repair attempt via `_smoke_repair` (:41-82); prompt rules at :58-68.
    - The step-2 env dict uses an undefined `_os`, so it raises NameError. The exception is swallowed at :368 as a debug log. Net: only step 1 actually runs.
  - **ArchitectureGovernor** (:374-395): `from_output_dir(output_dir)` then `generate_report("p04_backend", {models.py, crud.py})`. Results go to `accumulated_context["governor_report"]`.
  - Sub-task 2: UI/UX design (:401-408). The wrong module path means this never runs.
  - Writes `consolidated.json` and returns `success = any_success or bool(results)` (:424). Because of `bool(results)`, a run where every sub-task failed but returned a result still counts as success.
- **go_generator.py:**
  - Pure string templates: go.mod (:37), Prometheus middleware (:62), zerolog (:108), GORM model (:132), Gin CRUD handler (:168), db init with AutoMigrate (:256), main.go with `/health`, `/metrics` and `/api` group (:289), scratch Dockerfile (:353), `.env.example` (:371).
  - `generate_go_multiservice` (:428) writes one service per `service_map.services[]`, filtered by `owns_entities`.
- **go_grpc_generator.py:** proto with CRUD RPCs per entity (:36), `server.go` (:85). The proto↔model mapping is omitted: List returns an empty response (:103-104), Get returns an empty message (:112), Create ignores `req` (:116), Update is a no-op (:124). `register.go`, promised in the docstring, is never generated, so gRPC is never started from main.go.
- **node_generator.py:** package.json/tsconfig (:35,:69), drizzle db (:88), interfaces (:101), Fastify routes using raw `db.execute(sql, params)` (:127), index (:206), zod schemas (:244, never used by routes), vitest (:278), placeholder tests `expect(true).toBe(true)` (:318,324,330).
- **gate.py** (dead): ast-parses every `.py`; checks main.py for `FastAPI`. The "import-level" subprocess is just another `ast.parse` (:79-82), not an import check. Then checks `api_routes.json`. Confidence is 0.93, 0.82 or 0.72, and the gate passes even when main.py is missing (:115-116).

### 3.2 p04b_business_logic
- **Input** (`task_agent.py:47-70`):
  - Reads `domain_ir_path`. If that is missing, `recover_domain_ir` (`helpers.py:221`) re-runs p02b passes 1 and 4 inline via the LLM, falling back to a 1-entity stub IR (:270-278).
  - If `domain_knowledge.domain` is set and the IR has no workflows, it injects domain-pack workflows (:77-97).
- **Workflow state machines** (:100-106): `generate_workflow_sm` (`logic_generators.py:13`) builds a linear transition map from `steps` and writes it to `output_dir/workflows/<entity>_sm.py`.
  - That is the phase output dir, not the app's `src/`, so these files are orphaned.
  - Domain-pack workflows use `states`/`transitions`, not `steps`, so their machines get an empty transition table and every transition raises.
  - The `'placed'` status and admin/staff roles are hardcoded (:36).
- **Target dir:** `backend_src_dir` from input_data, else `output_dir/src` (:111-113).
- **Service scaffolds**, written according to `integration_flags.needs_email`, `needs_payments` and `needs_file_upload`: `email_service.py`, `stripe_service.py`, `s3_service.py` (:116-123).
- **Notifications:** `notifications/email_triggers.py` is always written, as a no-op or a sender to a hardcoded `admin@example.com` (:129-161). Email templates `welcome.html`, `password_reset.html`, `email_verification.html` and one per IR notification go to `src_dir.parent/templates/emails` (:164-203).
- **LLM Call A, workflow engine:** `prompt_a` (:220-242), `llm.call(task_type="code_generation", max_tokens=12000)`. The output must parse with `ast` and contain no relative imports. Fallback: `_FALLBACK_WORKFLOW_ENGINE` (`helpers.py:12-96`), whose `transition()` validates and logs only and never persists (:54-80, HOLLOW).
- **LLM Call B, business rules:** `prompt_b` (:273-294). Fallback: `_FALLBACK_BUSINESS_RULES` (`helpers.py:98-183`): validation, tax, discount and total calculations.
- **main.py patching** (:321-366): inserts absolute imports (`from email_service import EmailService`, etc.) after the last import line. Nothing ever instantiates or mounts them.
- **Output:** `business_logic.json`, confidence fixed at 0.9 (:390-395).

### 3.3 p04c_integration_codegen
- **Input:** `integration_map.integrations` (from p01b) or `p01b_integration_discovery_output` (:161-169). With none, it writes `skipped` and returns confidence 1.0.
- **src dir:** the first that exists of `project_dir/p04a_backend_codegen/src`, `project_dir/p04_backend/backend_codegen/src`, `project_dir/src`; else `output_dir/src` (:183-197). It ignores `backend_src_dir`, which p04b uses.
- **Per integration (cap 8, :210):**
  - A fuzzy name match against `NAMED_TEMPLATES` (`templates/__init__.py:12-22`) picks a deterministic template, written to `services/<file>`.
  - Otherwise: an LLM client with custom exceptions, retries and a singleton (prompt :244-263), ast-validated, falling back to the `_fallback_client` httpx stub (:74-153).
- **Also writes** `services/__init__.py` and `services/integration_manager.py` (star-imports all clients, :289-305).
- **Templates:** all deterministic strings:
  - Stripe: customer, checkout, subscription, cancel, invoice, webhook verify.
  - SendGrid: plain and template email.
  - Twilio: SMS and WhatsApp.
  - AI: OpenAI or Anthropic chat, embed, stream (OpenAI only).
  - RAG: Chroma or in-memory cosine, ingest, search, `chat_with_context`.

### 3.4 Pattern library — selection, resolution, injection

**Path A — p04a keyword injector** (active when p04a runs; outside this scope but drives these patterns):
- `detect_active_patterns(data, raw_input)` (`p04a_backend_codegen/pattern_injector.py:15-74`) matches keywords in `raw_input` plus `build_types`.
- `inject_patterns` (:77-171) writes `src/multi_tenant.py`, `agent.py`, `websocket_router.py`, `billing_router.py`, `marketplace_router.py`, `approval_router.py`, `social_router.py`, `iot_router.py`, and appends to requirements.
- `codegen_orchestrator.py:186-191` sets `_inject_*` flags for 4 of them. `templates_main.patch_main_py` (:444-517) adds try-wrapped `include_router` blocks before `@app.get("/health"`.
- Social, IoT, multi-tenant and agent files are written but never mounted.

**Path B — PatternSelector post-hook** (`orchestrator/phase_hooks.py:317-342`, after s03):
- Builds `entity_map = {name.lower(): name}` from IR entities. `PatternSelector(ir, entity_map).apply_all(project_dir)`.
- `select()` (`patterns/__init__.py:202-229`) flattens IR string values (`_ir_text` :188-200) and substring-matches `Pattern.triggers`.
- **Simple factories:** websocket → `src/routers/ws.py`; file_upload → `src/routers/uploads.py`; stripe → `src/routers/billing.py`; rbac → `src/middleware/rbac.py`.
- **Entity-aware factories:** iot → `src/routers/iot_router.py`; social → `src/routers/social_router.py`. These go through `pattern_name_resolver`.
- `Pattern.inject` (:51-77) picks the first existing of `project_dir/p04_backend/backend_codegen`, `project_dir/p04_backend`, `project_dir/p03_scaffolding`, else `project_dir`. It writes files and dedupes requirements by substring. Nothing mounts these routers.
- Result: `accumulated_context["applied_patterns"]`.

**Name resolution:**
- `generate_iot_pattern` / `generate_social_pattern` (`pattern_name_resolver.py:47,82`) replace `models.<Canonical>` with `models.<IRName>` when `entity_map[role]` differs.
- The template builders also chain `.replace()` with the same canonical names (`iot_timeseries_templates.py:561-564`, `social_graph_templates.py:563-569`).

**What each backend pattern generates** (all FastAPI and async SQLAlchemy):

| Pattern | Routes (prefix) | Models / notes |
|---|---|---|
| websocket | WS `/ws/{room}`, POST `/ws/{room}/broadcast` | in-memory ConnectionManager with asyncio.Lock; JWT via python-jose HS256 |
| file_upload | POST `/uploads/`, GET/DELETE `/uploads/{id}` | blocklist of extensions + content-type allowlist, size cap, in-memory `_registry` (lost on restart) |
| rbac | dependency factories | role ladder viewer<member<manager<admin<superadmin (:38) |
| stripe | `/billing/` checkout, webhook, subscription, cancel, invoices, invoices/{id}, usage, refund | webhook updates `users.plan` via raw SQL; dunning email over smtplib |
| multi_tenant | `/orgs` CRUD, `/{id}/invite`, `/accept-invite` | Organization, OrganizationMember (PG UUID), OrgMiddleware reading `org_id` from JWT (RS256 then HS256 fallback), HS256 invite tokens (48h) |
| agentic_ai | POST `/agent/run` (SSE), conversations list/get/delete | ReAct loop for OpenAI/Anthropic tool calls, max 10 iterations; tools web_search (stub), read_file, write_file (cwd-restricted); AgentConversation JSON model |
| marketplace | `/marketplace/listings`, bids, accept/reject, `/escrow/{id}` fund/release/dispute/resolve | Listing, Bid, Escrow; escrow transition table (:58-72); escrow tracks state only, no money moves |
| erp_approval | `/approvals/requests` CRUD, submit, approve, history, queue | PurchaseRequest, ApprovalRecord; level count from amount thresholds (`APPROVAL_THRESHOLDS` env JSON, :55-71) |
| iot_timeseries | `/iot/readings` (+bulk, X-Device-Key auth), device readings/summary/status, alerts list/ack/resolve, commands queue/pending/ack, dashboard/summary | requires `models.Device/SensorReading/Alert/Command` to exist; paho-mqtt and influxdb requirements are added but never used |
| social_graph | `/social/follow/{id}`, followers, following, feed, trending/hashtags, search/posts, notifications, posts/{id}/like | requires UserProfile, Follow, Post, Hashtag, PostHashtag, Like, Notification; redis and cloudinary requirements unused |

**Frontend patterns:**
- `p05_frontend/domain_pages.write_domain_pages` (:143-) imports `_c` (social: FeedPage, FollowersPage), `_d` (IoT: DeviceFleetPage, SensorChartPage), `_e` (ApprovalQueuePage when build_types has `erp`/`approval`; FlagAdminPage when it has `feature_flags`). These are written to `src/pages/` with routes and nav added.
- `_a` (Kanban, CommandPalette), `_b` (NotificationCenter), `_b2` (SettingsPage) and the barrel `frontend_patterns.py` have no importers. Kanban is produced by `p05_frontend/code_writer.generate_kanban_component` instead.

## 4. Control flow and data flow

```
orchestrator → s03_backend.BackendStageSupervisor.run_task
  ├─ p04_backend.task_agent.run   [ImportError at HEAD → success=False]
  │    ├─ go | typescript → go_generator / go_grpc_generator / node_generator → output_dir/backend|services
  │    └─ python → p04a.run (→ pattern_injector path A) → api_routes.json → smoke test (LLM fix) → governor → p04_uiux (dead path)
  ├─ p04b.task_agent.run   (reads domain_ir_path, integration_flags, backend_src_dir, domain_knowledge, raw_input)
  │    → workflow_engine.py, business_rules.py, *_service.py, notifications/, templates/emails/, patch main.py
  ├─ p04c.task_agent.run   (only if integration_map.integrations non-empty)
  │    → src/services/<client>.py + integration_manager.py
  └─ governor + api_routes + seed_entities → s03_consolidated.json; gate checks backend_output_path
phase_hooks.after_s03 → S11 copytree, api_routes propagation, PatternSelector (path B), BackendAuditCouncil
p05_frontend.domain_pages → frontend_patterns_c/d/e
```

**Data keys:**
- **Read:** `build_profile.{backend_lang,db_primary}`, `domain_ir`, `domain_ir_path`, `service_map`, `project_name`, `integration_flags`, `integration_map`, `domain_knowledge`, `raw_input`, `backend_src_dir`, `project_dir`.
- **Written to `input_data`:** `backend_output_path`, `api_routes_path`, `smoke_test`, `accumulated_context.governor_report`. p04a metadata is merged in too.
- **s03 metadata:** `integration_clients`, `seed_entities`, `design_tokens`.

**Path drift:** `phase_hooks` assumes `project_dir/p04_backend/backend_codegen/src` (:292, :311, :348). s03 writes `project_dir/s03_backend/p04_backend/backend_codegen/src`, because both `PM.get_output_dir(pid, "s03_backend")` and factory `project_dir` resolve to `~/.aether_os/projects/<run_id>` (`core/projects.py:16,68-76`; `orchestrator/factory_pipeline.py:219`). So the S11 merge, the API-route propagation, PatternSelector targeting and the BackendAuditCouncil main.py lookup miss the real output.

## 5. Plane mapping

| Plane | Content in scope |
|---|---|
| SDLC | Core codegen: p04 language router; Go, gRPC and TS generators; p04b business logic; p04c integration clients; pattern library for complex features. LLM is used only for repair (p04), the workflow engine and business rules (p04b), and unknown integrations (p04c). Everything else is deterministic templates. |
| STLC | p04 smoke test (py_compile + exec-import, partly broken); dead gates (ast checks); generated vitest stubs (placeholders); ast validation of LLM output in p04b/p04c. No real tests are generated for pattern routers. |
| SRE | Go: Prometheus `/metrics` + zerolog + `/health`. Node: pino logger + `/health`. Integration clients retry with exponential backoff (p04c `_fallback_client` :126-141). IoT dashboard and alert routes (app-level). No circuit breakers or timeouts beyond httpx's 30s. |
| Compliance | ERP approval audit trail (`ApprovalRecord`), but no segregation of duties. Upload extension blocklist. Email unsubscribe link is a `#` placeholder (`helpers.py:212`). No PII, GDPR or retention handling. |
| Security | RBAC deps (unused); upload validation; Stripe webhook signature verify (`stripe.py:89-101`); RS256-aware multi-tenant decode (broken file); agent file tools with cwd jail. Gaps: §7. Smoke test isolates `DATABASE_URL` so it does not touch the platform DB (`task_agent.py:113-129`). |
| Deployment | Go multi-stage scratch Dockerfile; Node 2-stage Dockerfile; `.env.example` files; go.mod/package.json. No Python Dockerfile here (that is p03/p04a). |
| Admin control | FlagAdminPage (feature-flag toggle, rollout %, ring); `multi_tenant` org admin (broken); marketplace `resolve_escrow` admin-only; ERP approval queue. |
| API management | `api_routes.json` route extraction is the FE↔BE contract; Stripe usage-record metering endpoint; gRPC proto generation; `/api` prefix convention (Go group, Fastify prefix, p04a mounts). |
| Other (AI/RAG) | Agentic AI ReAct pattern, AIClient and RAGService templates for generated apps. |

## 6. Interfaces and dependencies

- **Entrypoints:**
  - `p04_backend.task_agent.run(phase_input, memory_ctx, output_dir) -> TaskResult`; same signature for p04b and p04c.
  - `PatternSelector(domain_ir, entity_map).select() / .apply_all(project_dir) -> {name: [paths]}`.
  - `Pattern.inject(project_dir)`.
  - Generators: `generate_go_project(entities, project_name, output_dir, db_driver, module_name, port)`, `generate_go_multiservice(service_map, entities, project_name, output_dir)`, `generate_grpc_files(svc, entities, dir, module)`, `generate_node_project(entities, project_name, output_dir)`.
  - Templates: `NAMED_TEMPLATES[key] = (fn(output_dir, config) -> str, filename)`.
- **Callers:**
  - `stages/s03_backend/supervisor.py:244,299,334`.
  - `orchestrator/phase_hooks.py:319`.
  - `phases/p04a_backend_codegen/pattern_injector.py:104-163` (path A).
  - `phases/p05_frontend/domain_pages.py:171-216`.
  - tests: `tests/test_go_generator.py`, `test_phases.py`, `test_v2_*.py`.
- **Platform deps:**
  - `aether_os.core.llm.client.get_llm_client().call(prompt, task_type, max_tokens)`.
  - `core.architecture_governor.ArchitectureGovernor`, `core.projects.get_project_manager`, `core.domain_knowledge.loader.load_pack`.
  - `phases.p02b_domain_ir.task_agent` private symbols (`_PASS1_PROMPT`, `_PASS4_PROMPT`, `_extract_json`, `_build_ir_from_passes`), a fragile private coupling.
  - `phases.p04a_backend_codegen.task_agent.run`, `phases.base` (`PhaseBase`, `TaskResult`, `GateOutcome`).
  - `orchestrator.events.emit` (imported, unused).
- **Generated-app runtime deps:**
  - Python: fastapi, sqlalchemy async, python-jose / PyJWT, cryptography, stripe, sendgrid, twilio, openai, anthropic, chromadb, boto3, aiofiles, python-multipart, sse-starlette, websockets, paho-mqtt and influxdb (unused).
  - Go: gin, gorm, zerolog, prometheus, grpc.
  - TS: fastify, drizzle, postgres, zod, pino, vitest.
  - React: @tanstack/react-query, lucide-react, recharts, @radix-ui, shadcn `@/components/ui/*`.
- **Import conventions are inconsistent** across templates: `from auth import` (rbac, iot, social, multi_tenant); `from routers.auth import` (file_upload, marketplace, erp); `src.`-prefixed fallbacks (`stripe.py:114`, p04b `email_triggers` `from src.email_service`); p04b main.py patch uses bare `from email_service`. `current_user` is used as a dict (`current_user["id"]` in marketplace/erp) and as an object (`current_user.id` in social/multi_tenant/agent).

## 7. Reality check

**Broken or failing at HEAD:**
1. `p04_backend/task_agent.py:17` imports the nonexistent `aether_os.phases.p04b_uiux_design` (the real dir is `phases/p04_uiux_design`). The module cannot import, so s03 p04 fails and the s03 gate fails. Introduced by `0686b19`. The function-scoped import at :402 has the same wrong path.
2. `task_agent.py:129,164` uses `_os` after `0686b19` removed `import os as _os`. The NameError skips smoke-test step 2 (swallowed at :368-369).
3. `MULTI_TENANT_CODE` fails `ast.parse` at template line 29. The block at :32-38 is broken (`from sqlalchemy import (` is never closed) and :96-101 has an orphaned `try:`/`except` (commit `d81e33c`). It also hard-imports both `auth` and `src.auth`, so at least one would raise ImportError anyway. `_get_current_user_dep`/`_get_db_dep` (:167-188) are meaningless try/excepts. Calls `await _current_user_dep(request)`, which does not match `get_current_user(token)` signatures.
4. `AGENTIC_AI_CODE` fails `ast.parse`: `"\n".join(sys_msgs)` at `agentic_ai.py:250` emits a literal newline.
5. Path A writes 4 patterns that are never mounted (social, iot, multi_tenant, agent). Path B writes to the wrong base dir and mounts nothing. p04b `output_dir/workflows/*_sm.py` is orphaned.

**Pattern selection and resolution:**
6. PatternSelector triggers are raw substrings over all IR text: "ws" hits "news", "file" hits "profile", "live" hits "delivery", "role" hits nearly every IR with permissions, "post" hits "postgres/postal". This over-injects (verified).
7. The `entity_map` built in `phase_hooks.py:331-334` is `{name.lower(): name}`. Resolver roles are `device`/`reading`/`alert`/`command`/`user`/`post`, so substitution happens only when names already match. Effectively a no-op.
8. Substring replace without word boundaries is unsafe. `models.Post` → X rewrites `models.PostHashtag` when post_hashtag is unmapped (`pattern_name_resolver.py:102-112`). The template builder replaces `models.Post` before `models.PostHashtag` (`social_graph_templates.py:565-567`).
9. `NAMED_TEMPLATES` matching `key in name_lower or name_lower in key` (`p04c/task_agent.py:220-223`) maps any name containing "ai" (Mailchimp, Plaid, Gmail, Mailgun) to `ai_client.py`. Collisions overwrite the same file and duplicate entries in `clients_generated`.

**Generated-code security:**
10. Stripe router: no auth on `/refund`, `/cancel`, `/invoices*`, `/usage`, `/subscription`. The webhook SQL `WHERE stripe_customer_id = :cid OR stripe_customer_id IS NULL` (`stripe.py:118-119`) upgrades every user without a customer ID to `pro`. `async with get_db()` misuses a dependency generator (:116). Open redirect via body `success_url`.
11. ERP: `act_on_request` (`erp_approval.py:254-281`) has no role or level check, so a requester can self-approve every level. get_request, history and queue have no access control. The SUBMITTED state is unused.
12. Marketplace: `reject_bid` (:288-300) has no seller check (IDOR). Escrow "fund" moves no money.
13. RBAC: `owner_or_role` takes `resource_owner_id` as a client query param, which bypasses authorization (`rbac.py:84-91`). The ImportError fallback authenticates any token as role `user` (:33-35).
14. Upload: download and delete have no auth (`file_upload.py:90-110`) despite the docstring. The registry is in-memory.
15. WebSocket: the WS endpoint ignores `token` (no auth, `websocket.py:78`). Broadcast decodes HS256 with `SECRET_KEY` defaulting to `""`, which makes tokens forgeable when unset, and mismatches the RS256 app auth. `except _JWTError` raises NameError if jose is missing.
16. Agent `/run` has no auth (LLM cost abuse) and exposes `write_file` to model tool calls. Prompt injection can overwrite app source inside cwd.
17. Node routes: column names from the request body are interpolated into SQL (`node_generator.py:150-154,181-186`, SQL injection). Placeholders render as `1, 2`, not `$1, $2` (the f-string escaping at :152). drizzle `db.execute(string, params)` and `.rows` do not match the postgres-js API.

**Generator bugs:**
18. Go: the Dockerfile copies `go.sum`, which is never generated (:358), so the build fails. JWT dependency and `JWT_SECRET` are present with no auth middleware. `Delete` returns `c.JSON(204, nil)`. `strconv.Atoi` errors are ignored. task_agent filters gRPC entities with `.title()` (`task_agent.py:215`) while go_generator uses `_to_pascal` (:452), which diverges for snake_case.
19. p04 gate (dead): Go and TS outputs contain no `.py`, so `validate` would fail them with confidence 0 (`gate.py:37-39`).
20. p04b gate (dead): output_path is `business_logic.json`. Its name contains "logic", so it is ast-parsed as a "service file" with 0 functions, and confidence is always 0.6. The `p04b_gate_flags` it writes (:56) are never read.
21. p04b: domain-pack workflows (`states`/`transitions`) are fed to `generate_workflow_sm`, which expects `steps`, producing empty transition maps. `EmailService.send` prints to stdout and sends plain text only (`logic_generators.py:75-86`). The StripeService default key is `"sk_test_placeholder"`.
22. Social router: follows store `follower_id=current_user.id` (user ID) but queries use `my_profile.id` (profile ID) (:59 vs :163). `follower_count` updates use `UserProfile.id == user_id` (:73). `func.greatest` is unsupported on SQLite.

**FE↔BE contract mismatches:**
23. Social: FE `/api/social/feed` expects `Post[]` with `hashtags`, `is_liked`, `author_username`; BE returns `{items,total}` without those fields, so the page crashes on `.map`/`.length`. FE `/api/social/hashtags/trending` vs BE `/social/trending/hashtags`. FE `/api/social/users/{id}/follow|followers|following` vs BE `/social/follow/{id}`, `/social/followers`.
24. IoT: FE `/api/iot/fleet/dashboard` vs BE `/iot/dashboard/summary`, and field names differ (online vs online_count, in_alert vs open_alerts). FE `/api/iot/devices` has no BE route in the pattern. Readings shape differs (timestamp/metric_name vs recorded_at/sensor_type in `{items}`). Hardcoded `/app-preview/` link (`frontend_patterns_d.py:64`).
25. ERP: FE `/api/approvals/pending` and `/{id}/approve|reject` vs BE `/approvals/queue` and `/approvals/requests/{id}/approve` with an `action` body. FE expects `steps`, `current_level`, `request_id`.

**Dead code:** p04, p04b and p04c `supervisor_agent.py` + `gate.py` (registry uses s03); `p04_backend/__init__` export; `frontend_patterns.py`, `_a`, `_b`, `_b2`; `get_iot_code`/`get_social_code` `entity_map` parameter (never called with a map); unused `_global_emit` import (`p04_backend/task_agent.py:24`); `_HTTPX_CLIENT_EXAMPLE` (prompt-only, fine).

**Files over 600 lines:** none. Bare `except:`: none found. Many broad `except Exception` handlers that swallow failures as debug logs (e.g. `task_agent.py:368`, `stripe.py` DB blocks).

## 8. Open questions

1. Does the VPS run code from before `0686b19`? If not, is any backend currently produced in production, and does some other path (e.g. `factory_pipeline` calling p04a directly) bypass `s03_backend`?
2. Is p04's UI/UX sub-task supposed to call `phases/p04_uiux_design`, or was it moved to another stage on purpose?
3. Which injection path is canonical, A (p04a keywords) or B (PatternSelector hook)? Should B write into `s03_backend/p04_backend/backend_codegen/src` and add `include_router`?
4. Is `phase_hooks`' `project_dir/p04_backend` path a leftover from the pre-stage era (p04 as a top-level phase)? It affects S11 merge, the BackendAuditCouncil and api_routes propagation outside this scope.
5. Should the frontend patterns `_a`, `_b`, `_b2` be wired (SettingsPage expects `/api/users/me`, `/api/auth/keys`, `/api/orgs/members`, which no generator here provides) or deleted?
6. Does any test cover `ast.parse` of every `*_CODE` template? Both broken ones would have been caught.
7. Should p04c use `backend_src_dir`, like p04b does, instead of its own candidate list?
