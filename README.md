# AetherOS

AetherOS is an AI-powered software factory that transforms a plain-English requirement into a production-ready, compliance-verified, fully deployed application through a **39-phase autonomous pipeline** — the most phases of any known AI application generation system. The nearest competitor runs 8. In under 10 minutes, AetherOS generates backend API code, a React frontend, Kubernetes manifests, Helm charts, multi-region Terraform, an IAM layer, billing infrastructure, a compliance manifest with per-route audit trails, a machine-readable domain knowledge graph, and a self-healing SRE agent — all tailored to the detected business domain and its regulatory requirements.

---

## What It Generates

| Stack Profile | Backend | Frontend | Infrastructure | Use Case |
|---|---|---|---|---|
| `web_saas` | Python / FastAPI | React / Vite / TanStack | Docker Compose | Standard SaaS web app |
| `go_api` | Go / Gin | React | Kubernetes + Helm | High-performance REST API |
| `go_microservices` | Go / Gin (multi-service) | React | Kubernetes + Kafka | Distributed microservices |
| `node_api` | TypeScript / Express | React | Docker Compose | Node.js web app |
| `node_serverless` | TypeScript / Fastify | React | Serverless | Event-driven functions |
| `mobile_rn` | Python / FastAPI | React Native (Expo) | Docker Compose | Mobile apps |
| `desktop_electron` | Python / FastAPI | Electron | Native | Desktop apps |
| `ml_pipeline` | Python / FastAPI + Celery | React | Docker Compose | ML / AI services |
| `microservices` | Go / Gin (multi) | React | Kubernetes + Kafka | Full microservice mesh |
| `realtime_app` | Python / FastAPI | React | Docker Compose | Real-time apps (WebSocket) |
| `cloud_platform` | Python / FastAPI | React | Kubernetes | Full cloud platform |
| `cli_tool` | Python / Click | None | Native | CLI utilities |
| `java_enterprise` | Java / Spring Boot | React | Kubernetes | Enterprise Java |

Every generated project also ships:
- Kubernetes manifests and Helm charts
- Multi-region Terraform (AWS Global Accelerator + Route53 + VPC peering)
- IAM layer (OPA Rego policies + Keycloak realm JSON)
- Billing and metering infrastructure (OpenMeter + Stripe webhook handlers)
- CI/CD pipeline (GitHub Actions) with a compliance drift gate
- Prometheus + Grafana observability stack
- LitmusChaos chaos engineering experiments
- `compliance_manifest.json` — per-route compliance audit with SHA-256 drift fingerprint
- `domain_knowledge.json` — machine-readable domain graph with PHI/PCI/PII field tagging
- `business_model.json` — market sizing, pricing tiers, GTM strategy
- SRE agent (Kubernetes Operator) — domain-aware failure classification and self-healing

---

## The 39-Phase Pipeline

Each phase is an independent module. All inter-phase communication flows through a central `accumulated_context` dict managed by `orchestrator/factory_pipeline.py`. Critical phases abort the pipeline on failure; non-critical phases log and continue.

### Group 1 — Research and Classification (p00 – p00c)

| Phase | Name | What It Does |
|---|---|---|
| `p00_research` | Research and Spec Analysis | LLM-powered domain classification, stack profile selection via `BuildProfile`, optional web research, outputs `design_brief.json` and `build_profile` |
| `p00a_intake` | Multimodal Intake | Parses Figma JSON exports, architectural diagram images (Claude Vision), and voice memos (Whisper) into structured requirements |
| `p00b_data_archaeology` | Data Archaeology | Analyses existing data schemas and legacy system patterns for migration or integration projects |
| `p00c_architecture_planner` | Architecture Planner | For microservices builds: generates `service_map.json` defining per-service language, port, and communication protocol |

### Group 2 — Requirements and Domain IR (p01 – p02c)

| Phase | Name | What It Does |
|---|---|---|
| `p01_intake_requirements` | Intake and Requirements | Parses the spec into a structured PRD; promotes raw text if LLM sub-task fails; critical phase |
| `p01b_integration_discovery` | Integration Discovery | Detects third-party integrations (Stripe, Twilio, SendGrid) and emits `integration_map` |
| `p02_architecture` | Architecture Design | Generates system architecture, ER diagrams, and technology decisions using domain knowledge and build profile; critical phase |
| `p02b_domain_ir` | Domain IR Generation | Emits a typed intermediate representation of entities, relationships, and compliance annotations used by all downstream codegen phases |
| `p02c_permission_modeling` | Permission Modeling | Generates a `permission_model` mapping roles to resources; consumed by P04 and P16 |

### Group 3 — Code Generation (p03 – p05e)

