# AetherOS

AetherOS is an autonomous, multi-tenant software factory that transforms a natural-language prompt into a fully scaffolded, tested, documented, and deployed application through a supervised 21-phase pipeline.

---

## The 21-Phase Pipeline

Each phase is an independent module. All inter-phase communication is routed exclusively through the MessageBus. The orchestrator never calls phase logic directly.

| Phase | Name | Description |
|-------|------|-------------|
| p01 | Intake & Requirements | Parses raw user input into a structured PRD; promotes raw text if LLM sub-task fails |
| p02 | Architecture | Generates system architecture, entity-relationship diagrams, and technology decisions |
| p02b | Domain IR | Emits an intermediate representation of the detected domain, compliance notes, and entity graph used by downstream phases |
| p03 | Scaffolding | Creates project directory structure, cookiecutter templates, and boilerplate |
| p04 | Backend | LLM-driven code generation for API routes, models, auth, and database layer |
| p05 | Frontend | Generates React/TypeScript UI components, pages, and routing |
| p06 | Review & Security | Static analysis (Bandit, Semgrep), code review, and vulnerability triage |
| p07 | Testing | Unit, integration, performance (Locust), E2E (Playwright), and accessibility (axe) tests |
| p07b | Self-Healing | Automated fix loop: re-runs failing tests and patches code until gate passes |
| p08 | CI/CD & Deployment | GitHub Actions workflow generation, Docker build, container readiness probe |
| p09 | Observability | Prometheus metrics, structured logging (structlog), OTEL instrumentation |
| p10 | Docs & Delivery | pdoc API docs, architecture diagrams, README generation, artifact packaging |
| p11 | Deployment | Docker build and live container run; delivers a reachable URL |
| p11a | Monitoring | Prometheus scrape config, Grafana dashboard provisioning |
| p11b | Error Tracking | Sentry DSN wiring, structlog integration, alert rules |
| p11c | Analytics | PostHog event tracking, session recording config, dashboard JSON |
| p11d | Alerting | Alertmanager rules, on-call runbooks, PagerDuty/Slack webhook config |
| p12a | Feature Flags | Unleash client integration, flag definitions, gradual-rollout config |
| p12b | A/B Testing | GrowthBook experiment setup, metrics binding, results schema |
| p13 | App Memory | mem0 memory layer wiring, ChromaDB vector store, knowledge graph seeding |
| p14 | Client Portal | Standalone read-only portal for client review, approval, and feedback |

---

## Key Capabilities

- **Multi-tenant**: every resource is scoped to `org_id`; `X-Org-ID` header enforced in middleware
- **Compliance engines**: domain-aware GDPR / HIPAA / PCI-DSS / SOC2 guardrails evaluated at intake and CI/CD phases
- **FDE (Full Development Environment)**: Monaco editor in-browser, env-var management, `run-app` process manager, VS Code open-in-editor integration
- **VS Code extension**: sidebar panel with live pipeline status, artifact browser, and one-click open
- **CLI**: `aether` command (Typer + Rich) for starting runs, streaming logs, and downloading artifacts from the terminal
- **Redis message bus**: RPUSH/BLPOP primary; asyncio.Queue fallback for single-process mode
- **Intelligence engines**: Arch Governor, Truth Engine, Conflict Resolver, Tradeoff Engine, Improvement Loop, Maintenance Engine
- **SCIM v2**: automated user provisioning for enterprise IdPs
- **Billing**: Razorpay (India) + Stripe (international) dual-provider; order creation, payment verification, subscription management, and webhook processing; plan-gated feature access
- **Audit ledger**: append-only log of all pipeline events per org

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Gateway | FastAPI 0.110+, Uvicorn |
| Data validation | Pydantic v2 |
| Database (platform) | PostgreSQL (asyncpg) + SQLAlchemy async 2.0 + Alembic |
| Database (generated apps) | SQLite (aiosqlite) — see Generated Output doc |
| Cache / Message Bus | Redis 5+ (asyncio) |
| Auth | python-jose JWT, passlib/bcrypt, pyotp (TOTP MFA), python3-saml (SSO) |
| LLM Tier 1 | Anthropic claude-sonnet-4-6 |
| LLM Tier 2 | Google Gemini 2.5 Flash (google-genai) |
| LLM Fallback | Ollama via HTTP / OpenRouter |
| Agent frameworks | Native multi-model routing (core/model_router.py); LangSmith tracing |
| Code generation | cookiecutter, aider-chat |
| Security scanning | Bandit, Semgrep |
| Testing | pytest, Playwright, Locust, Hypothesis |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Memory | mem0ai, ChromaDB |
| Feature flags | UnleashClient |
| A/B testing | GrowthBook |
| Analytics | PostHog |
| Error tracking | Sentry SDK |
| Observability | Prometheus, structlog, LangSmith |
| CLI | Typer, Rich |
| Deployment | systemd, nginx, certbot (TLS), Docker |

---

## Quick Start

```bash
# 1. Clone and install
git clone <repo> aether_os
cd aether_os
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Set at minimum:
#   AETHER_SECRET_KEY=<random 64-char hex>
#   DATABASE_URL=postgresql+asyncpg://user:pass@localhost/aetheros
#   REDIS_URL=redis://localhost:6379
#   ANTHROPIC_API_KEY=sk-ant-...

# 3. Apply migrations
alembic upgrade add_pipeline_run_checkpoint

# 4. Start the server
uvicorn gateway.api:app --host 0.0.0.0 --port 8000 --reload

# 5. (Optional) CLI
pip install -e cli/
aether --help
```

The React dashboard is served at `/dashboard` from `dashboard/dist/`. Build it with:

```bash
cd dashboard && npm install && npm run build
```

---

## Project Structure

```
aether_os/
├── gateway/           # FastAPI application, routers, auth, SAML, MFA
│   └── routers/       # Modular route files (factory, auth, plugins)
├── orchestrator/      # Pipeline orchestrator, MessageBus, state machine, routing
├── phases/            # 21 phase modules (supervisor + task agent + gate per phase)
│   ├── p01_intake_requirements/
│   ├── p02_architecture/
│   ├── p02b_domain_ir/
│   └── ... (p03–p14)
├── core/              # Shared business logic
│   ├── compliance/    # Artifact generator (compliance_report.json)
│   ├── policy/        # ComplianceEngine, export controls
│   ├── llm/           # Model router (Anthropic → Gemini → OpenRouter → Ollama)
│   ├── services/      # PipelineService, domain engine
│   ├── identity/      # User, Org, RBAC models
│   ├── billing.py     # Razorpay integration
│   ├── audit/         # Append-only audit ledger
│   └── notifications/ # Email + in-app notification dispatch
├── dashboard/         # React 18 + Vite + Tailwind frontend
├── cli/               # `aether` CLI (Typer + Rich)
├── vscode-extension/  # VS Code sidebar extension
├── agents/            # Standalone agent definitions
├── tests/             # pytest test suite
├── deploy/            # nginx.conf, systemd unit, deploy.sh, setup_vps.sh
├── alembic/           # Database migration scripts
├── requirements.txt   # Python dependencies (pinned minimums)
└── docker-compose.yml # Local development stack
```

---

## License

Proprietary. All rights reserved. Unauthorized use, reproduction, or distribution is prohibited.
