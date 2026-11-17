# AetherOS - System Architecture

Checked against the code at commit `e5c23fd`. Each section names the files it was read from.
Claims about runtime behaviour in production (load, latency, uptime) are not measured.

## System overview

```
User / CLI / API client
        |  HTTPS
   nginx (deploy/nginx.conf; TLS via certbot, deploy/setup_vps.sh)
        |
   uvicorn, 4 workers  ->  FastAPI app  gateway/api.py (create_app, --factory)
        |        middleware: CORS, GZip, trace id, request logging (org/user id),
        |        security headers, optional HTTPS redirect
        |        78 router entries mounted from gateway/api.py (_ROUTERS)
        |
   FactoryPipeline  orchestrator/factory_pipeline.py
        |  12 stages in order (orchestrator/phase_sequence.py PHASE_SEQUENCE)
        |  each stage supervisor runs its own phase agents (stages/sNN_*/supervisor.py)
        |
   Stores: PostgreSQL or SQLite (core/db.py), Redis (bus, run events, auth state, rate limits),
           run files on local disk, optional Chroma vector store
```

- Clients: the React dashboard in `dashboard/` (Vite, Tailwind 4, React 19, Monaco editor; `dashboard/package.json`)
  and the CLI `cli/aetheros.py` (Typer, Rich).
- Gateway: `gateway/api.py`. The 78 entries in `_ROUTERS` come from 72 `*_router.py` modules in
  `gateway/routers/` (76 `.py` files in that folder in all, including helpers and `__init__.py`) plus the
  client portal, MCP, SAML, OAuth and MFA routers elsewhere in `gateway/`. Entries marked required stop startup
  if the import fails; the others log a warning.
- Sentry is started from `gateway/api_utils.py:_init_sentry` when configured. Rate limiting is in
  `core/rate_limiter.py`, not slowapi (see `SECURITY.md`).
- `core/services/pipeline_service.py` defines `PipelineService`, but no gateway router imports it. Routers call
  `get_factory()` and other code directly.

## Data stores

- Database: PostgreSQL through asyncpg when `DATABASE_URL` is set, otherwise SQLite at `~/.aether_os/aether_os.db`
  (`core/db.py:36-51`). On PostgreSQL the schema belongs to Alembic and startup refuses a database that is not
  at the Alembic head (`core/db.py:166-190`). Table reference: `DATA_MODEL.md`.
- Redis: message bus lists, run event history and live events, auth token state, rate-limit counters. Without
  Redis the bus falls back to in-process queues, and rate limits fall back to memory unless `REQUIRE_REDIS` is on.
- Generated apps: the default stack profile is `web_saas` (`core/stack_profiles.py:255`, PostgreSQL plus Redis).
  A `web_saas_sqlite` profile exists (`stack_profiles.py:46`) and is used when selected. SQLite is not the default
  for generated apps.

## The pipeline: 12 stages

`orchestrator/phase_sequence.py:90-103` defines `PHASE_SEQUENCE` as 12 stages (it was a list of 21 phases in
older docs). `PHASE_SUPERVISORS` maps each stage to a supervisor class (`:108-121`), loaded with `importlib`
(`_load_supervisor`). Critical stages, whose failure ends the run: `s01_intake`, `s02_architecture`,
`s03_backend` (`:22-26`). The phase agents in `phases/` are called by the stage supervisors; they are not in
`PHASE_SEQUENCE`. `docs/PIPELINE_SPEC.md` lists every phase directory.