| Phase | Name | What It Does |
|---|---|---|
| `p03_scaffolding` | Project Scaffolding | Creates directory structure, cookiecutter templates, and boilerplate |
| `p04_backend` | Backend Codegen | Routes to the appropriate language generator based on `build_profile.backend_lang`; critical phase |
| `p04a_backend_codegen` | Backend Codegen (extended) | Additional FastAPI code generation pass for complex entities |
| `p04b_business_logic` | Business Logic Layer | Reads `BusinessProcessPipeline` definitions from the domain pack and emits service orchestration code rather than bare CRUD |
| `p04c_integration_codegen` | Integration Clients | Generates typed HTTP clients for every integration in `integration_map` |
| `p05_frontend` | Frontend Codegen | React / Vite / TanStack Query frontend; routes to the correct framework per `build_profile.frontend_framework`; critical phase |
| `p05b_mobile` | Mobile (React Native) | Expo Router navigation, JWT auth in SecureStore, React Query, one screen per entity |
| `p05c_desktop` | Desktop (Electron) | Electron wrapper with IPC bridge to the FastAPI backend |
| `p05d_cli` | CLI Tool | Cobra (Go) or Click (Python) CLI with subcommands per entity |
| `p05e_serverless` | Serverless Functions | AWS Lambda or Cloudflare Workers handler generation |

### Group 4 — Security and Quality (p06 – p07d)

| Phase | Name | What It Does |
|---|---|---|
| `p06_review_security` | Security Review | LLM Council review + Bandit + Semgrep static analysis; writes `compliance_manifest.json` |
| `p06b_formal_verification` | Formal Verification | Z3 SMT-based invariant checking for JWT auth, RBAC role escalation, payment bounds, and PHI access; produces `verification_report.json` |
| `p07_testing` | Test Generation | Unit, integration, and E2E test generation |
| `p07a_unit_testing` | Unit Tests | Pytest unit tests per service |
| `p07b_self_healing` | Self-Healing | Automated fix loop: re-runs failing tests and patches code until the gate passes (up to 5 attempts) |
| `p07c_accessibility_testing` | Accessibility Testing | axe-core and WCAG 2.1 AA checks; govtech domain injects Section 508 rules |
| `p07d_e2e_testing` | E2E Testing | Playwright end-to-end test generation |

### Group 5 — CI/CD and Observability (p08 – p11e)

| Phase | Name | What It Does |
|---|---|---|
| `p08_cicd_deployment` | CI/CD Pipeline | GitHub Actions workflow with build, test, compliance drift gate, and container push |
| `p09_observability` | Observability Config | Prometheus scrape config, structured logging (structlog), OTEL instrumentation |
| `p10_docs_delivery` | Documentation | pdoc API docs, architecture diagrams, README generation, artifact packaging |
| `p11_deployment` | Docker Build and Deploy | Docker build, container health probe, live URL delivery |
| `p11a_monitoring` | Prometheus and Grafana | Prometheus scrape config, Grafana dashboard provisioning |
| `p11b_error_tracking` | Sentry and structlog | Sentry DSN wiring, structured logging, alert rules |
| `p11c_analytics` | PostHog Analytics | PostHog event tracking, session recording, dashboard JSON |
| `p11d_alerting` | Alertmanager and Runbooks | Alertmanager rules, on-call runbooks, PagerDuty / Slack webhook config |
| `p11e_enterprise_deployment` | Enterprise Deploy | Helm charts + multi-region Terraform |

### Group 6 — Product Instrumentation (p12a – p14)

| Phase | Name | What It Does |
|---|---|---|
| `p12a_feature_flags` | Feature Flags (Unleash) | Unleash client integration, flag definitions, gradual-rollout config |
| `p12b_ab_testing` | A/B Testing (GrowthBook) | GrowthBook experiment setup, metrics binding, results schema |
| `p13_app_memory` | App Memory Layer | mem0 memory layer wiring, ChromaDB vector store, knowledge graph seeding |
| `p14_client_portal` | Client Review Portal | Standalone read-only portal for client review, approval, and feedback |

### Group 7 — Enterprise and Operations (p15 – p21)

| Phase | Name | What It Does |
|---|---|---|
| `p15_handoff` | Technical Handoff | Complete technical handoff package with architecture docs and council review |
| `p16_iam` | IAM / OPA Policies | OPA Rego policy generator, Keycloak realm JSON generator |
| `p17_control_plane` | Kubernetes Operator | Kubernetes Operator + CRD YAML generator, Go controllers, RBAC manifests |
| `p18_billing_metering` | Billing and Metering | OpenMeter config, CloudEvents schema, Stripe webhook handler, metering middleware |
| `p19_service_catalog` | Service Catalog | Service catalog FastAPI router + React cloud console frontend |
| `p20_multiregion` | Multi-Region Deploy | AWS Global Accelerator + Route53 + VPC peering Terraform |
| `p21_sre_agent` | SRE Self-Healing Agent | Domain-aware Kubernetes Operator that classifies Prometheus alerts, generates remediations, runs canary tests, and applies fixes |

---

## Core Systems

### Model Router (`core/model_router.py`)

Three-tier LLM fallback chain with circuit-breaking per provider:

1. **Tier 1 — Anthropic** `claude-sonnet-4-6` (30 s timeout, 2 retries)
2. **Tier 1b — AWS Bedrock** Claude Sonnet or Amazon Nova Pro via IAM role
3. **Tier 2 — Google Gemini** `gemini-2.5-flash` (45 s timeout, 2 retries)
4. **Tier 3 — OpenRouter / Ollama** `qwen2.5-coder:3b` (90 s timeout, fallback)

