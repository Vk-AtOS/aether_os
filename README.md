# AetherOS

AetherOS turns a plain-English requirement into a generated application. A FastAPI gateway starts a pipeline run. The pipeline runs 12 stages. Each stage supervisor calls a set of phase agents that call an LLM and write code, configuration and reports into a project directory.

This file was checked against the code at commit `e5c23fd`. Where a number or behaviour has no evidence in the repository, it says "not measured". Counts that can be recomputed show the command.

---

## What It Generates

`core/stack_profiles.py` registers 17 stack profiles (`STACK_PROFILES`). The classifier in `phases/p00_research/stack_selector.py` picks one per run.

| Profile | Backend | Frontend | Database | Deployment target |
|---|---|---|---|---|
| `web_saas` | python / fastapi | react | postgres | docker_compose |
| `web_saas_sqlite` | python / fastapi | react | sqlite | docker_compose |
| `go_api` | go / gin | react | postgres | kubernetes |
| `go_microservices` | go / gin | react | postgres | kubernetes |
| `node_api` | typescript / fastify | react | postgres | docker_compose |
| `node_serverless` | typescript / express | react | postgres | serverless |
| `java_enterprise` (experimental, partial) | java / spring_boot (no generator: the backend is generated as Python/FastAPI) | react | postgres | kubernetes |
| `mobile_react_native` | python / fastapi | react_native | postgres | docker_compose |
| `mobile_rn` | python / fastapi | react_native | postgres | docker_compose |
| `desktop_electron` | python / fastapi | electron | sqlite | native |
| `desktop_tauri` | python / fastapi | electron | sqlite | native |
| `cli_tool` | python / fastapi | none | sqlite | native |
| `cli_go` | go / gin | none | sqlite | native |
| `ml_pipeline` | python / fastapi | react | postgres | docker_compose |
| `realtime_app` | go / gin | react | postgres | kubernetes |
| `cloud_platform` | python / fastapi | react | postgres | kubernetes |
| `microservices` | go / gin | react | postgres | kubernetes |

These are the values in the registry. Whether a profile has a working generator is a separate question (see below).

Backend generation is routed by `build_profile.backend_lang` in `phases/p04_backend/task_agent.py:254-261`. There is a Go generator (`go_generator.py`, `go_grpc_generator.py`) and a TypeScript generator (`node_generator.py`). There is no Java generator: the `java_enterprise` profile is experimental and only partly supported. Selecting it routes to the default Python/FastAPI backend generator, so no Spring Boot code is produced; the frontend, database and Kubernetes choices of the profile still apply. The CI/CD phase has a Java build template (`phases/p08_cicd/lang/java.py`).

Other files that generation code writes (each one was found in the code that writes it):
- `compliance_manifest.json` (`phases/p06_review_security/manifest.py:20`, called from `subtasks.py:21`).
- `domain_knowledge.json` (`phases/p06_review_security/subtasks.py:346-350`).
- `business_model.json` (`phases/p00_research/business_model_generator.py`).
- `formal_verification_report.json` (`phases/p06b_formal_verification/task_agent.py`); fields, verdicts and what is and is not proved: `docs/VERIFICATION_REPORT.md`.
- A GitHub Actions workflow with a `compliance-drift` job (`phases/p08_cicd/task_agent.py:249`).
- IAM output: OPA Rego and Keycloak realm JSON (`phases/p16_iam/`).
- Billing and metering output: OpenMeter and Stripe handlers (`phases/p18_billing_metering/`).
- Chaos experiments (`core/chaos_engineering/chaos_generator.py`), Kong, MinIO and NATS configs (`core/cloud_primitives/`), HPA, KEDA and PDB manifests (`core/capacity_planner/planner.py`), multi-region topology (`core/cell_architecture/cell_planner.py`) and an SRE agent (`phases/p21_sre_agent/`).

How good the generated output is for a given requirement: not measured. Generation time: not measured.

---

## The Pipeline

