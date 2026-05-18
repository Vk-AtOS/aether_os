# AetherOS — System Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          User / Client                                  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTPS
                    ┌───────────▼───────────┐
                    │   nginx reverse proxy  │
                    │   + certbot TLS        │
                    └───────────┬───────────┘
                                │
              ┌─────────────────┴──────────────────┐
              │                                    │
   ┌──────────▼──────────┐            ┌────────────▼───────────┐
   │  Dashboard (React)   │            │  CLI / API clients      │
   │  Vite + Tailwind     │            │  aether (Typer/Rich)    │
   └──────────┬──────────┘            └────────────┬───────────┘
              │                                    │
              └─────────────┬──────────────────────┘
                            │ REST + SSE (JWT Bearer)
                ┌───────────▼───────────────┐
                │   API Gateway (FastAPI)    │
                │   gateway/api.py           │
                │   ● CORS                   │
                │   ● JWT auth middleware    │
                │   ● X-Org-ID enforcement   │
                │   ● Rate limiting (slowapi)│
                │   ● Sentry instrumentation │
                └──────────┬────────────────┘
                           │
          ┌────────────────┼──────────────────┐
          │                │                  │
┌─────────▼──────┐  ┌──────▼──────┐  ┌───────▼───────┐
│ PipelineService│  │ Auth / RBAC │  │ Intelligence  │
│ (core/services)│  │ Billing     │  │ Engines       │
└─────────┬──────┘  └─────────────┘  └───────────────┘
          │
┌─────────▼──────────────────────────────────────────┐
│           Pipeline Orchestrator                     │
│           orchestrator/factory_pipeline.py          │
│           ● Loads supervisors dynamically           │
│           ● Routes via MessageBus                   │
│           ● State machine (PipelineStateMachine)    │
│           ● Gate evaluation per phase               │
│           ● Human approval escalation               │
└─────────┬──────────────────────────────────────────┘
          │  MessageBus (Redis RPUSH/BLPOP)
          │