The router classifies errors into *retry* (transient: rate limit, 429) vs *fallback* (hard: bad key, model not found). Dead providers are circuit-broken at module level. LangSmith traces every call with `phase_name + run_id`. Org-level chain overrides allow per-tenant model configuration.

### Compliance Engine

Three cooperating modules cover the full compliance lifecycle:

**`core/compliance/code_scanner.py`** (547 lines) — AST-based FastAPI route scanner. For every route in generated code, checks: presence of `Depends()` auth guard, Pydantic input validation, rate-limiting decorator, audit log call, and error handling. Returns a structured `ComplianceFinding` list with severity, framework, `rule_id`, and remediation guidance.

**`core/policy/compliance.py`** (483 lines) — Deterministic policy engine covering GDPR, HIPAA, PCI-DSS v4.0, SOC2, export controls, data residency flags, and cryptographic strength checks.

**`core/policy/compliance_india.py`** (225 lines) — India-specific rules: DPDP Act 2023 (consent + data principal rights), RBI Payment Aggregator data localisation directive, SEBI CSCRF 2024, and CERT-In 6-hour breach notification window.

**`core/policy/engine.py`** (422 lines) — `AetherPolicyEngine` with pipeline gating and per-org policy overrides.

The P06 security review phase runs all three modules and writes `compliance_manifest.json` to the generated project root. The P08 CI/CD generator adds a `compliance-drift` job to the generated GitHub Actions workflow that re-runs `code_scanner.py` on every push; if the computed score drops below the baseline stored in the manifest, the build fails with a per-rule breakdown.

### Domain Knowledge Library (`core/domain_knowledge/`)

The domain knowledge system is the primary differentiator between AetherOS and every other AI code generator. Each domain pack is a structured Python module containing:

- **`EntityTemplate`** — entity name, SQL table, fields with PHI/PCI/PII/`encrypted_at_rest`/`never_store` flags, indexes, `audit_trail`, and `soft_delete` flags
- **`WorkflowTemplate`** — full state machine with transition graph; P04 backend generator injects a `_TRANSITIONS_<ENTITY>` dict and a 422-raising guard block into every PATCH/PUT route that touches a `status` field
- **`ComplianceRule`** — standard, rule text, affected fields, `mandatory` or `recommended` enforcement, `implementation_hint`
- **`BusinessProcessPipeline`** — ordered service orchestration steps (service calls, state transitions, notifications, external API calls) consumed by P04b to emit orchestration code rather than bare CRUD
- **`prompt_injection`** — domain-specific context string injected verbatim into every LLM call for the run

The full pack is serialised via `to_dict_full()` and written to `domain_knowledge.json` in every generated project root, making the knowledge graph machine-consumable by downstream tools, auditors, and IDE plugins.

#### The 12 Domain Packs

| Pack | File | Key Entities | Compliance Standards | Notable Rules |
|---|---|---|---|---|
| Healthcare | `packs/healthcare.py` | Patient, Practitioner, Appointment, Encounter, Observation, ConsentRecord | HIPAA, GDPR, HITECH | FHIR R4 entities; all PHI fields `encrypted_at_rest`; appointment state machine (requested → confirmed → checked_in → in_progress → completed) |
| FinTech | `packs/fintech.py` | Account, Transaction, Payment, KYCRecord, Ledger | PCI-DSS v4, SOX, RBI | Double-entry ledger; KYC workflow; card numbers marked `never_store` |
| eCommerce | `packs/ecommerce.py` | Product, Cart, Order, OrderItem, Fulfillment, Review | GDPR, PCI-DSS | Order state machine; inventory reservation; payment capture pipeline |
| ERP | `packs/erp.py` | PurchaseOrder, Invoice, GLAccount, CostCentre, Employee | SOX, GDPR | Approval workflow; four-eyes principle on GL entries; audit trail mandatory |
| SaaS | `packs/saas.py` | Tenant, Subscription, FeatureFlag, UsageEvent, WebhookEndpoint | GDPR, SOC2 | Multi-tenancy row isolation; usage metering; webhook delivery with retry |
| Logistics | `packs/logistics.py` | Shipment, Route, Manifest, Fleet, TrackingEvent | GDPR | Tracking number uniqueness; event-log status (append-only, not update) |
| Trading / HFT | `packs/trading.py` | Order, Execution, Position, RiskLimit, MarketData | MiFID II, SEC Rule 17a-4, FINRA 5310 | LEI required on every order; WORM S3 for trade records (7-year retention); pre-trade risk check in order creation route; latency SLAs injected as K8s QoS |
| LegalTech | `packs/legaltech.py` | Matter, TimeEntry, PrivilegeLog, CourtFiling, TrustAccount | Attorney-client privilege, Bar regulations | Privilege log access gating; court filing workflow; trust account segregation |
| Real Estate | `packs/real_estate.py` | Property, Listing, Lease, Inspection, Transaction | Fair Housing Act, MLS rules | Disclosure workflow state machine; fair housing field restrictions |
| Manufacturing | `packs/manufacturing.py` | WorkOrder, BillOfMaterials, QualityInspection, ProductionRun, NCR | ISO 9001 | Production workflow; Non-Conformance Report (NCR) escalation; BOM version control |
| EdTech | `packs/edtech.py` | Course, Enrollment, Assessment, Certificate, LearningObjective | FERPA | Student record privacy; LTI 1.3 integration patterns; assessment submission workflow |
| GovTech | `packs/govtech.py` | Agency, ServiceRequest, Permit, AuditLog, FedRAMPControl | FedRAMP, FISMA, Section 508 | ATO workflow (initiation → security assessment → authorization → continuous monitoring); Section 508 rules injected into P07c accessibility phase |