| Stage | Name | Phases it calls (from the stage supervisor) | Org may switch off |
|-------|------|----------------------------------------------|--------------------|
| s01_intake | Intake | p00_research, p00b_data_archaeology, p00c_architecture_planner (parallel), then p01_intake_requirements, p01b_integration_discovery | no |
| s02_architecture | Architecture | p02_architecture, p02b_domain_ir, p02c_permission_modeling, p03_scaffolding (sequential) | no |
| s03_backend | Backend | p04_backend (calls p04a_backend_codegen), p04b_business_logic, p04c_integration_codegen, then the architecture governor | no |
| s04_frontend | Frontend | p05_frontend; p05b_mobile, p05c_desktop, p05d_cli, p05e_serverless only when the build profile asks | no |
| s05_quality | Quality gate | p06_review_security and p06b_formal_verification (Z3), then a dimension scorer | no |
| s06_testing | Testing | p07a_unit_testing; performance, accessibility and E2E are deferred to s07 | no |
| s07_healing | Self-healing | starts the app, probes 4 health layers, repairs with p07b_self_healing; runs p07b_performance_testing, p07c_accessibility_testing, p07d_e2e_testing | no |
| s08_observability | Observability | p09_observability, then p11a, p11b, p11c in parallel, then p11d_alerting | yes |
| s09_devops | DevOps | p08_cicd_deployment, p11_deployment, p11e_enterprise_deployment (kubernetes or microservices only) | no |
| s10_enterprise | Enterprise | p12a, p12b, p13, p16, p18, p21 in parallel; p17_control_plane when kubernetes or microservices | yes |
| s11_handoff | Handoff | p10_docs_delivery, then p14_client_portal and p15_handoff in parallel | no |
| s12_specialist | Specialist outputs | p05b-e, p19_service_catalog, p20_multiregion, each conditional | yes |

Sources: `stages/s*/supervisor.py` module docstrings (inputs, outputs, sub-steps) and
`orchestrator/stage_gate.py:15-25` (`MANDATORY_STAGES`). Docstring text describes intent; which sub-steps ran
in a real run: not measured.

### Gates and failure handling

- Every phase extends `PhaseBase` (`phases/base.py`): run the task, call `validate_gate`, retry up to
  `max_retries` (default 3), then mark the result `escalated`
  (`phases/base.py:46`, `:208-250`). `GateOutcome` has `passed`, `issues`, `confidence` (`phases/base.py:33-36`).
- The pipeline treats an `escalated` result as a failed gate for any stage, and a `failed` or timed-out result
  as blocking for critical stages (`orchestrator/stage_gate.py:gate_block_reason`; used at
  `factory_pipeline.py:471` and `:576`).
- `orchestrator/routing/router.py` maps failure types to a pipeline state to retry, but nothing outside tests
  calls `route_failure`. The factory pipeline does not use it.
- A run can wait for a human decision (`decision_mode` `approval_required`, `factory_pipeline.py:298`; wait up
  to 7 days, `:1048`). Organisations in autonomous mode skip approval gates.

### Checkpoint and resume

After each completed stage `save_checkpoint` writes `{"last_completed_phase", "accumulated_context"}` to
`runs.checkpoint_data` (`orchestrator/run_state.py:62-83`; `factory_pipeline.py:480`, `:688`). The column has the generic JSON type on every
database (`core/models.py:115`), not JSONB. On start, `restore_from_checkpoint`
(`orchestrator/phase_selector.py:129`) skips the stages already done and reloads the saved context.
Routes: `POST /factory/runs/{id}/restart` resumes a failed or cancelled run from its checkpoint
(`gateway/routers/run_decisions_router.py:116`); `POST /factory/runs/{id}/rerun` creates a new run that starts at
a chosen stage on a copy of the parent's files (`run_fork_router.py:109`); `POST /factory/runs/{id}/branch`
(`run_fork_router.py:129`). There is no `/retry` route.

## Message bus and live events

- `orchestrator/bus.py`: Redis `RPUSH` to a list per run and target phase, `BLPOP` to read, with a 3600 second
  expiry; keys are `aetheros:bus:{run_id}:{phase}` and a `__broadcast__` list (`bus.py:15-26`, `:74-82`, `:129`).
  The wait for a message is 120 seconds. Without Redis it uses bounded `asyncio.Queue` objects (1000 items).