`orchestrator/phase_sequence.py` defines 12 stages. A stage supervisor runs its own subset of the phase agents in `phases/`. The phase directories are not run one by one by the orchestrator (`orchestrator/phase_sequence.py:1-8`).

| Stage | Name | Purpose (from `orchestrator/phase_sequence.py`) |
|---|---|---|
| `s01_intake` | Intake | Requirements, domain research, past-run archaeology |
| `s02_architecture` | Architecture | Domain IR, permission model, project scaffold |
| `s03_backend` | Backend | FastAPI models, CRUD, business logic, integrations |
| `s04_frontend` | Frontend | React / Vite / TanStack and conditional platform outputs |
| `s05_quality` | Quality gate | Security scan, Z3 proofs, artifact scoring |
| `s06_testing` | Testing | Unit, performance, accessibility, E2E |
| `s07_healing` | Self-healing | Health probe and repair loop |
| `s08_observability` | Observability | Prometheus, Grafana, Sentry, analytics, alerting |
| `s09_devops` | DevOps | CI/CD, Docker, Kubernetes manifests, Helm, Terraform |
| `s10_enterprise` | Enterprise | Feature flags, A/B, memory, IAM, billing, SRE agent |
| `s11_handoff` | Handoff | Docs, client portal, Postman, delivery ZIP |
| `s12_specialist` | Specialist | Mobile, desktop, CLI, serverless (conditional) |

Stages `s01`, `s02` and `s03` abort the run when they fail. The other stages are non-critical and produce partial output (`orchestrator/phase_sequence.py:19-24`).

Phase agent directories: `ls phases | grep -c '^p[0-9]'` (49 at this commit). Some of them are listed as inactive or removed in `INACTIVE_PHASE_DIRS` in the same file. There is no `p00a_intake` phase: its directory is gone and the name only remains in that exclusion set.

The self-healing phase `p07b_self_healing` tries up to 5 fix attempts (`MAX_ATTEMPTS = 5`, `phases/p07b_self_healing/task_agent.py:39`).

The formal pipeline spec is `docs/PIPELINE_SPEC.md`. It was not checked as part of this file.

---

## Core Systems

### Model Router (`core/model_router.py`, `core/model_router_providers.py`)

`get_fallback_chain()` builds the provider chain from environment variables (`core/model_router_providers.py:76-157`):

- `PRIMARY_LLM` picks the first provider. The default is `bedrock`.
- With `bedrock` as primary the order is: Bedrock heavy model, Bedrock fallback model, then Anthropic and Gemini if configured, then OpenRouter models if `OPENROUTER_FALLBACK_MODELS` or `OPENROUTER_HEAVY_MODEL` is set, then Ollama.
- Each entry has one attempt (`retry_count` 1). Timeouts: Anthropic 60 s, Gemini 45 s, OpenRouter 60 s, Bedrock `BEDROCK_TIMEOUT` (default 60 s), Ollama `OLLAMA_TIMEOUT` (default 120 s).
- Default models: `ANTHROPIC_MODEL` = `claude-sonnet-4-6`, `BEDROCK_MODEL_HEAVY` = `us.amazon.nova-pro-v1:0`, `BEDROCK_MODEL_FALLBACK` = `us.meta.llama3-3-70b-instruct-v1:0`, Gemini `gemini-2.5-flash`, `OLLAMA_MODEL` = `qwen2.5-coder:3b`.
- `OFFLINE_MODE=true` restricts the chain to Ollama only (default model `llama3.1:8b`, timeout 300 s).
- Errors matching `_RETRY_PATTERNS` are retried. Errors matching `_FALLBACK_PATTERNS` move to the next provider. A provider that keeps failing is marked dead for a period (`_mark_provider_dead`). Organisations can override the chain (`_apply_org_chain_overrides`).

### Compliance and policy