┌─────────▼────────────────────────────────────────────────────────┐
│                    20-Phase Execution Layer                       │
│  p01 → p02 → p03 → p04 → p05 → p06 → p07 → p07b → p08 → p09   │
│  → p10 → p11 → p11a → p11b → p11c → p11d → p12a → p12b → p13   │
│  → p14                                                            │
│                                                                   │
│  Each phase: SupervisorAgent → TaskAgent → GateValidator         │
└─────────┬────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────┐    ┌─────────────────────────┐
│   Output Artifacts             │    │  Persistence             │
│   (filesystem per run_id)      │    │  PostgreSQL (asyncpg)    │
│   ● source code                │    │  Redis (state + SSE bus) │
│   ● compliance_report.json     │    │  SQLite (generated apps) │
│   ● scan_report.json           │    └─────────────────────────┘
│   ● ci.yml, devcontainer.json  │
│   ● docs/, tests/              │
└────────────────────────────────┘
```

---

## The 20-Phase Pipeline — Detail

The pipeline is defined in `PHASE_SEQUENCE` in `orchestrator/factory_pipeline.py`. Each phase is mapped to a supervisor class via `PHASE_SUPERVISORS`. Phases are loaded dynamically at runtime via `importlib`; adding a new phase requires no changes to the orchestrator.

### Phase Detail

**p01 — Intake & Requirements**
- Accepts: raw natural language prompt (and optional uploaded requirement doc / GitHub repo)
- Produces: `intake/intake.json` (structured PRD), `consolidated.json`
- Gate: validates `raw_text` is non-empty; if `structured_requirements` is empty, promotes `raw_text` as fallback so p02 always has input
- Domain engine runs here: detects `fintech`, `healthcare`, `saas`, `ecommerce`, etc. and injects compliance notes

**p02 — Architecture**
- Produces: architecture decision records (ADRs), entity-relationship model, technology stack selection, system context diagram
- Gate: checks architecture doc is non-empty and references at least one data model

**p03 — Scaffolding**
- Produces: full project directory tree, `pyproject.toml` / `package.json`, `Dockerfile`, `docker-compose.yml`, `.env.example`
- Uses cookiecutter templates parameterised by domain profile from p01

**p04 — Backend**
- Produces: `src/main.py` (FastAPI app), CRUD routers, SQLAlchemy models, Alembic migration, auth module, `requirements.txt`
- LLM generates code; aider-chat applies diffs cleanly

**p05 — Frontend**
- Produces: React TypeScript components, page routing, API client (axios), Tailwind CSS styling
- Gate: checks that at least one `.tsx` component file and a router entry exist

**p06 — Review & Security**
- Runs Bandit (Python AST security linter) and Semgrep (SAST rules)
- Produces: `scan_report.json` with findings, severity counts, fix suggestions
- Gate fails if any CRITICAL findings exist; HIGH findings generate warnings

**p07 — Testing**
- Runs: pytest unit/integration, Locust performance baseline, Playwright E2E, axe-playwright accessibility
- Produces: `test_report.json`, coverage report, performance baseline metrics
- Gate: overall pass rate ≥ 80%; no unhandled exceptions in E2E

**p07b — Self-Healing**
- If p07 gate fails, this phase re-runs failing tests, identifies root causes, patches code, and re-validates
- Maximum 3 healing iterations before escalating to human approval gate

**p08 — CI/CD & Deployment**
- Produces: `ci.yml` (GitHub Actions), `devcontainer.json`, `Dockerfile` (if not already present)
- Runs Docker build in sandbox; performs HTTP readiness probe on the container

**p09 — Observability**
- Wires Prometheus `/metrics` endpoint, OTEL tracing, structured logging (structlog)
- Produces: `prometheus.yml`, `grafana_dashboard.json`, logging config

**p10 — Docs & Delivery**
- Runs pdoc to generate HTML API documentation
- Produces: `README.md`, `CHANGELOG.md`, architecture diagram PNG (via `diagrams` library), artifact ZIP

**p11 — Deployment**
- Builds and runs Docker container; performs live HTTP readiness probe
- Produces: live URL, container ID, deployment manifest

**p11a — Monitoring**
- Produces: Prometheus scrape config, Grafana dashboard JSON with pre-built panels for latency/error rate/throughput

**p11b — Error Tracking**
- Wires Sentry SDK into generated app; configures `send_default_pii=False`
- Produces: Sentry project config, alert rules YAML

**p11c — Analytics**
- Instruments PostHog events (page views, feature interactions, funnels)
- Produces: PostHog config, event schema documentation

**p11d — Alerting**
- Produces: Alertmanager rules YAML, on-call runbooks (Markdown), Slack/PagerDuty webhook config

**p12a — Feature Flags**
- Integrates Unleash client; defines flag schema
- Produces: Unleash toggle definitions, SDK init code, documentation

**p12b — A/B Testing**
- Integrates GrowthBook; binds experiments to metrics
- Produces: GrowthBook config JSON, experiment definitions, results schema

**p13 — App Memory**
- Wires mem0 memory layer and ChromaDB vector store into the generated app
- Seeds initial knowledge graph from requirements and architecture docs

**p14 — Client Portal**
- Generates a standalone read-only web portal for client review
- Includes approval workflow, feedback form, and artifact download links

---

## Key Architectural Decisions

### Why FastAPI
FastAPI was chosen for its native async support (critical for non-blocking LLM calls), automatic OpenAPI schema generation, Pydantic v2 integration, and first-class dependency injection. The alternative (Django) would have required significant async adaptation.

### Why Redis Message Bus
The MessageBus (defined in `orchestrator/bus.py`) uses Redis RPUSH/BLPOP as the primary transport. This design means:
- Multiple worker processes can pick up phase work without coordination
- Pipeline state survives worker restarts (Redis persistence)
- SSE event streams are decoupled from the HTTP process

The asyncio.Queue fallback ensures the system works in single-process development mode when Redis is unavailable.

### Why SQLite for Generated Apps
Generated applications use SQLite by default. This keeps the generated code dependency-free and runnable immediately. The architecture document generated by p02 always includes a migration path to PostgreSQL; this is an intentional trade-off for time-to-first-run. See `GENERATED_OUTPUT.md` for limitations.

---

## MessageBus Design

```python
# orchestrator/bus.py — simplified

class MessageBus:
    """Per-run message bus. Redis primary; asyncio.Queue fallback."""

    async def publish(self, phase_name: str, message: PhaseMessage) -> None:
        if redis_available:
            await redis.rpush(f"aether:bus:{run_id}:{phase_name}", message.json())
        else:
            await self._queue.put(message)          # in-process fallback

    async def subscribe(self, phase_name: str) -> PhaseMessage:
        if redis_available:
            _, data = await redis.blpop(f"aether:bus:{run_id}:{phase_name}", timeout=300)
            return PhaseMessage.parse_raw(data)
        else:
            return await self._subscribers[phase_name].get()
