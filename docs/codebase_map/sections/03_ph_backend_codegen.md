# 03_ph_backend_codegen — Backend code generator (phase p04a)
Scope: phases/p04a_backend_codegen · 42 files · 8,570 LOC · Commit 052a101 · Mapped 2026-11-08
Method: every file in scope read in full. Key bugs were confirmed by running the real generators on a sample DomainIR in a scratch dir. No source was modified.

## 1. Summary

- **What it is:** p04a writes the backend of the generated app: one FastAPI + async SQLAlchemy 2 + Pydantic v2 project (`src/main.py, database.py, auth.py, config.py, rate_limiter.py, models.py, schemas.py, seed.py, routers/{auth,crud,stats}.py, services/*`, plus requirements.txt, Dockerfile, .env, Makefile, README, Alembic scaffold).
- **Who calls it:** it is never run as a standalone pipeline phase. `phases/p04_backend/task_agent.py:276-278` calls `p04a.run()` with `output_dir = <stage>/p04_backend/backend_codegen`. s03_backend → p04_backend → p04a.
- **No LLM calls in the live path.** It is fully deterministic (`task_agent.py:1-4, 172-175`: "LLM intentionally excluded: 3-call LLM chain had 30% relative-import failure rate"). All LLM code in scope is **DEAD**: `crud_generator._llm_*`, `crud_generator_seed.generate_llm_seed/get_seed_py`, and all of `prompts.py`.
- **Two generation paths:**
  1. **IR fast-path** (primary). Taken whenever p02b supplied `domain_ir_path`. Runs `ir_generators.py` + `ir_generator_helpers.py`.
  2. **Name-heuristic fallback.** Taken when there is no IR or the IR path fails. Runs `schema_builder._fallback_*` + `crud_generator._fallback_crud_routers` + `crud_generator_seed._fallback_seed`.
- **Fixed parts:** the static templates (`templates.py`, `templates_main.py`) provide the app shell, RS256 JWT auth, CORS, GZip, security headers, request-ID, Prometheus, /health, /ready and Alembic.
- **Add-ons:** pattern injection (websocket/stripe/marketplace/ERP/social/IoT/multi-tenant/agentic), domain-pack pipeline orchestrator stubs, audit, cache and ABAC permission services, and an SSE router.
- **Languages:** Python/FastAPI only. The Go and TypeScript backends are **not in p04a**. p04_backend routes on `build_profile.backend_lang` (`p04_backend/task_agent.py:266-272`). DBs: PostgreSQL via asyncpg (default) or SQLite via aiosqlite (dev).
- **Verified high-severity bugs:**
  - (a) IR-path `routers/crud.py` uses `schemas.X` without `import schemas`. Startup fails with **NameError**, so every IR-driven app is dead at boot.
  - (b) IR role guards call `getattr(dict,'role')`, so any entity with IR permissions **returns 403 for everyone**.
  - (c) IR list endpoints return ORM objects inside `List[Any]`, giving a **PydanticSerializationError (500)**.
  - (d) The fallback `models.py` adds `relationship()` on `*_id` columns that have no ForeignKey, so **mapper configuration crashes**.
  - (e) Business-rule and enum text is pasted into Python source. A quote in a rule breaks `models.py`; a space or hyphen in an enum value breaks `stats.py` (**SyntaxError**).
  - (f) `multi_tenancy=True` filters on `org_id` columns that neither generator creates.
  - (g) The password-reset fallback **stores plaintext passwords**, because passlib is not in the generated requirements.
  - (h) Domain seed templates are never written to disk.
- **Self-checks:** a pre-gen validator, a post-gen validator and a live uvicorn smoke probe all exist. The probe's "blocking" `PipelineBlockedError` is swallowed by p04_backend's `except Exception` (`p04_backend/task_agent.py:397-398`).

## 2. Coverage table