- `core/compliance/code_scanner.py` (560 lines): scans generated FastAPI routes for an auth dependency, input validation, rate limiting, audit logging and error handling. Findings carry a framework label. The frameworks named in the code are HIPAA, GDPR, SOC2 and PCI-DSS (`core/compliance/code_scanner.py:34`).
- `core/policy/compliance.py` (487 lines): `ComplianceEngine` with rules for export and embargo checks, data residency, high-risk AI use, crypto strength and sensitive data. It does not contain GDPR, HIPAA, PCI-DSS or SOC2 rules.
- `core/policy/compliance_india.py` (245 lines): rules for DPDP, RBI, SEBI and CERT-In.
- `core/policy/engine.py` (389 lines): `AetherPolicyEngine` with a `PolicyConfig` and an `org_profile` setting. Separate from this, `core/policy/rules.py` defines the role ranks and plan entitlements the gateway enforces.

These checks are automated rules. They do not make a generated app compliant with any law or standard, and no audit or certification has been done: not measured.

### Domain Knowledge (`core/domain_knowledge/`)

Twelve domain packs live in `core/domain_knowledge/packs/`: `healthcare`, `fintech`, `ecommerce`, `erp`, `saas`, `logistics`, `trading`, `legaltech`, `real_estate`, `manufacturing`, `edtech`, `govtech`. Each pack defines entity templates with field flags, workflow state machines, compliance rules and business process pipelines. Read the pack file for the exact entities and rules. `DomainKnowledgePack.to_dict_full()` (`core/domain_knowledge/base.py`) produces the data for `domain_knowledge.json`.

### Quality Metrics (`core/quality/metrics.py`)

`score_project()` returns 0 to 100. The weights are in `core/quality/metrics.py:404-424`: auth coverage 25%, input validation 25%, test coverage 10%, domain specificity 5%, seed quality 5%, Docker presence 5%, Bandit result 5%. Then bonus points: Docker 8, README 6, `.env.example` 5, frontend 6, compliance report 5. The total is capped at 100.

### LLM Council (`core/council/council.py`)

Classes: `PreFlightCouncil`, `BackendAuditCouncil`, `FrontendAuditCouncil`, `DeliveryCouncil`. `COUNCIL_ENABLED` defaults to true. `COUNCIL_STRICT_MODE` defaults to true when `ENVIRONMENT=production` and false otherwise (`core/council/council.py:109-112`); `docker-compose.yml:69` also sets it to "true". When strict, a failed check blocks the operation.

### Guardian (`core/guardian/`)

- `snapshot_manager.py`: database snapshots, `GUARDIAN_MAX_SNAPSHOTS` kept (default 10).
- `watchdog.py`: background loop. Service health and brute-force scan every 30 s, file integrity every 5 min, snapshot every 6 h.
- `threat_detector.py`, `auto_recovery.py`: threat events and restore from snapshot.
- `password_shield.py`: checks passwords against the HaveIBeenPwned range API.

### Intelligence engines (`core/intelligence/`)

`ArchGovernor`, `TruthEngine`, `ConflictResolver`, `TradeoffEngine`, `ImprovementLoop`, `MaintenanceEngine`. One class per file; see the module docstring of each.

### Sandbox (`core/sandbox/`)

Generated code runs through `SandboxRunner`, chosen by `AETHER_SANDBOX` (`core/sandbox/runner.py:158`). A Docker backend (`docker_backend.py`) and a macOS `sandbox-exec` backend (`macos_backend.py`) exist. In production only `docker` is allowed. `none` needs `AETHER_SANDBOX_ALLOW_NONE=1` and is for development only.

### Plugins (`core/plugins/`)

`registry.py` (plugin manifests and installs), `connectors.py` and `connectors_registry.py` (connector classes), `skills.py` (skill classes). They back the `/v2/plugins/*` routes.

### Capacity planner (`core/capacity_planner/planner.py`)

HPA targets by `performance_tier` (`planner.py:22-26`):

