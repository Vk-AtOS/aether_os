# Show HN: AetherOS — I built an AI factory that turns a plain-English prompt into a deployed app

---

## Submission Text

**Show HN: AetherOS — I built an AI factory that turns a plain-English prompt into a deployed app**

I've been building AetherOS for the past few months. The idea: you submit a business requirement in plain English, and a 20-phase autonomous pipeline produces a production-ready codebase — with auth, tests, a CI pipeline, a Dockerfile, and a client-facing portal — no human in the loop for the mechanical parts.

**What it actually does**

The pipeline runs these phases in sequence, with a quality gate between each:

1. **p01 Intake** — Parses the requirement into a structured PRD using Claude Sonnet 4.6
2. **p02 Architecture** — Generates ER diagrams and tech stack decisions
3. **p03 Scaffolding** — Creates the project directory from a cookiecutter template
4. **p04 Backend** — Generates FastAPI routes, SQLAlchemy models, JWT auth
5. **p05 Frontend** — Generates React 18 TypeScript components with TanStack Query
6. **p06 Review and Security** — Runs Bandit and Semgrep on the generated code
7. **p07 Testing** — Generates and *executes* pytest + Playwright tests
8. **p07b Self-Healing** — If tests fail, patches the code and re-runs (up to N iterations)
9. **p08 CI/CD** — Creates a GitHub Actions workflow and Dockerfile
10. **p09–p14** — Observability, docs, deployment, monitoring, feature flags, A/B testing, app memory, client portal

Each gate has a confidence threshold. The orchestrator never proceeds if a gate fails — it either triggers self-healing or surfaces the failure to the operator.

**What the output looks like**

For "Build a SaaS CRM with contact management and a deal pipeline", the output is:
- FastAPI app with Contact, Deal, Activity SQLAlchemy models
- JWT auth with role-based access (manager, sales_rep)
- React frontend with Kanban board
- pytest suite with 80%+ coverage (actually executed, not just generated)
- GitHub Actions CI pipeline
- Dockerfile and docker-compose
- Prometheus metrics endpoint
- Standalone client portal (shareable URL, no login required)

**Architecture decisions I'm happy to explain**

- **MessageBus**: phases communicate exclusively through Redis RPUSH/BLPOP. The orchestrator never calls phase logic directly — it only reads and writes to the bus. This makes phases independently testable and swappable.
- **Multi-tenancy**: every DB query filters by `org_id`. An `X-Org-ID` header is enforced in middleware. A failing row-level check is a 403, not a data leak.
- **LLM routing**: Anthropic Claude primary → Google Gemini secondary → OpenRouter → Ollama. Each tier is gated behind an env var. Failover is automatic within a phase; the system doesn't retry across phases.
- **Sandbox**: generated code that runs (in p07 testing and FDE run-app) goes through a sandbox guard that strips dangerous imports and blocks filesystem writes outside the project directory.
- **Self-healing loop**: p07b runs a patch agent that reads the failing test output, generates a targeted fix, applies it, and re-runs the test. It has a configurable iteration limit to prevent infinite loops.

**Limitations I want to be honest about**

- Generated code quality varies by complexity. Simple CRUD apps come out clean. Complex state machines or real-time features may need manual review.
- The pipeline takes 5–15 minutes per full run, depending on app size and LLM latency. It's not interactive.
- Self-healing works well for straightforward test failures. It struggles with architectural issues that require rethinking multiple files simultaneously.
- LLM costs per run are $0.40–$1.20 at current Anthropic/Google pricing. Not free.
- Currently supports FastAPI (backend) and React/TypeScript (frontend). Other stacks are on the roadmap.

**Tech stack of AetherOS itself**

FastAPI + SQLAlchemy async 2.0 + PostgreSQL + Redis + React 18 + TypeScript + Vite + Tailwind. Full list in README.

The live demo is at https://139.59.87.218 (demo@aetheros.ai / demo1234). The VPS is a 4-core/8GB DigitalOcean droplet. It will fall over under heavy concurrent load — this is a demo, not a production cluster.

Source is proprietary for now but I'm happy to open-source specific components (the MessageBus, the gate evaluation framework, the sandbox guard) if there's interest.

**What I'd love feedback on**

- The gate confidence scoring model — currently a weighted combination of LLM self-evaluation and static analysis results. Is this the right approach?
- The self-healing architecture — should p07b have write access to the full project, or only to files implicated by failing tests?
- Multi-LLM routing — is per-phase model selection (some phases use heavy Claude, others use Gemini Flash) the right granularity, or should this be per-task-type within a phase?
