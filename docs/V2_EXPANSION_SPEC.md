> **This document is a spec, not a description of what is built.** Nothing in it is claimed as implemented. The "Current State" table was written in 2026 and is not current: at 15 Nov 2026 (commit `e5c23fd`) the pipeline has 12 stages over 50 phase directories.

# AetherOS V2 — Multi-Language, Architecture-Aware Pipeline
## Technical Build Specification

**Goal:** Expand AetherOS from a single-stack SaaS generator (FastAPI + React) into a
full-spectrum software factory capable of producing any class of business software —
microservices, mobile apps, Go/Node services, enterprise ERP, and domain-expert-injected systems.

---

## Current State (Baseline)

| Capability | Current |
|---|---|
| Backend language | Python (FastAPI) only |
| Frontend | React/Vite only |
| Architecture output | Single monolith |
| Domain injection | DomainProfile hints (domain_engine.py) |
| Stack selection | Hardcoded — all runs use FastAPI |
| Phase count | 29 phases (as of writing; now 12 stages over 50 phase directories) |
| Key artifact | `design_brief.json` from P00, `architecture.json` from P02 |

**Key pipeline files:**
- `orchestrator/phase_sequence.py` — phase registry and order
- `orchestrator/factory_pipeline.py` — phase runner + context accumulation
- `core/domain_engine.py` — domain profiles with `suggested_tech_stack`
- `phases/p00_research/task_agent.py` — outputs `design_brief.json`
- `phases/p02_architecture/` — outputs `architecture.json` with `tech_stack` key
- `phases/p04_backend/` — generates Python FastAPI code
- `phases/p05_frontend/` — generates React/Vite code

---

## Layer 1 — Stack Profile System + Intent Classification
**Target: 2-3 weeks | Status: IN PROGRESS**

### What it does
Adds a pre-P00 classification step that reads the user's spec and outputs a structured
`BuildProfile` consumed by every downstream phase. Phases adapt their prompts and generators
based on the profile instead of assuming FastAPI + React.

### New files to create

#### `core/stack_profiles.py`
Central registry of all supported build profiles.

```
StackProfile dataclass:
  build_type: str          # "web_app" | "microservice" | "mobile" | "desktop" | "cli" | "ml_pipeline"
  architecture: str        # "monolith" | "microservices" | "serverless" | "event_driven"
  backend_lang: str        # "python" | "go" | "typescript" | "java"
  backend_framework: str   # "fastapi" | "gin" | "express" | "spring_boot"
  frontend_framework: str  # "react" | "react_native" | "flutter" | "electron" | "none"
  db_primary: str          # "postgres" | "sqlite" | "mysql" | "mongodb" | "timescaledb"
  db_secondary: list       # e.g. ["redis", "elasticsearch"]
  message_queue: str       # "" | "kafka" | "rabbitmq" | "redis_streams"
  deployment_target: str   # "docker_compose" | "kubernetes" | "serverless" | "native"
  domain_pack: str         # matches key in domain_engine.DOMAIN_PROFILES
  performance_tier: str    # "standard" | "high_throughput" | "real_time" | "batch"

STACK_PROFILES dict: maps profile name → StackProfile instance
  "web_saas"       → python/fastapi/react/postgres/docker
  "go_api"         → go/gin/react/postgres/kubernetes
  "node_serverless"→ typescript/express/react/postgres/serverless
  "java_enterprise"→ java/spring_boot/react/postgres/kubernetes
  "mobile_rn"      → python/fastapi/react_native/postgres/docker
  "desktop_electron"→ python/fastapi/electron/sqlite/native
  "ml_pipeline"    → python/fastapi+celery/react/postgres/docker
  "microservices"  → go/gin(multi)/react/postgres/kubernetes+kafka
```

#### `phases/p00_research/stack_selector.py`
LLM-powered classifier. Called from P00 task_agent.run() before screenshot analysis.

```
async def classify_build(spec_text: str, domain: str) -> StackProfile:
  - Sends spec to LLM with a classification prompt
  - LLM returns JSON: {build_type, architecture, backend_lang, ...}
  - Validates against STACK_PROFILES keys
  - Returns a StackProfile instance
  - Falls back to "web_saas" profile if LLM fails or returns unrecognised value
```

#### `phases/p00_research/prompts.py` (new file — extract from task_agent)
Move all prompt strings from task_agent.py into this file.
Add `STACK_CLASSIFIER_PROMPT` template.

### Files to modify

#### `phases/p00_research/task_agent.py`
- Import `classify_build` from `stack_selector`
- Call `classify_build()` at start of `run()` before screenshot stage
- Add `build_profile` dict to `design_brief.json` output
- Keep file under 300 lines (move prompts to prompts.py)

#### `core/domain_engine.py`
- Add `build_profile_hint` field to `DomainProfile` dataclass
- Add new domain profiles: `"mobile"`, `"desktop"`, `"cli"`, `"ml_pipeline"`
- Each profile's `suggested_tech_stack` must now be consistent with StackProfile fields