| Tier | CPU target | Min replicas | Max replicas |
|---|---|---|---|
| `standard` | 70% | 2 | 10 |
| `high_throughput` | 60% | 3 | 50 |
| `real_time` | 50% | 5 | 100 |
| `batch` | 80% | 1 | 20 |

---

## Platform Features (the gateway)

- Authentication: RS256 JWT when RSA keys are configured, HS256 with `AETHER_SECRET_KEY` as a fallback for CI and tests (`gateway/auth.py:43-110`). API keys start with `aesk_`. MFA with TOTP (`gateway/auth_mfa.py`). SAML (`gateway/auth_saml.py`), GitHub and Google OAuth (`gateway/auth_oauth.py`). SCIM users and groups (`gateway/routers/scim_router.py`, `scim_groups_router.py`).
- Multi-tenancy: tokens carry `org_id`, and run routes check the run belongs to the caller's organisation (`gateway/dependencies.py`, `assert_run_in_org`). The `X-Org-ID` header is only used to tag log lines (`gateway/api_helpers.py:116`); it does not grant access.
- Roles and policy: central role floor in `gateway/role_gate.py`, policy decisions in `core/policy/`.
- Billing: Razorpay (`gateway/routers/billing_router.py`) and Stripe (`billing_stripe_router.py`).
- Encryption at rest: some model columns use `EncryptedText`, a Fernet-based column type (`core/encryption.py`, used in `core/models.py`).
- Audit: `core/audit/ledger.py` (`DecisionLedger`) with hash-chain and anchoring modules.
- Rate limits: see `API_REFERENCE.md`.
- Memory: ChromaDB vector store (`core/memory/vector_store.py`), knowledge graph (`core/memory/knowledge_graph.py`).
- Static analysis: Bandit runs in the quality score (`core/quality/metrics.py:321`) and in phase p06 (`phases/p06_review_security/task_agent.py`). Semgrep is not run by any code; `requirements.txt:80-81` only says to install it separately.
- Developer tooling: Monaco editor routes, env var editing and `run-app` (see `API_REFERENCE.md`), a VS Code extension in `vscode-extension/`, and the CLI below.

---

## Architecture

```
React dashboard (dashboard/)
        |  HTTPS
FastAPI gateway (gateway/api.py, routers in gateway/routers/)
        |
Orchestrator (orchestrator/factory_pipeline.py, phase_sequence.py)
        |
12 stage supervisors (stages/s01 .. s12) -> phase agents (phases/)
        |
Generated project output
```

Infrastructure: PostgreSQL (asyncpg, SQLAlchemy async, Alembic) and Redis.
Router modules: `ls gateway/routers | grep -c _router.py` (72 at this commit).
Routes: see `API_REFERENCE.md` (generated from the live app).

---

## Quick Start

### Docker Compose

```bash
git clone <repo> aether_os
cd aether_os
cp .env.example .env
# Set at least the values that docker-compose.yml marks as required:
#   POSTGRES_PASSWORD, REDIS_PASSWORD, CORS_ORIGINS, FRONTEND_URL
# and the secrets main.py checks at start: AETHER_SECRET_KEY, AETHER_ONE_ZT_SECRET
# and one LLM provider, for example ANTHROPIC_API_KEY or AWS Bedrock credentials.
docker compose up -d
cd dashboard && npm install && npm run build && cd ..
curl http://localhost:8000/health
```

`docker-compose.yml` defines the services `db`, `redis`, `migrate`, `api`, `preview` and `velaris_public`. The `api` service publishes port 8000. The image starts `uvicorn aether_os.gateway.api:create_app --factory` with 4 workers (`Dockerfile:51`).

### Local Python

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then edit it
alembic upgrade head
uvicorn gateway.api:app --host 0.0.0.0 --port 8000 --reload
cd dashboard && npm install && npm run build
```

Set `DATABASE_URL` (PostgreSQL, `postgresql+asyncpg://...`) and `REDIS_URL` for a real setup. In development without Redis the rate limiters fall back to per-process memory (`core/api_rate_limit.py`).