```

Redis keys are namespaced as `aether:bus:{run_id}:{phase_name}` and carry a TTL of 3600 seconds.

---

## Multi-Tenancy

Every database model with user-generated data carries an `org_id` foreign key. Queries in `PipelineService` always include a `.where(Model.org_id == org_id)` clause. There are no cross-org data joins anywhere in the codebase.

The `org_id` is embedded in the JWT at login time. The gateway middleware extracts it and makes it available via the `get_current_user` dependency. No route needs to accept `org_id` from the request body or URL.

---

## Authentication

- **JWT**: `python-jose` with HS256. Access tokens expire in 15 minutes. Refresh tokens are long-lived, stored hashed in the database.
- **Refresh flow**: `POST /auth/refresh` accepts a refresh token, rotates it (old token is revoked), and returns a new access + refresh pair.
- **RBAC**: roles are `owner`, `admin`, `member`, `viewer`. Role checks are enforced via FastAPI dependencies in individual routes.
- **MFA**: TOTP (pyotp) — QR code provisioning + verification endpoint. Enforced at login for orgs with MFA required.
- **SAML SSO**: python3-saml integration. SP-initiated SSO flow with ACS endpoint. Metadata endpoint for IdP configuration.
- **SCIM v2**: `/scim/v2/Users` and `/scim/v2/Groups` for automated user provisioning from Okta, Azure AD, etc.
- **API Keys**: org-scoped, hashed at rest. Used by CLI and CI integrations.

---

## Compliance Engine

`core/policy/compliance.py — ComplianceEngine` takes a `ComplianceContext` (country code, region, data sensitivity, industries, high-risk use cases, crypto flags) and evaluates:

- **Export / embargo controls**: blocks or warns on sanctioned country codes
- **Data residency**: flags EU personal data destined for non-adequate third-country cloud regions
- **High-risk AI use cases**: biometric identification, surveillance, social scoring → mandatory human gate
- **Crypto controls**: weak crypto (MD5, SHA1, DES) in security-sensitive contexts → gate failure
- **GDPR**: triggered when `handles_personal_data=True` and `region=EU`
- **HIPAA**: triggered when `healthcare` is in `industries` and `handles_personal_data=True`
- **PCI-DSS**: triggered when `fintech` / `ecommerce` in `industries`

All checks are deterministic and produce a structured result that is logged to the audit ledger. The engine carries an explicit disclaimer: it is not a substitute for legal advice.

The domain engine in `core/domain_engine.py` pre-populates `ComplianceContext` fields from the detected domain, so compliance evaluation happens automatically at p01 without user intervention.

---

## Gate System

Every phase exposes a `gate.py` module with a `validate(result: TaskResult) -> GateOutcome` function. The `GateOutcome` carries:

```python
@dataclass
class GateOutcome:
    passed: bool
    confidence: float   # 0.0 – 1.0
    issues: List[str]
```

The orchestrator (`factory_pipeline.py`) calls `supervisor.validate_gate()` after every phase. If the gate fails:
1. The orchestrator consults the routing table (`orchestrator/routing/router.py`) to find the remediation phase
2. If a self-healing phase is available, it is queued
3. After `MAX_RETRIES` failures, a human approval ticket is created and the pipeline pauses
4. On approval, the pipeline resumes from the failed phase

---

## Full Development Environment (FDE)

The FDE turns the AetherOS dashboard into a lightweight IDE for the generated project:

| Endpoint | Function |
|----------|----------|
| `GET /factory/runs/{id}/file-content` | Read any file in the generated project |
| `PATCH /factory/runs/{id}/file-content` | Write file content from Monaco editor |
| `POST /factory/runs/{id}/open-in-vscode` | Open project folder in local VS Code via `code` CLI |
| `GET /factory/runs/{id}/envvars` | Read `.env` for the generated app |
| `PATCH /factory/runs/{id}/envvars` | Update env vars (written to `.env` on disk) |
| `POST /factory/runs/{id}/run-app` | Start the generated app process |
| `DELETE /factory/runs/{id}/run-app` | Stop the running process |

The Monaco editor is embedded in the dashboard's Artifacts tab. File saves are debounced and sent via `PATCH`. Process stdout is streamed back over SSE.

---

## Deployment

Production deployment is handled by `deploy/deploy.sh` and `deploy/setup_vps.sh`:

1. **systemd**: `aetheros.service` runs `uvicorn aether_os.gateway.api:create_app --factory` as a non-root user
2. **nginx**: reverse proxy config in `deploy/nginx.conf`; proxies `/api` to uvicorn, serves static files directly
3. **TLS**: certbot (`--nginx` plugin) obtains and auto-renews Let's Encrypt certificates
4. **PostgreSQL**: installed on the VPS or connected as a managed service
5. **Redis**: installed on the VPS (`redis-server`) or connected as a managed service (e.g. Redis Cloud)
6. **Zero-downtime deploys**: `deploy.sh` pulls new code, runs `alembic upgrade head`, restarts systemd service with `--no-block` and a health-check loop

The `docker-compose.yml` in the project root provides a local development stack (Postgres + Redis + app).