#### `orchestrator/factory_pipeline.py`
- After P00 completes, read `build_profile` from `design_brief.json`
- Store in `accumulated_context["build_profile"]`
- Pass to every phase's `phase_input.input_data["build_profile"]`
- Add `_select_phase_sequence(build_profile)` function that returns a trimmed phase list:
  - Mobile builds: skip p05_frontend, add p05b_mobile (future)
  - CLI builds: skip p05_frontend, p11_deployment web steps
  - Standard web: existing PHASE_SEQUENCE unchanged

#### `phases/p02_architecture/task_agent.py`
- Read `build_profile` from `input_data`
- Inject into architecture generation prompt: "Generate architecture for a {build_type}
  using {backend_lang}/{backend_framework} with {architecture} pattern"
- Ensure `architecture.json` output contains `tech_stack.backend_lang` field

#### `phases/p04_backend/task_agent.py`
- Read `build_profile.backend_lang` from context
- If `python`: existing FastAPI generator (no change)
- If `go`: call new `go_generator.py` (see below)
- If `typescript`: call new `node_generator.py` (see below)

#### `phases/p05_frontend/task_agent.py`
- Read `build_profile.frontend_framework`
- If `react`: existing generator (no change)
- If `none`: skip frontend generation gracefully
- If `react_native` / `electron`: log "not yet implemented, falling back to react"
  (stubs for Layer 2)

### New generator: `phases/p04_backend/go_generator.py`
Generates a working Go + Gin REST API.

```
Files generated:
  main.go           — Gin server, route registration, middleware
  handlers/         — one handler file per entity
  models/           — Go structs matching domain IR entities
  db/               — GORM connection + migration runner
  Dockerfile        — multi-stage Go build (scratch final image)
  go.mod / go.sum   — module definition

Functions:
  generate_go_main(entities, project_name) → str
  generate_go_handler(entity) → str
  generate_go_model(entity) → str
  generate_go_db(db_url) → str
  generate_go_dockerfile(project_name) → str
```

### New generator: `phases/p04_backend/node_generator.py`
Generates a TypeScript + Express REST API (stub, full in Layer 2).

```
Files generated:
  src/index.ts      — Express server
  src/routes/       — one router per entity
  src/models/       — TypeScript interfaces
  package.json      — dependencies
  tsconfig.json     — TS config
  Dockerfile        — Node multi-stage build
```

### Wiring diagram

```
User spec text
     │
     ▼
P00 task_agent.run()
     ├── stack_selector.classify_build()  ← NEW
     │        └── LLM → StackProfile
     ├── screenshot + vision analysis (existing)
     └── outputs design_brief.json
              └── build_profile: {StackProfile fields}  ← NEW KEY
                       │
                       ▼
factory_pipeline.py reads build_profile after P00
     └── stored in accumulated_context["build_profile"]
              │
              ├──► P02 architecture prompt gets build_profile context
              ├──► P04 backend routes to python/go/node generator
              ├──► P05 frontend uses profile.frontend_framework
              └──► All other phases receive build_profile in input_data
```

### Commit plan (one per logical unit)
1. `feat: add StackProfile dataclass and STACK_PROFILES registry (core/stack_profiles.py)`
2. `feat: add LLM-based stack classifier to p00_research`
3. `feat: wire build_profile output from P00 into pipeline context`
4. `feat: inject build_profile into P02 architecture generation prompt`
5. `feat: route P04 backend to Go generator when build_profile.backend_lang == "go"`
6. `feat: add Go/Gin REST API generator (phases/p04_backend/go_generator.py)`
7. `feat: add Node/Express TypeScript generator stub (phases/p04_backend/node_generator.py)`
8. `feat: P05 frontend reads build_profile.frontend_framework, graceful fallback`

---

## Layer 2 — Architecture Planner Phase + Full Multi-Language
**Target: 3-4 weeks | Depends on: Layer 1**

### New phase: `phases/p00c_architecture_planner/`
Inserted between P00b_data_archaeology and P01_intake_requirements.
Only activated when `build_profile.architecture == "microservices"`.

```
Outputs: service_map.json
  {
    "services": [
      {"name": "auth-service", "lang": "go", "framework": "gin", "port": 8001,
       "owns": ["User", "Session"], "communicates_via": "rest"},
      {"name": "payment-service", "lang": "go", "framework": "gin", "port": 8002,
       "owns": ["Transaction", "Ledger"], "communicates_via": "grpc"},
      ...
    ],
    "message_bus": "kafka",
    "api_gateway": "nginx",
    "shared_db": false
  }
```

When service_map.json exists, factory_pipeline runs P04 once PER service in parallel.

### Full Go generator (production-grade)
- gRPC service definitions (.proto files)
- Structured logging (zerolog)
- Health check endpoints
- Prometheus metrics middleware
- Docker multi-stage build (CGO_ENABLED=0, scratch final)

### Full Node/TypeScript generator
- Fastify (faster than Express)
- Zod schema validation
- Drizzle ORM
- Vitest tests