### First admin user

`core/seed.py` creates an admin user at startup only when both `AETHER_ADMIN_EMAIL` and `AETHER_ADMIN_PASS` are set (`core/seed.py:20-34`). `AETHER_ADMIN_PASSWORD` is not read by the application. It appears only in `.github/workflows/ci.yml:42`. `AETHER_ADMIN_USER` and `RETRIEVER` are read nowhere.

### CLI

```bash
pip install -e cli/
aether --help
aether login
aether run "Build an appointment booking system for a clinic"
aether ls
aether status <run_id>
aether logs <run_id>
aether download <run_id>
aether cancel <run_id>
aether open <run_id>
aether config
aether health
aether whoami
aether logout
```

The commands are defined in `cli/aetheros.py` (`login`, `logout`, `whoami`, `run`, `ls`, `status`, `logs`, `cancel`, `download`, `open`, `config`, `health`). The entry point is `aether=cli.aetheros:main` (`cli/setup.py`). There is no `artifacts` command; use `download`.

### Smoke test

```bash
./scripts/smoke_test.sh http://localhost:8000
```

---

## Project Structure

```
aether_os/
  gateway/        FastAPI app, auth, SAML, MFA, OAuth; routers/ has the route modules
  orchestrator/   factory_pipeline.py, phase_sequence.py, message bus
  stages/         s01 .. s12 stage supervisors
  phases/         phase agents (pNN_* directories)
  core/           shared logic: compliance, policy, domain_knowledge, quality, council,
                  guardian, intelligence, sandbox, plugins, memory, billing, audit,
                  identity (portal access, zero trust), notifications, model_router*.py,
                  stack_profiles.py
  dashboard/      React 19 + Vite + Tailwind frontend
  cli/            `aether` CLI (Typer + Rich)
  vscode-extension/
  agents/
  tests/          pytest tests
  deploy/         nginx, systemd units, deploy and setup scripts, kubernetes, terraform
  alembic/        database migrations
  scripts/        smoke_test.sh, post-deploy.sh, db_migrate.py and others
  docs/           further documents
  docker-compose.yml
```

---

## Tech Stack (from `requirements.txt` and `dashboard/package.json`)

| Layer | Technology |
|---|---|
| API | FastAPI >= 0.110, Uvicorn, Pydantic >= 2.5 |
| Database | PostgreSQL via asyncpg, SQLAlchemy async, Alembic. SQLite via aiosqlite for local development |
| Cache and queues | Redis |
| Auth | PyJWT, passlib with bcrypt, pyotp, python3-saml |
| LLM providers | Anthropic, AWS Bedrock, Google Gemini (google-genai), OpenRouter, Ollama |
| Tracing | LangSmith |
| Code generation | cookiecutter and LLM-written code |
| Static analysis | Bandit (Semgrep is optional and not run by the code) |
| Formal verification | z3-solver |
| Testing | pytest, Playwright, Locust, Hypothesis |
| Frontend | React 19, Vite 8, Tailwind CSS 4, TanStack Query |
| Memory | ChromaDB |
| Payments | Razorpay, Stripe |
| Errors and logs | sentry-sdk, structlog |
| CLI | Typer, Rich |
| Deployment | systemd, nginx, Docker |

---

## Tests

Test files: `find tests -name 'test_*.py' | wc -l` (217 at this commit). The number of test cases: not measured here. Coverage: CI runs `pytest tests/ --cov=. --cov-fail-under=$COVERAGE_FLOOR` and the floor is 50 (`.github/workflows/ci.yml:49,91-98`). Actual coverage: not measured here.

CI runs on push to `main` and `dev` and on pull requests to `main` (`.github/workflows/ci.yml:3-7`).

```bash
pytest tests/ --timeout=300 -q
```

---

## License

Proprietary. All rights reserved. Unauthorized use, reproduction, or distribution is prohibited.