| File | LOC | Purpose | Status |
|---|---|---|---|
| `__init__.py` | 0 | package marker | REAL (empty) |
| `task_agent.py` | 396 | `run()` entry. Pre-gen check → templates → IR fast-path or fallback → CRUD → pipelines/seed/patterns/infra → main.py → support files → validation → smoke test → TaskResult | REAL (deterministic) |
| `codegen_orchestrator.py` | 372 | `run_ir_fastpath`, `run_pipeline_and_seed_steps`, `run_validation_pass`, workflow-transition map | REAL |
| `ir_generators.py` | 443 | DomainIR → models.py and schemas.py (Numeric money types, enum/rule CheckConstraints, FK relationships, field validators) | TEMPLATE (buggy: rule/enum injection) |
| `ir_generator_helpers.py` | 569 | DomainIR → crud.py (RBAC, workflow guards, org_id), seed.py (20 rows/entity), stats.py; `validate_seed_dependencies` | TEMPLATE (crud broken: NameError, role guard, serialization); `validate_seed_dependencies` STUB + DEAD |
| `schema_builder.py` | 379 | Fallback models/schemas from field-name heuristics, domain money/PHI helpers (also imported by ir_generators); `_fix_common_issues` | TEMPLATE; `_fix_common_issues` DEAD |
| `crud_generator.py` | 564 | `_fallback_crud_routers` (ORM CRUD + cache + audit + ABAC `require_role`), `_get_roles_for_action`; LLM gens `_llm_models_and_schemas/_llm_crud_routers/_llm_seed_data/_llm_service_layer`, `_check_and_fix_sql_injection`, `_scrub_password_fields_from_response` | fallback TEMPLATE; all `_llm_*` + scrubbers DEAD (0 callers repo-wide) |
| `crud_generator_seed.py` | 229 | `_fallback_seed` (admin + ≤8 entities × 5 rows); `generate_llm_seed`, `get_seed_py` | `_fallback_seed` TEMPLATE; LLM fns LLM-DRIVEN but DEAD |
| `crud_generator_service.py` | 102 | `_fallback_service_layer` service-class stubs | DEAD (re-exported only) |
| `prompts.py` | 246 | CRUD/seed prompt builders, few-shot +/- examples, PromptCompiler private-method preamble, temperatures | DEAD (only consumer is dead `_llm_*`) |
| `templates.py` | 564 | `_DATABASE_PY`, `_AUTH_PY` (RS256), `_CONFIG_PY`, `_AUTH_ROUTER_PY`, `_RATE_LIMITER_PY`; re-exports templates_main; `_ENV_TEMPLATE`, `_DOCKER_COMPOSE_TEMPLATE`, `_REDIS_CACHE_PY` | TEMPLATE; the last three DEAD |
| `templates_main.py` | 518 | `_MAIN_PY_TEMPLATE`, requirements, Dockerfile, Alembic ini/env/mako, Makefile/README builders, `patch_main_py` router/middleware injection | TEMPLATE (`_SERVICES_INIT_PY` DEAD) |
| `helpers.py` | 574 | Audit service generator, `_check_imports`, `_smoke_test`, `_live_http_probe`, `_AUTH_FLOWS_PROMPT`, `_fallback_auth_flow_code`, `topological_sort_entities` | REAL/TEMPLATE; `_AUTH_FLOWS_PROMPT` + `topological_sort_entities` DEAD |
| `helpers_permissions.py` | 101 | services/permissions.py (Role enum, PERMISSIONS, `require_permission`, `mask_fields`) from p02c model | TEMPLATE (output never imported by generated CRUD → hollow) |
| `helpers_cache.py` | 182 | services/cache.py (redis.asyncio helpers + `RedisCacheMiddleware`) | TEMPLATE |
| `helpers_sse.py` | 46 | routers/realtime_router.py, a heartbeat SSE stream | TEMPLATE (heartbeat only, no domain events) |
| `pattern_injector.py` | 171 | Keyword/build_type detection → writes `phases/patterns/*` code into src/ + requirements | REAL |
| `pipeline_generator.py` | 337 | Domain-pack BusinessProcessPipelines → service stubs, orchestrators, `routers/pipeline_events.py`, PIPELINES.md | TEMPLATE (services are `# TODO` stubs returning success) |
| `pre_gen_validator.py` | 299 | Circular-FK / implicit-unique / reserved-name checks; `fix_relative_imports` | REAL (FK check blind to IR "fk" type) |
| `validator.py` | 270 | Post-gen: compile, `all_routers`, relative imports, seed unique duplicates | REAL |
| `gate.py` | 53 | Heuristic gate (/health, /ready, X-Request-ID, pagination, pool_size) | REAL but only `tests/test_phases.py:176` uses it. `issues` is never filled, so the gate always passes. |
| `seed_templates/__init__.py` | 25 | 3 empty `seed_*` funcs, `from models import User` | STUB |
| `seed_templates/{saas,crm,real_estate,restaurant,hrm,iot,security,events,food,sports,hospitality,education,library,gym_fitness,logistics,marketplace}.py` | 37–69 each (~901 total) | Hard-coded `async def seed_<domain>(db_session)` with fixed model/field names | DEAD in effect: the selected template is never written to disk (see §7) |
| `seed_templates/{healthcare,ecommerce,fintech,ai_integrated}.py` | 288/302/311/360 | `get_<domain>_seed_data(entities)` returning dict rows (ICD-10, SKUs, ledgers, RAG docs) | DEAD (0 callers; no `seed_<domain>` coroutine) |

No file is over 600 LOC. Nearest: helpers.py 574, ir_generator_helpers.py 569, crud_generator.py 564, templates.py 564.

## 3. Components