### Quality Metrics Engine (`core/quality/metrics.py`)

AST-based code quality scorer producing a 0–100 score from weighted sub-scores:

- **Auth coverage** — fraction of non-health routes with `Depends()` auth guard
- **Input validation** — fraction of POST/PUT routes with Pydantic body models
- **Test coverage** — test-to-route ratio
- **Seed quality** — presence and density of database seed data
- **Domain specificity** — entity names match domain pack vocabulary
- **Frontend completeness** — screen count relative to entity count
- **Security** — Bandit subprocess scan (B-rated findings penalised)
- **Docker presence** — Dockerfile and docker-compose existence

The `QualityScore` dataclass is returned by the council review gate and displayed in the platform dashboard.

### Stack Profile System (`core/stack_profiles.py`)

The `StackProfile` dataclass describes every technology choice for a generated project: `build_type`, `architecture`, `backend_lang`, `backend_framework`, `frontend_framework`, `db_primary`, `db_secondary`, `message_queue`, `deployment_target`, and `performance_tier`.

P00 classifies the user's spec into one of the registered profiles using an LLM-based classifier in `phases/p00_research/stack_selector.py`. The selected profile is stored in `accumulated_context["build_profile"]` and passed to every downstream phase. P02 adjusts its architecture generation prompt, P04 routes to the correct language generator (Python FastAPI / Go Gin / TypeScript Express), and P05 routes to the correct frontend generator.

### LLM Council (`core/council/council.py`)

Two review gates that run LLM-based quality checks:

- **PreFlightCouncil** — validates a factory request before the pipeline starts (spec quality, feasibility, domain classification confidence)
- **DeliveryCouncil** — validates pipeline output before delivery (code quality, compliance coverage, test pass rate)

Both gates are configurable via `COUNCIL_ENABLED` and `COUNCIL_STRICT_MODE` environment variables. In strict mode, a failed council check blocks the operation. In default mode, failures are logged as warnings and the pipeline continues.

### Guardian — Backup and Recovery (`core/guardian/`)

A database backup and restore system with five components:

- **`snapshot_manager.py`** — `pg_dump` / `psql` for PostgreSQL, Python `sqlite3` backup API for SQLite; SHA-256 hashes every snapshot; keeps configurable rolling window (default 10)
- **`watchdog.py`** — periodic health monitor that triggers auto-recovery on detection of data anomalies
- **`auto_recovery.py`** — automated recovery procedures with configurable rollback strategies
- **`threat_detector.py`** — detects anomalous data patterns that may indicate corruption or attack
- **`password_shield.py`** — prevents credential data from appearing in logs or API responses

### Intelligence Engines (`core/intelligence/`)

Six LLM-powered advisory systems that run during the pipeline to improve output quality:

| Engine | Class | Purpose |
|---|---|---|
| Arch Governor | `ArchGovernor` | Validates architecture decisions against known anti-patterns |
| Truth Engine | `TruthEngine` | Cross-checks LLM output against domain knowledge for factual accuracy |
| Conflict Resolver | `ConflictResolver` | Detects contradictions between requirements and architecture decisions |
| Tradeoff Engine | `TradeoffEngine` | Analyses and documents architectural tradeoffs with justification |
| Improvement Loop | `ImprovementLoop` | Iterative code quality improvement via structured critique and re-generation |
| Maintenance Engine | `MaintenanceEngine` | Generates maintenance runbooks and operational procedures |

### Cell Architecture (`core/cell_architecture/cell_planner.py`)

Multi-region active-active deployment topology generator. Produces Terraform for N AWS regions (default: us-east-1, eu-west-1, ap-southeast-1), nginx upstream cell router, FastAPI health endpoints per cell, and a Markdown failover runbook.

### Cloud Primitives (`core/cloud_primitives/`)

Infrastructure code generators consumed by P11e enterprise deployment:

- **`storage.py`** — MinIO Helm values, bucket policies, boto3 client generator, docker-compose block
- **`queue.py`** — NATS JetStream Helm values, stream configs with DLQ, async Python client generator
- **`gateway.py`** — Kong declarative config (DB-less mode, rate-limit + JWT + CORS plugins) and Helm values

### Capacity Planner (`core/capacity_planner/planner.py`)

Generates Kubernetes HPA, KEDA ScaledObject, PodDisruptionBudget, and ResourceQuota manifests tuned to the `performance_tier` from the build profile:

| Tier | CPU Target | Min Replicas | Max Replicas |
|---|---|---|---|
| `standard` | 70% | 2 | 10 |
| `high_throughput` | 60% | 3 | 50 |
| `real_time` | 50% | 5 | 100 |
| `batch` | 80% | 1 | 20 |

### Sandbox Manager (`core/sandbox/manager.py`)

Execution isolation layer for code validation and testing:

- **Local execution** — resource-bounded subprocess with CPU time, wall-clock, and memory limits
- **Remote execution** — SSH-based execution on edge devices, IoT nodes, or CI runners (via paramiko)
- Strongly-typed request/response objects; clean stdout/stderr capture; timing info on every invocation

### Plugin and Connector Registry (`core/plugins/`)

- **`registry.py`** — dynamic plugin registry for extending the platform with custom phase agents
- **`connectors_registry.py`** — connector registry for third-party service integrations
- **`connectors.py`** — built-in connector implementations
- **`skills.py`** — reusable skill library for agent composition

---

## Generated App Artifacts

Every generated application ships the following artifacts in its project root alongside the source code:

### `compliance_manifest.json`

Written by P06 security review. Contains:
- `drift_fingerprint` — SHA-256 hash of all compliance-relevant code sections; recomputed by the generated CI gate on every push
- `overall_score` and `overall_status` (pass / fail / partial)
- Per-route `rules_satisfied` and `rules_violated` arrays with severity and remediation guidance
- `pii_fields_found`, `phi_fields_found`, `pci_fields_found` — field-level compliance tagging
- `encryption_verified` and `audit_trail_verified` booleans

The generated GitHub Actions workflow includes a `compliance-drift` job that fails the build if the recomputed score drops below the baseline, preventing silent compliance regression after developer edits.

### `domain_knowledge.json`

Written by the artifact collector after P01 domain resolution using `DomainKnowledgePack.to_dict_full()`. Contains the complete nested structure: every entity with all field flags (`pii`, `phi`, `pci`, `encrypted_at_rest`, `never_store`), every state machine transition table, every compliance rule with `implementation_hint`, and every `BusinessProcessPipeline` definition. Consumed by IDE plugins, downstream CI rules, and audit systems.

### `business_model.json`

Written by P00 research. Contains: target market definition, problem statement, value proposition, revenue model type, TAM/SAM/SOM estimates with confidence levels, monetisation tier recommendations (Free / Starter / Pro / Enterprise), competitive landscape analysis, GTM strategy, cost structure, unit economics, and regulatory considerations. If LLM generation fails the step is skipped gracefully; the rest of the pipeline is unaffected.

### Workflow State Machine Guards

For every entity in the domain pack with a `WorkflowTemplate`, P04 injects a `_TRANSITIONS_<ENTITY>` dict derived from the workflow definition and a guard block in every PATCH/PUT route that raises HTTP 422 with a descriptive error on invalid transitions. An Appointment cannot jump from `requested` to `completed` without passing through `confirmed` and `checked_in`. The guard is generated from the domain pack's authoritative state machine definition, not from LLM judgment.

### SRE Agent (P21)

Generated after P15 handoff. Produces `sre/operator.py` (Kubernetes Operator that watches Prometheus AlertManager webhooks), `sre/failure_classifier.py` (domain-aware alert classification), `sre/remediation_generator.py` (LLM-powered remediation producer), and Kubernetes manifests. The failure classifier uses domain-specific Prometheus patterns — for example, a `p95_latency > 500ms` alert in a trading application is classified as an immediate SLA breach rather than a warning, while the same alert on an eCommerce cart endpoint triggers a traffic surge check first.

### Kubernetes and Infrastructure

- **Helm charts** — per-service deployments, services, ingress, configmaps, and HPA
- **LitmusChaos experiments** — pod-delete, network-partition, and CPU-hog YAML manifests with RBAC and chaos schedules
- **Multi-region Terraform** — AWS Global Accelerator, Route53 health-check failover, VPC peering across three regions
- **IAM** — OPA Rego policies for RBAC and Keycloak realm JSON for SSO realm configuration

---

## Enterprise Features

### Authentication and Identity

- **RS256 JWT** — asymmetric key signing; public key exposed at `/auth/keys` for downstream service verification
- **SAML/SSO** — python3-saml integration; tested against Okta and Azure AD
- **SCIM v2** — automated user and group provisioning from enterprise IdPs
- **TOTP MFA** — pyotp-based time-based one-time passwords
- **OAuth2 Social Login** — GitHub and Google OAuth2 flows
- **Multi-tenancy** — every resource is scoped to `org_id`; `X-Org-ID` header enforced in middleware; row-level isolation in all queries

### Billing

- **Stripe** (international) — subscription creation, metering, webhook processing, plan-gated feature access
- **OpenMeter** — usage metering with CloudEvents schema and metering middleware injected into generated apps
- Both providers are configured via environment variables; the billing router (`gateway/routers/billing_router.py`, `billing_stripe_router.py`) handles order creation, payment verification, and subscription management

### Security