### React Native generator (`phases/p05b_mobile/`)
- Navigation (Expo Router)
- Auth (JWT stored in SecureStore)
- API client (React Query)
- One screen per entity

---

## Layer 3 — Domain Knowledge Library
**Target: 2-3 weeks | Can run in parallel with Layer 2**

### New module: `core/domain_knowledge/`

```
core/domain_knowledge/
  __init__.py
  loader.py         — loads domain pack by name, injects into phase context
  packs/
    fintech.py      — KYC flow, double-entry ledger, PCI-DSS patterns
    healthcare.py   — FHIR resources, HIPAA field tagging, consent flows
    ecommerce.py    — order state machine, cart, inventory, fulfillment
    erp.py          — GL accounts, cost centres, approval workflows, audit trails
    logistics.py    — route optimisation, carrier abstraction, geofencing
    saas.py         — multi-tenancy, usage metering, webhook system
```

Each pack is a Python module exporting:
```python
ENTITIES: List[EntityTemplate]     # pre-built entity schemas for this domain
WORKFLOWS: List[WorkflowTemplate]  # state machines and business rules
COMPLIANCE: List[ComplianceRule]   # field-level tagging (PII, PHI, PCI)
PROMPT_INJECTION: str              # context string injected into all LLM prompts
API_PATTERNS: List[str]            # standard API patterns for this domain
```

### Modified phases
- P00: after `classify_build()`, also call `loader.load_pack(domain)` → store in `design_brief["domain_knowledge"]`
- P01 intake: receives domain_knowledge in context, uses PROMPT_INJECTION in requirements prompt
- P02 architecture: uses ENTITIES as starting schema hints
- P04 backend: uses WORKFLOWS to generate state machine code
- P06 security: uses COMPLIANCE rules for field-level audit

---

## Layer 4 — Infrastructure Expansion + Mobile/Desktop
**Target: 3-4 weeks | Depends on: Layer 2**

### Enhanced P11e enterprise deployment
Currently generates: Helm chart, Terraform stub
Add:
- Kafka + Zookeeper Helm chart wiring
- Redis Streams config for event sourcing
- Terraform modules for AWS VPC + RDS + EKS
- GitHub Actions CI/CD for multi-service repos

### React Native generator (full, from stub in Layer 2)
### Electron/Tauri desktop generator (`phases/p05c_desktop/`)
### CLI generator (`phases/p05d_cli/`) — Cobra (Go) or Click (Python)

---

## Phase Sequence After All Layers

```
p00_research          (enhanced: classify_build + domain_knowledge load)
p00b_data_archaeology
p00c_architecture_planner  (NEW — microservices only)
p01_intake_requirements
p01b_integration_discovery
p02_architecture      (enhanced: build_profile-aware prompts)
p02b_domain_ir
p02c_permission_modeling
p03_scaffolding
p04_backend           (routes to: python/go/node/java generator)
p04b_business_logic   (domain workflow injection)
p04c_integration_codegen
p05_frontend          (routes to: react/react_native/electron/none)
p05b_mobile           (NEW — React Native, Layer 2)
p05c_desktop          (NEW — Electron/Tauri, Layer 4)
p05d_cli              (NEW — Cobra/Click, Layer 4)
p06_review_security   (domain compliance rules injected)
p07_testing
p07b_self_healing
p08_cicd_deployment   (multi-service CI aware)
p09_observability
p10_docs_delivery
p11_deployment
p11a_monitoring → p11e_enterprise_deployment
p12a_feature_flags
p12b_ab_testing
p13_app_memory
p14_client_portal
p15_handoff
```

---

## File Budget (CLAUDE.md compliance)

| New file | Est. lines | Status |
|---|---|---|
| core/stack_profiles.py | ~150 | New |
| phases/p00_research/stack_selector.py | ~120 | New |
| phases/p00_research/prompts.py | ~80 | New (extracted) |
| phases/p04_backend/go_generator.py | ~400 | New |
| phases/p04_backend/node_generator.py | ~300 | New |
| core/domain_knowledge/loader.py | ~100 | New (Layer 3) |
| core/domain_knowledge/packs/fintech.py | ~150 | New (Layer 3) |
| phases/p00c_architecture_planner/task_agent.py | ~250 | New (Layer 2) |

All new files are under 600 lines. P00 task_agent.py will shrink (prompts extracted).

---

## Valuation Impact

| State | Realistic Ask | Strategic Ceiling |
|---|---|---|
| Today (pre-Layer 1) | $80-150K | $200K |
| After Layer 1 (stack profiles + Go) | $150-250K | $350K |
| After Layer 1+2 (microservices + mobile stub) | $250-400K | $500K |
| After Layer 1+2+3 (domain knowledge) | $350-500K | $700K |
| After all 4 layers | $500K-800K | $1M+ |

The step change is Layer 1 → Layer 2 (demonstrable multi-language, multi-architecture builds).
Layer 3 (domain knowledge) is the enterprise differentiator — no competitor does this.