### 3.1 Pipeline steps (task_agent.run, `task_agent.py:71-396`)
| Step | Lines | What happens |
|---|---|---|
| 0 Inputs | 77-118 | Reads from `phase_input.input_data`: `raw_input/requirements, project_name, domain, entities, api_endpoints, multi_tenancy (or project_contract.multi_tenancy), tenant_isolation_model, realtime_features, seed_vocabulary, user_personas, has_customer_portal, architecture_path/json_path, domain_ir_path, permission_model, build_types`. The arch doc fills in `entities`/`api_endpoints` when they are missing. `memory_hint(mem)` is computed and never used (`106`). |
| 0b Pre-gen | 123-137 | `run_pre_gen_checks({"entities":…})`. Only a circular FK raises `PipelineBlockedError`. |
| 1 Templates | 140-146 | Writes `__init__, database.py, auth.py, config.py, rate_limiter.py, routers/__init__.py, routers/auth.py`. |
| 2 IR fast-path | 157-170 → `codegen_orchestrator.run_ir_fastpath:288-372` | `DomainIR.load` → models, schemas, stats, seed written to disk. Writes `src/.env` (random SECRET_KEY) and `.env.example`. Rebuilds `entities` from the IR. Builds workflow transitions (domain pack `load_pack(domain).workflows`, else a linear chain from IR workflow steps) and writes `scripts/workflow_transitions.json`. Then CRUD. On any exception it returns empty strings and the fallback runs. |
| 2b Fallback / compile | 176-222 | If models or schemas are empty: `_fallback_models/_fallback_schemas` (`generated_via="deterministic_fallback"`). `compile()` checks models/schemas and regenerates via fallback on SyntaxError. `fix_relative_imports`, then write. On any exception: `templates+fallback`. |
| 3 CRUD | 226-253 | If no IR crud: `_fallback_crud_routers(entities, multi_tenancy, permission_model)`. compile() check, auto-inject `all_routers`, `fix_relative_imports`, write `routers/crud.py`. |
| 3a-4c | 258-287 → `run_pipeline_and_seed_steps:102-222` | SSE router (if `realtime_features`) → domain-pack pipeline codegen → seed (IR seed, else domain template, else `_fallback_seed`) → `detect_active_patterns` + `inject_patterns` → audit service → cache service → permissions service (if `permission_model`). Returns the injection flags. |
| 5 main.py | 290-300 | `_build_main_py` + `patch_main_py` (audit/cache middleware; pipeline/realtime/ws/stripe/marketplace/erp routers). |
| 6 Support | 303-322 | requirements.txt, Dockerfile, `.env` and `.env.example` (identical content incl. the real SECRET_KEY and `ADMIN_PASSWORD=Admin1234!`), Makefile, README, Alembic scaffold. |
| 6c Validate | 327-328 → `run_validation_pass:225-285` | `validate_generated_backend` over all src/*.py. Every category is recorded in the global `ErrorRegistry` (`core.error_registry`). Failures are appended to `input_data["generation_warnings"]`. Also runs `core.repair_learning.load_validators()` (C6). |
| 7 Smoke | 331-342 → `helpers._smoke_test:200-257` | py_compile every file → AST import check (`aether_os.`, `gateway.`, `core.services.`, `phases.` are forbidden) → live probe: `uvicorn src.main:app` on a free port, GET /health and /docs. Missing-module errors are demoted to non-fatal. Other failures raise `PipelineBlockedError`. |
| Result | 347-396 | Confidence 0.9 for IR, 0.82 for fallback, 0.7 for exception; +0.05 if smoke passed, −0.2 if it failed, −0.1 for validation errors. Metadata: paths, `generated_via`, entity count, `pipeline_files`, smoke, validation errors/warnings, multi_tenancy, realtime router. |

### 3.2 IR → files (IR fast-path)
- **models.py** (`ir_generators.generate_models_py:184-248`):
  - Fixed `_USER_MODEL` (Integer PK, email unique, bcrypt `password_hash`, role default `'user'`). Any IR `User` entity is skipped.
  - Per entity: Integer PK. `_sa_column` maps AetherType through `SA_TYPE_MAP`:
    - FK → `Integer, ForeignKey('<pluralised snake ref>.id'), index`
    - EMAIL → String(320); URL → String(2048); ENUM → String(50) plus a `CheckConstraint IN (...)`
    - DECIMAL → `Numeric(12,2)` in money domains (`fintech/marketplace/erp`), else Numeric(14,2). Money-named STRING fields are promoted in money domains.
    - Healthcare PHI fields get only a `# PHI` comment.
  - `__table_args__`: business-rule `CheckConstraint('<raw expr>')` (`_sql_check_constraints:148-166`) plus indexes on created_at and status/state.
  - `relationship('<Ref>', foreign_keys=[fk], lazy='selectin')`. created_at/updated_at use Python-side defaults.
- **schemas.py** (`generate_schemas_py:347-438`): `PaginatedResponse`, and `XBase/XCreate/XUpdate/XResponse` per entity. EmailStr. Decimal in money domains. `@field_validator`s generated from numeric rules (`salary > 0`).
- **crud.py** (`ir_generator_helpers.generate_crud_py:206-251`):
  - Per entity: list (page/limit ≤100, returns ORM items), create (201), get, patch, a hidden put alias, delete (204). Every route depends on `get_current_user`.
  - Optional `_role_guard` from `ir.permissions`.
  - Optional workflow guard: a module-level `_TRANSITIONS_<ENTITY>` dict; PATCH returns 422 on an illegal `status` move.
  - Optional org_id scoping. `_log_action` audit hook (falls back to a no-op).
- **seed.py** (`generate_seed_py:380-462`): FK-topologically sorted (`_sort_entities_by_deps`), admin user (`ADMIN_PASSWORD` env, default `Admin1234!`), 20 rows per entity. Values come from `_seed_value` (type/name heuristics + `seed_vocabulary`). Idempotent via a User count check. Logs the admin password.
- **stats.py** (`generate_stats_router:475-569`): `/stats` with per-entity counts, per-enum-value stage counts, a "success_rate" over hard-coded statuses, and `total_cost` = sum of the first money-like field.

### 3.3 Fallback path (no IR)
- `_fallback_models` (`schema_builder.py:144-212`): the type comes from the field **name** only (`_col_to_sa_type:100-129`):
  - `*_id` → Integer, with an FK only when the name contains "user"
  - `is_*`/`archived`/`completed` → `Boolean default=True`
  - `status`/`type`/`stage`/`priority` → String(50) plus a fixed `CheckConstraint IN ('active','inactive','pending','open','closed','new')`
  - Fields whose name contains name/email/title/status → NOT NULL
  - Adds a soft-delete `deleted_at` that nothing uses
- `_fallback_schemas` (`217-284`): all fields Optional. Type comes from IR `type` if present, plus money-name override.
- `_fallback_crud_routers` (`crud_generator.py:372-559`):
  - ORM-only (no raw SQL). page/page_size ≤200. Static serialization dicts that skip `password*`.
  - `require_role(...)` from the p02c `permission_model` (`_get_roles_for_action:329-369`, SuperAdmin always appended); delete falls back to `require_admin`.
  - Cache hooks via `from cache import ...`, which falls back to no-ops. org_id filters. `_log_action`.
  - Appends `_fallback_auth_flow_code()`: forgot/reset/verify with an in-memory token dict and SMTP.
- `_fallback_seed` (`crud_generator_seed.py:18-148`): admin plus 5 rows per entity, only for entities with a `name` field (≤8 entities). Unique-field patterns.

### 3.4 Infra and add-ons
- **Auth** (`templates.py:159-294`):
  - RS256 PyJWT. The keypair is auto-generated into CWD (`private_key.pem`) at import.
  - Access token 30 min (env), refresh token 7 days, `type` claim checked.
  - bcrypt hashing. `require_admin` (role == "admin"); `require_role(*roles)`.
  - Router (`318-442`): `/auth/login` (10/min), `/auth/register` (5/min, open self-signup, role="user"), `/auth/refresh`, `/auth/me`.
- **DB** (`templates.py:31-97`): async engine. PG pool size = cpu×2 (min 4), `statement_timeout` 30 s, `pool_recycle` 300. SQLite uses NullPool. `get_db` commits or rolls back per request. Startup runs `Base.metadata.create_all` + seed (`templates_main.py:69-82`). Alembic is scaffolded with an empty `versions/`.
- **main.py** (`templates_main.py:12-185`):
  - Middleware: dotenv, CORS from env, GZip, security headers (nosniff, SAMEORIGIN, Referrer-Policy), X-Request-ID access log.
  - Global 500 handler. Prometheus `/metrics` (optional). slowapi exception handler.
  - Routes `/health`, `/ready` (SELECT 1), `/`. Everything is mounted under `/api`.
- **Patterns** (`pattern_injector.py`): keyword triggers in `raw_input` or `build_types` copy `aether_os.phases.patterns.*` code into multi_tenant.py, agent.py, websocket_router.py, billing_router.py, marketplace_router.py, approval_router.py, social_router.py and iot_router.py. Only websocket/stripe/marketplace/erp are wired into main.py (`templates_main.py:486-517`).
- **Pipelines** (`pipeline_generator.py:270-337`): domain-pack `pipelines` produce `services/<svc>.py` stubs, `services/pipelines/<x>_orchestrator.py`, `routers/pipeline_events.py` (POST → BackgroundTasks, 202) and `PIPELINES.md`.
- **Audit** (`helpers.py:30-165`): `AuditLog` table, `log_action` (flush only), `AuditContextMiddleware` (IP/UA/session contextvars). `register_audit_listeners` only logs at debug level and is never called.
- **Cache** (`helpers_cache.py`): redis.asyncio with a latched no-op fallback. `RedisCacheMiddleware` caches GET `/api/*` (except auth, health, docs) for `CACHE_TTL`, keyed by path + query + `md5(Authorization)[:8]`.
- **Permissions** (`helpers_permissions.py`): Role enum, PERMISSIONS/ROW_FILTERS/FIELD_MASKS JSON, `require_permission` and `mask_fields`. Nothing in the generated app imports it.

### 3.5 LLM-first vs template fallback
There is none in the live path: template/IR always wins. The dead LLM code, if it were revived, would use:
- `llm.call(prompt, task_type="code_generation", max_tokens=6000/4000)`
- `get_llm_client().call(..., max_tokens=4096)` with a 90 s timeout
- the prompts `build_crud_prompt` / `build_seed_prompt` (`prompts.py:117-246`), golden few-shots (`core.learning.golden_retriever`), and private `PromptCompiler._get_backend_constraints/_extract_decisions/_build_error_prevention_block`

`core/llm/phase_config.py:22` still configures p04a at temperature 0.2, 8192 tokens, "powerful" tier. That config is unused by p04a.

## 4. Control flow and data flow

```
s03_backend.supervisor._run_p04_backend (stages/s03_backend/supervisor.py:236-262)
  └─ p04_backend.run (p04_backend/task_agent.py:260)
       ├─ backend_lang=go → _run_go_backend | typescript → _run_node_backend   (NOT p04a)
       └─ p04a.run(phase_input, memory_ctx, <stage>/p04_backend/backend_codegen)
            inputs ← p01 (raw_input, project_name, domain, project_contract.multi_tenancy, build_types)
                   ← p02 architecture (architecture_path/json_path → entities, api_endpoints)
                   ← p02b (domain_ir_path → domain_ir.json; p02b_domain_ir/task_agent.py:193, phase_hooks_helpers.py:157)
                   ← p02c (permission_model: roles/permissions/row_filters/field_masks)
                   ← accumulated ctx (seed_vocabulary, realtime_features, user_personas, has_customer_portal)
                   ← core: domain_knowledge.load_pack(domain) (workflows, pipelines), repair_learning validators
            outputs → disk tree above + TaskResult.metadata
                   → input_data["generation_warnings"], ["pre_gen_warnings"/"pre_gen_errors"], ErrorRegistry records
       p04_backend afterwards: merges metadata into input_data, writes backend_output_path, regex-extracts routes
         → api_routes.json (api_routes_path) for p05 frontend; runs its own _startup_smoke_test; ArchitectureGovernor
         phantom/missing entity check (p04_backend/task_agent.py:280-395)
```
**Downstream readers of the p04a tree:** each probes `p04_backend/backend_codegen/src`, then `p04a_backend_codegen/src`.
- p04b gate (confidence) — `p04b_business_logic/gate.py:31`
- p04c — `p04c_integration_codegen/task_agent.py:187`
- p05 — via `api_routes.json`
- p07a unit testing — `p07a_unit_testing/task_agent.py:43`
- p07b self-healing reuses `_fallback_crud_routers` — `p07b_self_healing/quality_helpers.py:233`
- p08 CI/CD — `p08_cicd/task_agent.py:32-54`
- p09 observability — `p09_observability/task_agent.py:180`
- p11 deployment — `p11_deployment/helpers.py:75,102`
- core quality metrics / truth engine
- gateway run_spec_router

## 5. Plane mapping

| Plane | p04a contribution |
|---|---|
| SDLC | Core code-construction step: entity IR → ORM/schema/CRUD/seed, plus Alembic scaffold, Makefile, README, PIPELINES.md, workflow_transitions.json. |
| STLC | Pre-gen validator, post-gen validator (compile/all_routers/relative imports/seed uniqueness), py_compile + import AST + live uvicorn /health probe, heuristic gate (test-only). Makefile `test` target exists, but p04a generates no tests. |
| SRE | `/health`, `/ready` (DB ping), Prometheus `/metrics`, X-Request-ID structured access log, Docker HEALTHCHECK, DB pool tuning + statement_timeout, Redis cache with graceful degradation, GZip. |
| Compliance | Money → `Numeric(12,2)` (PCI-flavoured), HIPAA PHI **comments only**, an `AuditLog` table + `log_action` on CRUD and password reset (immutability not enforced), soft-delete column (unused). Healthcare/fintech seed datasets exist but are DEAD. |
| Security | RS256 JWT access/refresh, bcrypt, slowapi on login/register, CORS allow-list, security headers, ABAC via `require_role` (fallback path) / IR role guard (broken), org_id tenancy (broken), password-field exclusion, ORM-only queries (no SQL injection in templates), random SECRET_KEY per build. Weaknesses listed in §7. |
| Deployment | Dockerfile (python:3.11-slim, root, `COPY . .`), requirements.txt, `.env`/`.env.example`, Alembic, ROOT_PATH support. docker-compose template is DEAD (Makefile `docker` target references a compose file p04a never writes). |
| Admin control | Seeded `admin@example.com` / `ADMIN_PASSWORD` (default `Admin1234!`), `require_admin` on fallback deletes, ABAC permission service file (unused), SuperAdmin auto-grant. |
| API management | All routers under `/api`. Consistent CRUD surface (list/get/post/patch/put-alias/delete), pagination caps, OpenAPI `/docs` and `/redoc`, `/stats` KPI endpoint, `/pipeline-events/*` 202 triggers, `/realtime/stream` SSE. Global rate limits are declared but not enforced (no SlowAPIMiddleware). |
| Other | Domain-pack business-process orchestrator stubs, pattern library (billing, marketplace, ERP approval, websocket, social, IoT, agentic AI), seed vocabulary for realistic demo data. |

## 6. Interfaces and dependencies

- **Entry:** `async run(phase_input, memory_ctx, output_dir) -> TaskResult` (`task_agent.py:71`). Gate: `validate(TaskResult) -> GateOutcome` (`gate.py:8`).
- **Public helpers:**
  - `run_ir_fastpath(...) -> (models, schemas, crud, seed, entities)`
  - `run_pipeline_and_seed_steps(..., *_fn injected callables) -> dict flags`
  - `run_validation_pass(src_dir, phase_input) -> ValidationReport`
  - `ir_to_models/ir_to_schemas/generate_crud_py/generate_seed_py/generate_stats_router(ir, ...)`
  - `_fallback_models/_fallback_schemas/_fallback_crud_routers/_fallback_seed`
  - `run_pre_gen_checks(dict) -> PreGenReport`
  - `validate_generated_backend(files) -> ValidationReport`
  - `fix_relative_imports(code)`
  - `detect_active_patterns/inject_patterns`
  - `generate_pipeline_code(pipelines, src_dir, domain)`
- **Platform imports:** `aether_os.phases.base` (TaskResult, GateOutcome), `core.errors.PipelineBlockedError`, `core.domain_ir` (DomainIR, AetherType, SA_TYPE_MAP, IR*), `core.domain_knowledge.loader.load_pack`, `core.error_registry`, `core.repair_learning.load_validators`, `phases.utils.memory_hint`, `phases.patterns.*`. Dead code references `core.prompt_compiler`, `core.learning.golden_retriever` and `core.llm.client`.
- **Mixed import roots:** some files import `phases.p04a_backend_codegen...` (`helpers.py:169,516`, `templates.py:13`, `crud_generator.py:13-14,563-564`); others import `aether_os.phases...`. This works because pyproject `packages.find where=["."]` + editable install (Dockerfile `pip install -e`) and CWD expose `phases` as a top-level package. The side effect is duplicate module objects (verified: `sys.modules['phases']` is loaded).
- **Host runtime deps:** httpx, uvicorn (subprocess via `sys.executable`), and enough of the generated app's deps to boot the probe.
- **Generated-app deps** (`templates_main.py:189-207`): fastapi, uvicorn, sqlalchemy[asyncio], aiosqlite, asyncpg, psycopg2-binary, alembic, pydantic[email], PyJWT, bcrypt, python-multipart, httpx, python-dotenv, slowapi, email-validator, redis, prometheus-fastapi-instrumentator, plus pattern requirements. **Missing:** `cryptography` (needed by RS256 key generation in `_AUTH_PY`; only pulled in transitively, if at all) and `passlib` (used by the reset-password fallback).

## 7. Reality check

**Verified by execution** (scratch generation with real generators, sample IR):
1. **IR crud.py NameError at import** — `ir_generator_helpers.py:224-238`. `generate_crud_py` emits `import models` + `from schemas import XCreate, XUpdate`, then uses `schemas.PaginatedResponse` / `schemas.XResponse` in decorators (`:121,136,150,163,183`). `_CRUD_IMPORTS` (`:19-28`, which has `import models, schemas`) is dead. Result: `NameError: name 'schemas' is not defined`. `routers/__init__.py` imports crud, so `main.py` cannot start. compile() and the validator pass it. The live probe would catch it, but the error is demoted if the host lacks any dep (e.g. aiosqlite → "No module named"), and `PipelineBlockedError` is swallowed by p04_backend anyway. Present since commit 8a76db5 (2026-06-18).
2. **IR role guard always denies** — `ir_generator_helpers.py:52`: `getattr(current_user,'role',None)` on the dict returned by `get_current_user` (`templates.py:269`) is always None. Every action that has IR permissions → 403.
3. **IR list endpoint 500** — `:134` returns ORM instances in `PaginatedResponse.items: List[Any]` (`ir_generators.py:369-374`). Verified: `PydanticSerializationError: Unable to serialize unknown type`.
4. **Fallback models crash mapper config** — `schema_builder.py:174-176` emits `relationship()` for every non-user `*_id`, but `_col_to_sa_type:108-109` adds a ForeignKey only for `user`. Verified `NoForeignKeysError`. `fn[:-3].capitalize()` also produces wrong class names for multi-word refs (`order_item_id` → `Order_item`).
5. **Source injection / SyntaxError from IR text:**
   - Business-rule `expression` goes verbatim into `CheckConstraint('{expr}')` (`ir_generators.py:165`). `status != 'closed'` → models.py SyntaxError (verified). Arbitrary LLM-derived text becomes generated Python and DDL.
   - Enum values become identifiers in stats.py (`ir_generator_helpers.py:526-530`). `"in progress"` → SyntaxError (verified). stats.py is written without a compile check (`codegen_orchestrator.py:324`).
   - Enum values with `'` also break `_sa_column:114`.
6. **Multi-tenancy references a missing column** — both CRUD generators filter and set `Model.org_id` (`crud_generator.py:438-449`, `ir_generator_helpers.py:98-100`). Neither models generator adds `org_id`, and the IR has none (`grep org_id core/domain_ir.py` → 0). Verified `hasattr(Order,'org_id') == False` → 500 on every tenant-scoped request. `register` also never sets org_id.

**From reading** (high confidence):

7. **Seed templates never written** — `codegen_orchestrator.py:162-183`. When `seed_templates/<domain>.py` exists, `seed_code` is set, but the `write_text` sits inside `if not seed_code:`. No seed.py is written, `main.py`'s `from seed import seed_database` fails ("Seed skipped") and **no admin user exists**. This hits only the non-IR path for the 20 template domains. Even if written, the templates hard-code models/fields that don't match generated models, use `password_hash="hashed"` (bcrypt `checkpw` raises → 500 on login), and aren't idempotent. The 4 `get_*_seed_data` modules have no caller.
8. **Plaintext password storage** — `helpers.py:484-490`. The reset flow imports passlib (not in requirements) and on ImportError sets `user.password_hash = new_password`. That then breaks bcrypt login. Reset/verify tokens live in process-memory dicts (lost on restart, not shared across workers), and `_verify_tokens` is never populated, so verify-email always returns 400.
9. **Role-name mismatch** — p02c roles are `SuperAdmin/Admin/Manager/Staff/ReadOnly` (`p02c_permission_modeling/task_agent.py:27`). The seeded admin has `role='admin'` and registration gives `'user'`. Fallback `require_role("SuperAdmin","Admin",…)` compares case-sensitively (`templates.py:287`), so even the seeded admin is locked out of ABAC-guarded endpoints.
10. **Open authz in the IR path** — with no IR permissions, every CRUD route (including delete) needs only a valid token, and `/auth/register` is open self-signup. Anyone on the internet can register and modify or delete all data. The fallback path guards delete with `require_admin` but not create/update.
11. **Secrets hygiene:**
    - `.env.example` is written with the same content as `.env`, including the real SECRET_KEY (`task_agent.py:318-319`). The IR path also writes a second `src/.env` (`codegen_orchestrator.py:334`).
    - `ADMIN_PASSWORD=Admin1234!` is the default everywhere and the seed logs it in cleartext (`ir_generator_helpers.py:460`, `crud_generator_seed.py:147`).
    - The Dockerfile `COPY . .` with no generated `.dockerignore` bakes in `.env`, any `private_key.pem` and the probe-created `app.db`. The container runs as root.
    - SECRET_KEY is unused by auth (RS256).
    - The RSA keypair is generated per container at import time, so tokens die on restart, can't be shared across replicas, and multiple workers race.
    - The README claims `SECRET_KEY`/`CORS *` defaults that are stale (`templates_main.py:405-412`).
12. **Cache issues:**
    - CRUD imports `from cache import …`, but `src/cache.py` (`_REDIS_CACHE_PY`) is never written, so CRUD caching is always a no-op.
    - `RedisCacheMiddleware` is live whenever `REDIS_URL` is set. It serves stale GETs up to 30 s after writes (CRUD invalidation targets different keys), keys on `md5(auth)[:8]` (a 32-bit collision space across users), and has `except Exception: pass` (`helpers_cache.py:167-168`).
    - The fallback single-item cache key `"{name}:{item_id}"` is not org-scoped (latent cross-tenant leak if the cache module ever exists).
13. **Live probe defects** (`helpers.py:260-358`):
    - `/docs` is requested on an `httpx.AsyncClient` after its `async with` block has closed, so `docs_ok` is always False.
    - The `.env` file overrides the probe DB URL, leaving a seeded `app.db` in the output.
    - The probe subprocess inherits the **full platform `os.environ`** (`:281`), giving generated code (including pattern code) the AetherOS host's credentials.
14. **Validator noise** — `_ROUTERS_INIT_PY = "from .crud import all_routers"` (`templates_main.py:187`) trips `check_no_relative_imports` on every build, so a `relative_import` category is recorded in the global ErrorRegistry every run (pollutes learning). `check_seed_unique_fields`'s DOTALL regex (`validator.py:118-121`) can span lines and produce false positives.
15. **Pre-gen FK check is blind** — it only detects `foreignkey` in the `type` string (`pre_gen_validator.py:68`). IR/entity dicts use `type:"fk"` + `ref_entity`, so cycles are never found. It also runs on `entities`, not the IR.
16. **Partial-failure mismatch:** if IR models fail compile, task_agent swaps in `_fallback_models` (`task_agent.py:198-205`) but keeps the IR schemas/crud/seed/stats. The two use different column sets, and the fallback brings in bug 4.
17. **IR seed FK violations** — FK values `(idx%3)+1` (`ir_generator_helpers.py:287`). For FK→User only id 1 exists, so PG raises an FK error (SQLite doesn't enforce FKs). Unique non-pattern strings repeat every 10 rows.
18. **Fallback seed often fails entirely** — NOT NULL is applied to title/status (`schema_builder.py:166`), but the seed sets only `name` and unique fields. The commit fails and the whole seed rolls back, including the admin.
19. **Hollow or dead outputs:**
    - services/permissions.py is never imported.
    - `register_audit_listeners` is never called.
    - `deleted_at` is never honoured.
    - social_router.py, iot_router.py, multi_tenant.py and agent.py are written but never mounted.
    - Pipeline services are `# TODO` stubs that return success.
    - SSE emits only heartbeats.
    - Fallback booleans like `archived`/`completed` default to True.
20. **Gate never fails** — `issues` is never appended (`gate.py:19-53`), and there is an unused `list_routes`. The gate is not wired into the pipeline (test-only).
21. **Error-handling rule violations in generated code:** `except Exception: pass` in `templates_main.py:100-101, 460-466` (patch_main_py middleware injection), `helpers_cache.py:167-168`, plus `except ImportError: pass` blocks. Platform-side generator code is compliant. `_live_http_probe` logs a warning on each connect retry (log noise).
22. **SQL injection:** none in the live templates (ORM only). `_check_and_fix_sql_injection` (`crud_generator.py:139-165`) is dead and would itself emit `None  # TODO` statements with fixed indentation if revived.

**Dead code inventory** (0 callers repo-wide, by grep):
- `_llm_models_and_schemas`, `_llm_crud_routers`, `_llm_seed_data`, `_llm_service_layer`, `_check_and_fix_sql_injection`, `_scrub_password_fields_from_response`, `_MULTI_TENANCY_PROMPT`
- `generate_llm_seed`, `get_seed_py`, `_fallback_service_layer`
- all of `prompts.py`; `_AUTH_FLOWS_PROMPT`
- `_fix_common_issues`, `topological_sort_entities`, `validate_seed_dependencies` (also a stub), `_CRUD_IMPORTS`
- `_ENV_TEMPLATE`, `_DOCKER_COMPOSE_TEMPLATE`, `_REDIS_CACHE_PY`, `_SERVICES_INIT_PY`
- all 21 seed_templates (in effect)

That is roughly 2.9K of 8.5K LOC.

## 8. Open questions
1. Does a later phase (p04b business logic, p07b self-healing) rewrite `routers/crud.py` and so mask bug 1? Or are IR-path apps shipped unbootable? p07b imports only `_fallback_crud_routers`.
2. Should p04a's `PipelineBlockedError` actually halt s03? p04_backend catches all exceptions (`p04_backend/task_agent.py:397`).
3. Where should `org_id` columns come from? IR/p02b never emits them, but p01 `project_contract.multi_tenancy` turns tenancy on.
4. Is `gate.py` meant to be wired into a p04 supervisor? Currently test-only.
5. Is the dead LLM path (and `core/llm/phase_config.py` p04a entry) planned for revival, or slated for deletion?
6. Which component owns the generated Go/TS backends (p04_backend `_run_go_backend`/`_run_node_backend`)? They are mapped in another section, not here.
7. Should generated apps use Alembic migrations instead of `create_all` at startup? `versions/` is always empty.
8. Is `seed_vocabulary` / `realtime_features` / `build_types` reliably produced upstream? Their source is outside this scope.