- **Bandit + Semgrep** static analysis on every generated project
- **Field-level encryption** — Fernet-based encryption for PII/PHI fields at the SQLAlchemy layer
- **Rate limiting** — slowapi per-route limits injected into generated code
- **Audit ledger** — append-only log of all pipeline events per org (`core/audit/`)
- **OPA Rego policies** — generated by P16; enforced at the Kubernetes ingress layer

### Vector Memory and Feature Flags

- **ChromaDB** — vector store for app memory (`p13_app_memory`)
- **mem0** — persistent memory layer with knowledge graph seeding
- **GrowthBook** — A/B testing and feature flag management (`p12b_ab_testing`)
- **Unleash** — gradual rollout feature flags (`p12a_feature_flags`)

### Developer Tooling

- **Full Development Environment (FDE)** — Monaco editor in-browser, env-var management, `run-app` process manager, VS Code open-in-editor
- **VS Code extension** (`vscode-extension/`) — sidebar panel with live pipeline status, artifact browser, one-click open
- **CLI** (`cli/aetheros.py`) — `aether` command (Typer + Rich) for starting runs, streaming logs, downloading artifacts
- **LangSmith tracing** — every LLM call is traced with phase name and run ID

---

## Architecture

```
                             ┌─────────────────────────────┐
                             │         React Dashboard      │
                             │  (Vite + Tailwind + TanStack)│
                             └──────────────┬──────────────┘
                                            │ HTTPS
                             ┌──────────────▼──────────────┐
                             │       FastAPI Gateway         │
                             │   gateway/api.py             │
                             │   44 domain routers          │
                             │   RS256 JWT + SAML + SCIM    │
                             └──────────────┬──────────────┘
                                            │
              ┌─────────────────────────────┼─────────────────────────┐
              │                             │                         │
   ┌──────────▼──────────┐     ┌────────────▼──────────┐  ┌──────────▼──────────┐
   │   PipelineService    │     │   Intelligence Engines │  │   Compliance Engine  │
   │  orchestrator/       │     │   core/intelligence/   │  │  core/compliance/    │
   │  factory_pipeline.py │     │   6 advisory systems   │  │  core/policy/        │
   └──────────┬──────────┘     └────────────────────────┘  └─────────────────────┘
              │
   ┌──────────▼──────────────────────────────────────────────────────────────────┐
   │                    39-Phase Pipeline (phases/p00 – p21)                      │
   │                                                                              │
   │  Research → Requirements → Architecture → Code → Security → Test → Deploy  │
   │     ↕             ↕             ↕           ↕        ↕         ↕       ↕   │
   │           accumulated_context flows through every phase via MessageBus      │
   └──────────┬──────────────────────────────────────────────────────────────────┘
              │
   ┌──────────▼──────────────────────────────────────────────────────────────────┐
   │                          Generated Project Output                            │
   │                                                                              │
   │  backend/         frontend/       k8s/            sre/                      │
   │  compliance_manifest.json         domain_knowledge.json                     │
   │  business_model.json              verification_report.json                  │
   │  .github/workflows/ci.yml  (with compliance-drift gate)                     │
   └─────────────────────────────────────────────────────────────────────────────┘

Infrastructure:
  PostgreSQL (asyncpg + SQLAlchemy 2.0 async + Alembic)
  Redis (RPUSH/BLPOP MessageBus; asyncio.Queue fallback for single-process)
  LLM: Anthropic claude-sonnet-4-6 → AWS Bedrock → Gemini 2.5 Flash → OpenRouter → Ollama
```

---

## Quick Start

### Option 1 — Docker Compose (recommended)

```bash
# 1. Clone the repository
git clone <repo> aether_os
cd aether_os

# 2. Create environment file
cp .env.example .env
# Required: edit .env and set at minimum:
#   ANTHROPIC_API_KEY=sk-ant-...          (or AWS Bedrock credentials)
#   AETHER_SECRET_KEY=<64-char hex>
#   AETHER_ONE_ZT_SECRET=<32-char hex>
#   REDIS_PASSWORD=<strong random password>
#   POSTGRES_PASSWORD=<strong random password>
#   AETHER_ADMIN_PASSWORD=<strong admin password>
#   CORS_ORIGINS=http://localhost:3000
#   FRONTEND_URL=http://localhost:3000/dashboard

# 3. Start the full stack
docker compose up -d

# 4. Build the React dashboard
cd dashboard && npm install && npm run build && cd ..

# 5. Verify
curl http://localhost:8000/health
```

### Option 2 — Local Python Environment

```bash
# 1. Clone and install
git clone <repo> aether_os
cd aether_os
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Set at minimum:
#   ANTHROPIC_API_KEY=sk-ant-...
#   AETHER_SECRET_KEY=<64-char hex>
#   AETHER_ONE_ZT_SECRET=<32-char hex>
#   DATABASE_URL=postgresql+asyncpg://user:pass@localhost/aetheros
#   REDIS_URL=redis://:password@localhost:6379/0
#   CORS_ORIGINS=http://localhost:3000
#   FRONTEND_URL=http://localhost:3000/dashboard
#   AETHER_ADMIN_PASSWORD=<strong admin password>

# 3. Apply database migrations
alembic upgrade head

# 4. Start the API server
uvicorn gateway.api:app --host 0.0.0.0 --port 8000 --reload

# 5. Build the dashboard
cd dashboard && npm install && npm run build
```

