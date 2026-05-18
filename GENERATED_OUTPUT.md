# AetherOS — Generated Output Guide

This document describes what a completed AetherOS pipeline run produces. All output is written to a per-run directory on the server filesystem. The full directory is available as a ZIP download via `GET /factory/runs/{run_id}/download`.

---

## Output Files Per Phase

| Phase | Output files |
|-------|-------------|
| p01_intake_requirements | `intake/intake.json`, `consolidated.json` |
| p02_architecture | `architecture/architecture.md`, `architecture/erd.md`, `architecture/adrs.md` |
| p03_scaffolding | Full project skeleton (see below), `Dockerfile`, `docker-compose.yml`, `.env.example` |
| p04_backend | `src/main.py`, `src/models.py`, `src/database.py`, `src/auth.py`, `src/routers/`, `requirements.txt`, `alembic/` |
| p05_frontend | `frontend/src/`, `frontend/package.json`, `frontend/vite.config.ts` |
| p06_review_security | `scan_report.json` |
| p07_testing | `tests/`, `test_report.json`, `coverage/`, `performance_baseline.json` |
| p07b_self_healing | Updated source files (patches applied), `healing_log.json` |
| p08_cicd_deployment | `ci.yml`, `devcontainer.json`, `Dockerfile` (updated if needed) |
| p09_observability | `prometheus.yml`, `grafana_dashboard.json`, `logging.py` |
| p10_docs_delivery | `docs/`, `README.md`, `CHANGELOG.md`, `architecture_diagram.png`, `artifact.zip` |
| p11_deployment | `deployment_manifest.json` (container ID, port, live URL) |
| p11a_monitoring | `monitoring/prometheus_scrape.yml`, `monitoring/grafana_panels.json` |
| p11b_error_tracking | `monitoring/sentry_config.py`, `monitoring/alert_rules.yml` |
| p11c_analytics | `analytics/posthog_config.py`, `analytics/event_schema.md` |
| p11d_alerting | `alerting/alertmanager_rules.yml`, `alerting/runbooks/` |
| p12a_feature_flags | `feature_flags/unleash_config.py`, `feature_flags/flags.yml` |
| p12b_ab_testing | `ab_testing/growthbook_config.py`, `ab_testing/experiments.json` |
| p13_app_memory | `memory/mem0_config.py`, `memory/knowledge_graph_seed.json` |
| p14_client_portal | `portal/index.html`, `portal/assets/`, `portal/approval_config.json` |

---

## Example Project Structure: "SaaS CRM"

A completed run for a SaaS CRM application produces this file tree:

```
run_a1b2c3d4/
├── intake/
│   ├── intake.json
│   └── consolidated.json
├── architecture/
│   ├── architecture.md
│   ├── erd.md
│   └── adrs.md
├── src/
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   ├── auth.py
│   ├── routers/
│   │   ├── contacts.py
│   │   ├── deals.py
│   │   └── emails.py
│   └── schemas.py
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Contacts.tsx
│   │   │   ├── Deals.tsx
│   │   │   └── Dashboard.tsx
│   │   ├── components/
│   │   └── api/
│   │       └── client.ts
│   ├── package.json
│   └── vite.config.ts
├── tests/
│   ├── test_contacts.py
│   ├── test_deals.py
│   ├── test_auth.py
│   └── e2e/
│       └── test_crm_flow.py
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
├── monitoring/
│   ├── prometheus_scrape.yml
│   └── grafana_panels.json
├── analytics/
│   └── posthog_config.py
├── alerting/
│   ├── alertmanager_rules.yml
│   └── runbooks/
│       └── high_error_rate.md
├── feature_flags/
│   ├── unleash_config.py
│   └── flags.yml
├── ab_testing/
│   └── experiments.json
├── memory/
│   └── mem0_config.py
├── portal/
│   └── index.html
├── docs/
│   └── index.html
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── ci.yml
├── devcontainer.json
├── requirements.txt
├── README.md
├── CHANGELOG.md
├── scan_report.json
├── test_report.json
├── compliance_report.json
└── architecture_diagram.png
```

---

## main.py — What's Inside

The generated `src/main.py` is a self-contained FastAPI application:

```python
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .auth import get_current_user, router as auth_router
from .routers import contacts, deals, emails

app = FastAPI(title="AcmeCRM", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
app.include_router(deals.router, prefix="/deals", tags=["deals"])
app.include_router(emails.router, prefix="/emails", tags=["emails"])

@app.get("/health")
async def health():
    return {"status": "ok"}
```

The routers implement standard CRUD operations. Auth uses JWT with `python-jose`. All data access is through SQLAlchemy async sessions.

---