- Live events to the browser: `GET /factory/runs/{id}/stream` (Server-Sent Events,
  `gateway/routers/factory_run_streaming_router.py:50`). It replays stored event history, then follows a Redis
  pub/sub channel (`:99-209`). A short-lived token comes from `POST /factory/runs/{id}/sse-token` (`:36`).

## Model routing

`core/model_router.py` and `core/model_router_providers.py`. Before each call `core/llm/guard.py:admit()` checks
kill switches, the organisation and its spend allowance. The chain is built from `PRIMARY_LLM` (default
`bedrock`): Bedrock Nova Pro, a Bedrock fallback, Anthropic and Gemini when keys are set, OpenRouter models, then
Ollama. One attempt per model; timeouts 45 to 60 seconds for cloud models. Details and prices: `COST_MODEL.md`.

## Multi-tenancy and authentication

The `org_id` is a claim in the JWT; handlers take it from the validated token (`gateway/dependencies.py`). The
`X-Org-ID` header only tags logs. Models carry an `org_id` column where the data belongs to an organisation
(`DATA_MODEL.md`). That every query filters on it: not verified.

Authentication, roles, MFA, SAML and SCIM: `SECURITY.md` has the code references. Short form: RS256 JWT (HS256
fallback), access token 1 hour, refresh token 30 days with rotation and reuse detection; roles `viewer`,
`member`, `api`, `admin`, `owner`, `superadmin`; TOTP MFA; SAML through python3-saml; SCIM v2 Users and Groups.

## Compliance engine

`core/policy/compliance.py` `ComplianceEngine.evaluate(ComplianceContext)` runs five rules: export embargo
(a fixed country set), EU data residency with a third-country cloud, high-risk AI use cases, weak or strong
crypto in embargoed countries, and sensitive data (children, EU/UK biometric, sensitive industries). The worst
violation decides: critical means denied, high or medium means approval needed, otherwise allowed. It has no
rule named GDPR, HIPAA or PCI-DSS and does not certify anything. It is called from `agents/implementations.py`
(lines 92 and 394), not from `factory_pipeline.py`. Separately, the generated-app scanner
(`core/security/code_scanner.py`) and the domain packs (`core/domain_knowledge/packs/`) carry compliance rule
text for generated code.

## Full development environment endpoints

| Endpoint | File |
|----------|------|
| `GET`, `PATCH /factory/runs/{id}/file-content` | `gateway/routers/factory_run_files_router.py:130`, `:160` |
| `POST /factory/runs/{id}/open-in-vscode` | `factory_run_files_router.py:187` |
| `GET`, `PATCH /factory/runs/{id}/envvars` | `factory_run_files_router.py:203`, `:237` |
| `POST`, `DELETE /factory/runs/{id}/run-app`, `GET .../run-app/status` | `gateway/routers/run_app_router.py:83`, `:97`, `:133` |

Whether the dashboard debounces saves and streams process output over SSE: not verified.

## Sandbox for generated code

`core/sandbox/docker_backend.py`: each command runs in a Docker container with dropped capabilities, read-only
root, resource limits and no network except for package installs; see `SECURITY.md`. `core/sandbox/guard.py` is
only a regex filter.

## Deployment

- systemd unit `deploy/aetheros.service` runs `uvicorn aether_os.gateway.api:create_app --factory` with 4 workers
  (user `aetheros`). The `Dockerfile` runs the same command with 4 workers.
- `deploy/setup_vps.sh` installs nginx and certbot and builds the dashboard with `npm ci`.
- `deploy/deploy.sh` installs the package, runs `scripts/db_migrate.py` (`alembic upgrade head` on an existing
  database, create-and-stamp on an empty one; `deploy.sh:46-48`), rebuilds the dashboard, reloads the service and
  checks `/health`. The old text named `alembic upgrade add_pipeline_run_checkpoint`, which is not what the script does.
- `docker-compose.yml` and `docker-compose.staging.yml` exist in the repository root. `helm/` and
  `deploy/terraform` and `deploy/kubernetes` also exist. That any of these has been applied to a live
  environment: not verified.