### CLI

```bash
pip install -e cli/
aether --help
aether run "Build a HIPAA-compliant appointment booking system for a clinic"
aether logs <run_id>
aether artifacts <run_id> --download
```

### Smoke Test

```bash
# Test a local instance
./scripts/smoke_test.sh http://localhost:8000

# Test the production VPS
./scripts/smoke_test.sh http://REDACTED_IP
```

---

## Project Structure

```
aether_os/
├── gateway/                   # FastAPI application, auth, SAML, MFA
│   └── routers/               # 44 domain router files
├── orchestrator/              # Pipeline orchestrator, MessageBus, state machine
│   ├── factory_pipeline.py    # Phase runner + accumulated_context
│   └── phase_sequence.py      # Phase registry and order
├── phases/                    # 39 phase modules (supervisor + task agent + gate)
│   ├── p00_research/
│   ├── p00a_intake/
│   ├── p00b_data_archaeology/
│   ├── p00c_architecture_planner/
│   ├── p01_intake_requirements/
│   ├── p01b_integration_discovery/
│   ├── p02_architecture/
│   ├── p02b_domain_ir/
│   ├── p02c_permission_modeling/
│   ├── p03_scaffolding/
│   ├── p04_backend/
│   ├── p04b_business_logic/
│   ├── p04c_integration_codegen/
│   ├── p05_frontend/
│   ├── p05b_mobile/
│   ├── p05c_desktop/
│   ├── p05d_cli/
│   ├── p05e_serverless/
│   ├── p06_review_security/
│   ├── p06b_formal_verification/
│   ├── p07_testing/ → p07d_e2e_testing/
│   ├── p08_cicd_deployment/
│   ├── p09_observability/
│   ├── p10_docs_delivery/
│   ├── p11_deployment/ → p11e_enterprise_deployment/
│   ├── p12a_feature_flags/
│   ├── p12b_ab_testing/
│   ├── p13_app_memory/
│   ├── p14_client_portal/
│   ├── p15_handoff/
│   ├── p16_iam/
│   ├── p17_control_plane/
│   ├── p18_billing_metering/
│   ├── p19_service_catalog/
│   ├── p20_multiregion/
│   └── p21_sre_agent/
├── core/                      # Shared business logic
│   ├── compliance/            # AST-based route scanner, PDF report, artifact generator
│   ├── policy/                # GDPR/HIPAA/PCI-DSS/SOC2 + India DPDP/RBI/SEBI
│   ├── domain_knowledge/      # 12 domain packs + base dataclasses + loader
│   ├── quality/               # AST-based 0–100 quality scorer
│   ├── stack_profiles.py      # BuildProfile registry (13 profiles)
│   ├── model_router.py        # 4-tier LLM fallback with circuit-breaking
│   ├── council/               # PreFlight + Delivery LLM review gates
│   ├── guardian/              # Snapshot backup, watchdog, auto-recovery
│   ├── intelligence/          # 6 advisory engines (ArchGovernor, TruthEngine, etc.)
│   ├── cell_architecture/     # Multi-region active-active topology generator
│   ├── cloud_primitives/      # MinIO, NATS JetStream, Kong generators
│   ├── capacity_planner/      # Kubernetes HPA + KEDA + PDB generators
│   ├── chaos_engineering/     # LitmusChaos YAML experiment generators
│   ├── sandbox/               # Local + SSH code execution isolation
│   ├── plugins/               # Plugin + connector registry
│   ├── memory/                # ChromaDB + mem0 vector memory
│   ├── billing/               # Stripe + billing models
│   ├── audit/                 # Append-only event ledger
│   ├── identity/              # User, Org, RBAC models
│   └── notifications/         # Email + in-app notification dispatch
├── dashboard/                 # React 18 + Vite + Tailwind frontend
├── cli/                       # `aether` CLI (Typer + Rich)
├── vscode-extension/          # VS Code sidebar extension
├── agents/                    # Standalone agent definitions
├── tests/                     # pytest test suite (535+ tests)
├── deploy/                    # nginx.conf, systemd unit, deploy.sh
├── alembic/                   # Database migrations
├── scripts/                   # smoke_test.sh, post-deploy.sh
└── docker-compose.yml         # Local development stack
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Gateway | FastAPI 0.110+, Uvicorn |
| Data validation | Pydantic v2 |
| Database (platform) | PostgreSQL (asyncpg) + SQLAlchemy async 2.0 + Alembic |
| Database (generated apps) | SQLite (aiosqlite) default; PostgreSQL for enterprise builds |
| Cache / Message Bus | Redis 7 (asyncio, RPUSH/BLPOP); asyncio.Queue fallback |
| Auth | python-jose JWT (RS256), passlib/bcrypt, pyotp (TOTP MFA), python3-saml (SSO) |
| LLM Tier 1 | Anthropic claude-sonnet-4-6 |
| LLM Tier 1b | AWS Bedrock (Claude Sonnet / Amazon Nova Pro via IAM) |
| LLM Tier 2 | Google Gemini 2.5 Flash (google-genai) |
| LLM Fallback | OpenRouter / Ollama qwen2.5-coder:3b |
| LLM Tracing | LangSmith |
| Code generation | cookiecutter, aider-chat |
| Security scanning | Bandit, Semgrep |
| Formal verification | Z3 SMT solver (p06b_formal_verification) |
| Testing | pytest, Playwright, Locust, Hypothesis |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, TanStack Query |
| Memory | mem0ai, ChromaDB |
| Feature flags | Unleash, GrowthBook |
| Analytics | PostHog |
| Error tracking | Sentry SDK |
| Observability | Prometheus, Grafana, structlog, OTEL |
| Chaos engineering | LitmusChaos |
| IAM | OPA (Rego policies), Keycloak |
| Billing | Stripe, OpenMeter (CloudEvents) |
| Kubernetes | Helm, KEDA, HPA, PDB, CRDs |
| Infrastructure-as-Code | Terraform (AWS: Global Accelerator, Route53, VPC, EKS) |
| API Gateway (generated) | Kong (DB-less, rate-limit + JWT + CORS plugins) |
| Object storage (generated) | MinIO (S3-compatible, Helm) |
| Message queue (generated) | NATS JetStream (Helm, DLQ) |
| CLI | Typer, Rich |
| Deployment | systemd, nginx, certbot (TLS), Docker multi-stage |

---

## Competitive Positioning

| Capability | AetherOS | Lovable | Bolt.new | Replit Agent | Devin / Cognition |
|---|---|---|---|---|---|
| Pipeline phases | **39** | 1 | 1 | 2–3 | 3–5 |
| Domain knowledge packs | **12** | None | None | None | None |
| PHI/PCI/PII field tagging | **Yes** | No | No | No | No |
| Workflow state machine enforcement | **Yes** | No | No | No | No |
| Compliance manifest in generated output | **Yes** | No | No | No | No |
| CI compliance drift gate | **Yes** | No | No | No | No |
| India regulatory compliance (DPDP/RBI/SEBI) | **Yes** | No | No | No | No |
| Kubernetes + Helm generation | **Yes** | No | No | No | No |
| Chaos engineering (LitmusChaos) | **Yes** | No | No | No | No |
| Multi-region Terraform | **Yes** | No | No | No | No |
| IAM (OPA + Keycloak) | **Yes** | No | No | No | No |
| Go microservices generation | **Yes** | No | No | No | No |
| React Native mobile | **Yes** | No | Partial | Partial | No |
| Electron desktop | **Yes** | No | No | No | No |
| Post-deployment SRE self-healing | **Yes** | No | No | No | No |
| Formal verification (Z3 SMT) | **Yes** | No | No | No | No |

---

## Test Suite

The test suite covers all 39 phases, all 12 domain packs, the compliance engine, quality metrics, model router, multi-tenancy, rate limiting, billing webhooks, and cloud platform generators.

| Test File | Focus | Tests |
|---|---|---|
| `test_v2_layers.py` | Stack profiles, Go/Node generators, domain knowledge packs | 71 |
| `test_l5_cloud_primitives.py` | MinIO, NATS, Kong, cell architecture, chaos engineering | 40 |
| `test_l6_l8_phases.py` | Cloud platform phases (P16–P21) | 27 |
| `test_core.py` | Core business logic, compliance engine, council | 27 |
| `test_quality_metrics.py` | AST-based quality scorer | 24 |
| `unit/test_security.py` | Security utilities, JWT, field encryption | 23 |
| `test_factory.py` | Factory pipeline integration | 23 |
| `test_model_router.py` | LLM fallback chain, circuit breaking | 20 |
| `test_project_fingerprinter.py` | Project fingerprinting and diff detection | 18 |
| `test_phases.py` | Phase input/output contracts | 16 |
| `test_phases_later.py` | Later pipeline phases (P13–P21) | 13 |
| `test_integration_pipeline.py` | End-to-end pipeline integration | 13 |
| `test_gateway.py` | API gateway routing and auth | 13 |
| `test_pipeline.py` | Orchestrator and message bus | 11 |
| `test_memory.py` | ChromaDB and mem0 integration | 11 |
| Additional files | Billing, multi-tenancy, rate limiting, LLM, Bedrock | ~165 |

**535+ tests. 0 failures. CI runs on every push to `main`.**

Run the full suite:

```bash
pytest tests/ --timeout=300 -q
```

---

## Pipeline Specification

The formal pipeline specification is published at [`docs/PIPELINE_SPEC.md`](docs/PIPELINE_SPEC.md). It defines:

- `PhaseInput` and `PhaseResult` JSON Schema for every phase interface
- Domain pack plugin standard — the `DomainKnowledgePack` conformance checklist for third-party packs
- `BusinessProcessPipeline` step schema with `input_mapping` path syntax
- Artifact standards for `domain_knowledge.json`, `compliance_manifest.json`, and `business_model.json`
- Three documented extension points (pre-P00, post-P15, post-P20) for inserting third-party phases

---

## License

Proprietary. All rights reserved. Unauthorized use, reproduction, or distribution is prohibited.