## Generated requirements.txt

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.5.0
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
alembic>=1.13.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.6
python-dotenv>=1.0.0
httpx>=0.25.0
```

Versions are minimum-pinned. The generated app is tested against these versions during p07.

---

## compliance_report.json

Produced by `core/compliance/artifact_generator.py`. Structure:

```json
{
  "run_id": "run_a1b2c3d4",
  "generated_at": "2026-05-19T10:06:00Z",
  "domain": "saas",
  "compliance_flags": ["GDPR", "SOC2"],
  "context": {
    "country_code": "DE",
    "region": "EU",
    "handles_personal_data": true,
    "handles_biometric_data": false,
    "industries": ["saas"],
    "high_risk_use_cases": []
  },
  "checks": [
    {
      "check_id": "GDPR_DATA_RESIDENCY",
      "passed": true,
      "severity": "high",
      "notes": "Deployment region is EU-compatible"
    },
    {
      "check_id": "CRYPTO_WEAK",
      "passed": true,
      "severity": "critical",
      "notes": "No weak crypto patterns detected in generated code"
    }
  ],
  "overall_passed": true,
  "disclaimer": "This report is not a substitute for legal advice."
}
```

---

## scan_report.json — p06 Security Scan

```json
{
  "run_id": "run_a1b2c3d4",
  "generated_at": "2026-05-19T10:02:30Z",
  "tools": ["bandit", "semgrep"],
  "summary": {
    "critical": 0,
    "high": 1,
    "medium": 3,
    "low": 7,
    "info": 12
  },
  "findings": [
    {
      "tool": "bandit",
      "rule_id": "B105",
      "severity": "high",
      "file": "src/auth.py",
      "line": 42,
      "message": "Hardcoded password string detected",
      "fix_applied": true,
      "fix_description": "Replaced with os.environ.get('SECRET_KEY')"
    }
  ],
  "gate_passed": true,
  "notes": "1 HIGH finding auto-remediated by p07b self-healing"
}
```

---

## devcontainer.json — VS Code Dev Container

```json
{
  "name": "AcmeCRM Dev Container",
  "image": "mcr.microsoft.com/devcontainers/python:3.11",
  "features": {
    "ghcr.io/devcontainers/features/node:1": { "version": "20" }
  },
  "postCreateCommand": "pip install -r requirements.txt && npm install --prefix frontend",
  "forwardPorts": [8000, 5173],
  "portsAttributes": {
    "8000": { "label": "FastAPI backend" },
    "5173": { "label": "Vite frontend" }
  },
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "dbaeumer.vscode-eslint"
      ]
    }
  }
}
```

---

## ci.yml — GitHub Actions Workflow

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest tests/ --tb=short -q

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ruff bandit
      - run: ruff check src/
      - run: bandit -r src/ -ll

  build:
    runs-on: ubuntu-latest
    needs: [test, lint]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5
        with:
          push: false
          tags: acmecrm:latest
```

---

## Completeness and Production Readiness

A completed AetherOS run produces approximately **85% of what a production deployment requires**. The remaining 15% is intentionally left for human decision-making.

### What is complete and ready to use
- All CRUD endpoints with auth, input validation, and error handling
- Database schema and migration scripts
- Test suite (unit + integration + E2E skeleton)
- CI/CD pipeline definition
- Docker container (builds and passes readiness probe)
- Security scan with auto-remediation of common findings
- Observability wiring (Prometheus, Sentry, PostHog)
- Compliance report
- Documentation

### Known Limitations

**SQLite for data persistence**: Generated apps use SQLite by default. This is intentional — it eliminates the dependency on an external database and makes the app runnable immediately. For production workloads requiring horizontal scaling or concurrent writes, migration to PostgreSQL is required. The generated `alembic/` directory and `models.py` use SQLAlchemy ORM, making migration straightforward (`DATABASE_URL` env var swap + `alembic upgrade head`). This step is not automated.

**Business logic validation**: AetherOS generates structurally correct CRUD logic based on the requirements description. Domain-specific business rules (e.g., "a deal cannot move to Closed Won without an approved quote") require human review and implementation. The generated code provides the scaffolding; the developer fills in the constraints.

**No live payment processing**: If the domain is `fintech` or `ecommerce`, the generated code includes Razorpay/Stripe integration stubs with correct API call signatures. Actual keys, webhook verification secrets, and go-live compliance steps (PCI-DSS SAQ) are outside the scope of automated generation.

**Security findings require human sign-off**: The scan report and self-healing phase resolve common patterns (hardcoded secrets, SQL injection, insecure deserialization). Novel application-specific vulnerabilities require manual penetration testing before production deployment.

**No infrastructure provisioning**: AetherOS generates deployment artifacts (Dockerfile, CI pipeline, docker-compose) but does not provision cloud infrastructure. Terraform/Pulumi IaC generation is on the roadmap.
