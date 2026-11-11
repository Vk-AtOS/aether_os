# AetherOS — Master Codebase Map

Repo: `/Users/apple/Desktop/aether_os` · HEAD `052a101` (working tree: `agents/implementations.py`, `plans2.md` modified) · Mapped 2026-11-08
Method: 13 parallel workers read every source file in their slice in full (~240K LOC across phases, core, gateway, dashboard, infra, tests, docs). Detailed evidence with `file:line` citations lives in `sections/01…13`. This file is the synthesis. Headline bugs marked ✔ were re-verified by the lead directly.

| § | Section file | Scope |
|---|---|---|
| 01 | `sections/01_orchestration.md` | main.py, orchestrator/, stages/s01–s12, phases/base, agents/, integrations/ |
| 02 | `sections/02_ph_discovery_design.md` | p00, p00b, p00c, p01, p01b, p02, p02b, p02c, p03, p04_uiux_design |
| 03 | `sections/03_ph_backend_codegen.md` | p04a_backend_codegen |
| 04 | `sections/04_ph_backend_support_patterns.md` | p04_backend, p04b, p04c, phases/patterns |
| 05 | `sections/05_ph_frontend.md` | p05_frontend, p05b mobile, p05c desktop, p05d cli, p05e serverless |
| 06 | `sections/06_ph_quality_apptargets.md` | p06, p06b (Z3), p07, p07a–d, p07b_self_healing |
| 07 | `sections/07_ph_deployment.md` | p08_cicd, p08_cicd_deployment, p09_*, p10, p11, p11e, p15 |
| 08 | `sections/08_ph_ops_enterprise.md` | p11a–d, p12a/b, p13, p14, p16–p21 |
| 09 | `sections/09_core_ai_knowledge.md` | core/llm, model_router, memory, council, knowledge, learning, quality |
| 10 | `sections/10_core_platform_governance.md` | core/ governance, security, compliance, Guardian, run_app, DB, queue |
| 11 | `sections/11_gateway_api_data.md` | gateway/ (~282 routes), auth, alembic, data model |
| 12 | `sections/12_dashboard_cli_ide.md` | dashboard/ (React), cli/, vscode-extension/, public/ |
| 13 | `sections/13_infra_tests_vision.md` | Docker/K8s/Helm/VPS, CI, scripts, tests, vision & strategy docs |

---

## 1. Vision and goal

- **Vision (README.md:3):** "an AI-powered software factory that transforms a plain-English requirement into a production-ready, compliance-verified, fully deployed application" — marketed as a "39-phase autonomous pipeline… in under 10 minutes".
- **End-state ambition (STRATEGIC_UPGRADE_PLAN.md):** "Compliance-Verified Business Creation Platform" — full-stack apps with machine-checkable (Z3) security proofs, "a category of one".
- **V2 expansion (V2_EXPANSION_SPEC.md):** from a single FastAPI+React generator to "any class of business software" — Go/Node, microservices, mobile, desktop, CLI, serverless, domain-expert packs. All 4 layers have code on disk.
- **Differentiators claimed:** 12 domain knowledge packs (PHI/PCI/PII tagging), compliance manifest + drift CI gate, Z3 formal verification, India regulatory layer (DPDP, RBI, SEBI, CERT-In), self-healing, SRE operator.
- **Target users:** technical founders/CTOs, small agencies (5–20), regulated verticals (healthcare, fintech, govtech), enterprise IdP customers (SAML/SCIM), and acquirers — the repo is explicitly being prepared for sale (SALE_READINESS, DD docs, IP_OWNERSHIP).
- **Business model:** trial (3 runs) / pro / enterprise; Razorpay (India) + Stripe. Prices are inconsistent across surfaces ($29/$149 in Billing, $49/$199 Pricing fallback, ₹999/₹4,999 landing).
- **Reality vs vision:** code runs **12 stages wrapping ~52 phase dirs** (docs claim 10/20/21/26/29/39). Latest internal DD audit rates the product 5.5/10. Two valuation stories conflict ($80K–$1M vs $5–100M).

---

## 2. Framework & architecture

### 2.1 Stack
FastAPI (uvicorn, 4 workers) · async SQLAlchemy + asyncpg (PostgreSQL; SQLite fallback) · Redis (event bus, control keys, rate limits, JWT blacklist) · React 18 / Vite dashboard served by FastAPI · nginx + certbot · systemd on a single DigitalOcean VPS. Optional: PgBouncer, Ollama, ChromaDB, SQS. Unexercised: Docker Compose, raw K8s, Helm chart.

### 2.2 Layered architecture
```
 Surfaces      dashboard (React, ~50 routes) · CLI (Typer, 12 cmds) · VS Code ext (9 cmds) · MCP · client portal
                 │  REST + SSE (single-use sse_token)
 API plane     gateway/  api.py → 55 routers, ~282 routes · middleware: audit→prom→gzip→CORS→https→sec-headers→org-log→/api strip
                 │  auth: RS256 JWT (+HS256 fallback) · refresh · TOTP · Google/GitHub OAuth · SAML · SCIM · aesk_ API keys
 Orchestration orchestrator/factory_pipeline.py (FactoryPipeline: semaphore=2, 30-min timeout)
                 │  12 stage supervisors in 9 waves · phase_hooks (spec gate, KG, councils, quality gate+heal)
 Stage layer   stages/s01…s12 (PhaseBase supervisors: run_task → gate → retry×3 → escalate)
                 │  call phase task_agent.run() directly (phase gates/supervisors bypassed)
 Phase library phases/p00…p21 (~52 dirs) + phases/patterns (20 pattern templates)
                 │
 Core services core/llm + model_router (Bedrock→Llama→Anthropic/Gemini→OpenRouter→Ollama)
               core/memory, knowledge_graph, domain_knowledge, domain_packs, council, quality, learning
               core/policy, approval, audit, compliance, security, identity, encryption, guardian
               core/run_app (hosts generated apps), queue (SQS), billing, webhooks, plugins, connectors
 Data          PostgreSQL 35 ORM tables (schema from init_db; Alembic chain not replayable) · Redis · ~/.aether_os/projects/<run_id> on disk
```

### 2.3 Run lifecycle (end to end)
```
POST /factory/start | SQS | MCP | rerun/branch
 → FactoryPipeline.run → Run row → accumulated_context (the only real inter-stage channel)
 → waves: [s01][s02][s03][s04][s05‖s12][s06][s07][s08‖s09‖s10][s11]
     after each sequential stage: checkpoint → hooks (spec review after s01; KG; BackendAuditCouncil; quality gate ≥80 → heal ×2 → PipelineBlockedError)
     SSE events via Redis pub/sub (phase_start/complete, file_written, llm_chunk, …)
 → council_review → background: auto-start app, DeliveryCouncil, webhooks, learning, embeddings, S3
 → generated app hosted by core/run_app as a uvicorn process, proxied at /app-preview/
```

### 2.4 Stage → phase map (what actually runs)
| Stage | Phases called | LLM? |
|---|---|---|
| s01 intake | p00 research ‖ p00b data archaeology ‖ p00c arch planner → p01 requirements (critical) → p01b integrations | yes (p00–p01b) |
| s02 architecture | p02 architecture → p02b domain IR (critical) → p02c permissions → p03 scaffold | yes (p03 no) |
| s03 backend | p04_backend (language router → p04a codegen, Go/Node/gRPC) → p04b business logic → p04c integrations | repair/workflow/integrations only; p04a is templates |
| s04 frontend | p05_frontend (+ p05b/c/d/e alt targets) | yes (pages, dashboard, compile-fix loop) |
| s05 quality | p06 security review, p06b formal verification, dimension critic | yes (p06) |
| s06 testing | p07a unit tests (template CRUD tests, pytest executed) | no |
| s07 healing | p07b self-healing (5 attempts) + p07b perf / p07c a11y / p07d E2E (never triggered) | yes |
| s08 observability | p09_observability, p11a monitoring ‖ p11b errors ‖ p11c analytics → p11d alerting | no (templates) |
| s09 devops | p08_cicd_deployment(p08) → p11 deployment → p11e enterprise (k8s/microservices only) | p08 patch, p11e terraform |
| s10 enterprise | p12a flags, p12b A/B, p13 memory, p16 IAM, p18 billing, p21 SRE; p17 control plane (opt) | no |
| s11 handoff | p10 docs → p14 portal ‖ p15 handoff → ZIP | yes (p10, p15) |
| s12 specialist (opt-in) | p19 service catalog, p20 multiregion, alt targets | no |
Dead: p04_uiux_design, all per-phase `gate.py`/`supervisor_agent.py`, legacy `pipeline.py`, `state_machine.py` (26 states, unused), `predictor.py`, `routing/`, MessageBus consumers.

### 2.5 AI / intelligence plane (core)
- **One entry point:** `LLMClient.call(prompt, task_type, context, system, max_tokens, org_id, plan, run_id, phase, attempt, temperature)` → `ModelRouter.call`: Postgres cache → monthly token budget → health-scored fallback chain (per-org overrides, trial filtering) → LangSmith trace.
- **Providers:** Bedrock (Nova Pro, Llama 3.3 70B), Anthropic, Gemini, OpenRouter, Ollama. No direct OpenAI.
- **Councils:** pre-flight + delivery JSON-verdict councils, BackendAuditCouncil (4 prompts × free OpenRouter models), 3-persona review. Block only when `ENVIRONMENT=production`.
- **Memory:** 5 disconnected stores (SQLite FTS, per-org Chroma, fingerprint DB, NetworkX run graph, JSON KG). pgvector adapter unused.
- **Learning:** golden-example promotion from rated builds feeds p04a/p05 prompts (real). Repair-learning loop does not close.
- **Domain knowledge:** 5 overlapping systems (domain_knowledge packs, domain_packs, domain_engine, KG seeds, constraint_engine) with contradictory rules.

---

## 3. Planes

Status legend: **LIVE** (enforced at runtime) · **ADVISORY** (runs, never blocks) · **GENERATED** (files emitted for the generated app, not applied) · **BROKEN** · **DEAD**.

### 3.1 SDLC plane (build pipeline)
| Step | Where | Status |
|---|---|---|
| Intake (prompt, Figma, diagram, voice, brownfield schema import) | p00, p00b, p01, core/schema_importer | LIVE; p00c always skipped on fresh run |
| Requirements / PRD / contract | p01 (+ spec_critique) | LIVE; second-check LLM call uses nonexistent `llm.complete` |
| Architecture + decisions | p02 | LIVE but cannot detect LLM failure → generic users/items CRUD accepted |
| Domain IR (canonical model) | p02b → `domain_ir.json` | LIVE; can abort pipeline on FK cycles/extra keys |
| Permission model (ABAC) | p02c | BROKEN — LLM output always discarded, default roles used |
| Scaffold | p03 | LIVE (templates); unvalidated `git clone` |
| Backend codegen | p04_backend → p04a | ✔ BROKEN at HEAD: `p04_backend/task_agent.py:17` imports nonexistent `p04b_uiux_design` (commit 0686b19) |
| Backend output quality | p04a | IR-path apps fail to boot (`schemas` not imported); role checks always 403; list endpoints 500 |
| Frontend codegen | p05 | LIVE with LLM fix loop; template baseline likely doesn't compile; token key mismatch |
| Patterns (Stripe, ERP, RBAC, websocket, IoT, social, agentic AI, marketplace…) | phases/patterns | PARTIAL — 2 templates not valid Python; injector path B writes to wrong dir |
| Spec review / change requests / rerun / branch | spec_review_gate, phase_selector | LIVE; spec gate waits 600 s every run (autonomous_mode never read) |
| Handoff (docs, ZIP, GitHub push, portal) | p10, p14, p15, s11 | PARTIAL — ZIP omits CI/k8s/docs; push capped at 50 files, public repo |

### 3.2 STLC plane (testing & quality)
| Level | Component | Executed? | Blocks? |
|---|---|---|---|
| Unit/API | p07a template CRUD tests | yes (pytest, s06) | no — score reader looks in wrong folder (test score stuck at 0.5) |
| Integration | p07b QualityMonitor L1–L4 probe | yes | no |
| Regression/heal | p07b self-healing (5 tries, 600 s) | yes | no; 5th attempt crashes (`_apply_deterministic_fallback` NameError); may rewrite tests to pass |
| Performance | p07b_perf + Locust | never in stage path | – |
| Accessibility | p07c axe | never; false pass (`skipFailures`) | – |
| E2E | p07d Playwright | never (`l1_passed` never set) | – |
| SAST | p06 bandit + CodeScanner + LLM review (first 6 KB of main.py) | yes | no; auto-patcher needs missing `astor` |
| Formal | p06b Z3 | yes | no — solver outcome predetermined (cosmetic) |
| Quality gate | `phase_hooks.py:76-155` score ≥80 → heal ×2 → block | **the only LIVE gate** | yes |
| Councils | Backend/Delivery councils | yes | only in production env |
| Platform's own tests | 629 test fns, all mocked | CI pytest | no frontend tests; 12 stages, ~25 phases, 22 core pkgs, most routers untested |

### 3.3 SRE plane
- **Platform:** Guardian (pg_dump snapshots, watchdog, threat detector, auto-recovery — LIVE but auto-recovery restores the snapshot it just took; ≥92% disk triggers destructive `pg_restore --clean`), crash recovery + app auto-restore in lifespan, workloop monitor, structlog, Prometheus (`/metrics` keyed; `/_metrics_internal` public), Sentry, LangSmith, SLA endpoint, SystemHealth page, 3 overlapping backup scripts (RTO 4 h / RPO 24 h), fail2ban, logrotate. Dead: telemetry spine, scheduler, bootstrap safe mode, predictor, external monitor bridge.
- **Generated app (GENERATED):** Prometheus/Grafana/OTEL/Alertmanager/Mimir (p11a/d), Sentry (p11b), PostHog (p11c), SRE CronJob + operator + canary (p21 — image lacks kubectl), LitmusChaos/HPA/KEDA (p20, core/chaos, capacity). p09 injected `monitoring.py` crashes the app on boot (missing `CollectorRegistry` import).

### 3.4 Security plane
- **Platform LIVE:** RS256 JWT + Redis blacklist (fail-closed), TOTP MFA, OAuth, SAML, SCIM, bcrypt + HIBP password shield, prompt guard, Fernet field encryption, SHA-256 API keys, CSP nonce/HSTS headers, rate limits, SSRF/path-traversal guards in places.
- **Critical gaps (section 10/11):**
  - ✔ `POST /system/feature-flags/{flag}` unauthenticated, mutates `os.environ` (`system_info_router.py:207`).
  - `POST /ci/webhook` no signature, arbitrary server path; `/_metrics_internal` public.
  - Refresh tokens usable as access tokens, never rotated, survive logout; HS256 migration window still accepted.
  - Cross-tenant takeover via SAML (any member edits SAML config; callback matches email across orgs).
  - ~20 IDOR endpoints (LLM traces, spec approval, compliance, MCP, run-app); portal ZIP unauthenticated.
  - `/app-preview` unauthenticated, serves LLM-written code on the platform origin, forwards the caller's `Authorization`/`Cookie`; generated apps run as host uvicorn processes with full platform env (sandbox package dead).
  - Org LLM key saved into `os.environ` → becomes other orgs' fallback; outbound webhooks signed with empty key; X-Forwarded-For spoofing bypasses login limits; runtime validators exec'd in-process from shared tree.
  - Dashboard: tokens in localStorage, CSP `unsafe-inline`/`unsafe-eval`, preview iframe `allow-scripts allow-same-origin`.
- **Zero-trust tickets:** issue path dead (docstring imports), verify warn-only.
- **Generated-app security:** Stripe refund/cancel unauthenticated + webhook upgrades all no-customer users to pro; ERP self-approval; agent `/run` exposes write_file; `.env.example` carries the real SECRET_KEY; admin `Admin1234!` logged in cleartext; Docker image runs as root and includes `.env`; demo creds baked into login pages; SAM template SQL injection.

### 3.5 Compliance plane
- **LIVE:** regex compliance scanner (HIPAA/GDPR/SOC2/PCI) + fpdf2 PDF; `compliance_manifest.json` with drift fingerprint; policy/compliance_india (DPDP, RBI, SEBI, CERT-In, export control, EU residency, AI-Act-like rules); embargo/jurisdiction pre-check on factory start; GDPR export/erase; ToS/DPA consent at signup; compliance router (ledger, export, evidence ZIP, EU AI Act risk report); `/compliance` page.
- **Not enforcing:** audit log `prev_hash` chain doesn't link fully and is never verified, and an API endpoint purges oldest rows; policy engine `check_pipeline_start` always allows and `requires_approval` is ignored; policy presets for fintech/healthcare unenforced; compliance PHI handling in generated code is comments only.
- **Generated:** p08 `check_compliance.py` CI drift job; Grafana "HIPAA Audit Events" panels; p19 platform_events table.

### 3.6 Deployment plane
- **Platform:** single VPS; `deploy/deploy.sh` (git pull → pip install unpinned → alembic to stale `revision_merge_guardian_heads` → dashboard rebuild → restart → post-deploy Guardian rehash (skips: Redis without password) → manual smoke_test.sh). Alembic has 6 heads; deploy never applies newer migrations. Path split `/opt/aetheros` vs `/home/aether_os`. `requirements.lock` missing 6 packages vs `requirements.txt`. Platform CI: pytest only, ruff non-blocking, no image build/deploy/SAST.
- **Generated app:** only p11 truly deploys (`docker build` + hardened `docker run` on the AetherOS host, `live_url`) — likely health-check failure because the container joins an `--internal` network. K8s/Helm/Terraform/compose/VPS scripts are files only, several invalid. CI self-repair engine (~3.5K LOC) broken end to end. Admin self-deploy: `/admin/system/deploy`.

### 3.7 Admin control plane
- **Platform:** `admin_router`, `admin_platform_router` (git deploy, file write, prune, kill-all), `admin_quality_router`, settings routers (LLM routing, org keys, phase enable/priority, autonomous mode, SAML/SCIM), org delete/restore, Guardian snapshot/restore (superadmin — but superadmin cannot be granted via any API), feature flags (unauthenticated + inert), kill switch. UI gating is client-side only (`AdminRoute` wraps 4 routes).
- **HITL governance:** spec review gate (LIVE), p00/p01 decision gates, p05 Gate 2/3 (Gate 3 has no effect), DecisionsPanel, ClientPortal approve (BROKEN — 500), escalation approval and guided questionnaires (DEAD via docstring imports), human-decision wait has no working timeout.
- **Generated app:** p12a flag admin API, p19 cloud console, p14 ticket portal, p17 CRD controller (doesn't compile).

### 3.8 API management plane
- **Platform:** ~282 routes / 55 routers, all mounted; `/api` prefix strip, `/v2` only for plugins; rate limits (auth by IP; factory start per org/min/hour/concurrent + DB cap 3/org, 10 global); org API keys (`aesk_`); outbound webhooks (`run.*`, `phase.completed`, `decision.requested`, `deploy.completed`); MCP REST facade (reads stale SQLite); SSE single-use tokens; plugins/connectors/marketplace; OpenAPI disabled in prod. Missing: versioning, per-key quotas, idempotency keys, and any UI to mint programmatic API tokens (CLI/VS Code reuse login JWT, no MFA). API_REFERENCE.md documents ~75 endpoints, with nonexistent `/v2/auth`, `/v2/factory`.
- **Generated app:** consistent CRUD under `/api`, OpenAPI docs, `api_routes.json` FE↔BE contract, Postman collection (p15), OpenMeter metering + Stripe (p18 — paths never match), service catalog (p19).

### 3.9 Additional planes found
| Plane | Contents |
|---|---|
| **Data plane** | 35 ORM tables; org_id tenancy by hand-written filters (no RLS, several queries skip it); 12 tables without migrations; Alembic chain can't build an empty DB; DATA_MODEL.md lists 25/35 |
| **Learning / memory** | golden builds, GlobalPattern/UserPattern, embeddings, KG, repair learning, IntelligenceHub/Learning/MemoryInspector pages |
| **Billing / monetisation** | Razorpay + Stripe routers, trial counter, storage limits, plan-gated models/plugins; downgrade endpoint grants pro/enterprise; verify-payment trusts body plan |
| **Factory observability** | SSE events, phase_completions, confidence trail, cost tracking (5 places, 4 price tables), TraceTab |
| **Collaboration / tenancy** | orgs, workspaces (cosmetic), OrgSwitcher, notifications, client portal |
| **Developer surfaces** | CLI (download & logs broken), VS Code ext (missing icon → can't package), MCP server |
| **Marketing** | `vkatos_deploy/` VKatOS site (still tracked) |

---

## 4. Systemic root causes

1. **July import-hoisting commits (`d81e33c`, `0686b19`).** ✔ 26 imports trapped in `factory_pipeline.py`'s docstring → ~48 undefined names hidden by `try/except` (approval gate, zero-trust, questionnaires, notifications, autonomous mode, create_run…). ✔ p04_backend wrong module name → no backend generated. Ruff flags 25 more undefined names elsewhere.
2. **Stage refactor left p-phase plumbing behind.** Stages call task agents directly, so every phase gate/supervisor is dead; hooks still read `p04_backend/...` paths while s03 writes `s03_backend/p04_backend/...` (BackendAuditCouncil, pattern injection, S11 merge, s10 autowire, quality score all miss). Parallel waves drop stage outputs (security findings, `live_url`, resume checkpoint).
3. **Swallowed exceptions.** The "no bare except" rule became `except Exception as e: logger.warning(...)`, which keeps failures invisible: Anthropic tier (✔ `model_router.py:466` passes extra `client` arg → TypeError every call), p01 second check, p00 imports, questionnaire writes.
4. **Generate-only enterprise phases.** ~25 phases emit files that are never applied, often invalid, and excluded from the delivery ZIP.
5. **Mocked tests.** 629 mocked tests passed while backend generation, the Anthropic tier, and s07 were broken.

---

## 5. Priority fix list (from all sections)

| P | Issue | Location |
|---|---|---|
| P0 | Backend generation broken (wrong import) | `phases/p04_backend/task_agent.py:17` |
| P0 | Docstring-trapped imports | `orchestrator/factory_pipeline.py:10-35` |
| P0 | Unauthenticated feature-flag write, CI webhook, `_metrics_internal` | `gateway/routers/system_info_router.py:207`, ci router, metrics router |
| P0 | SAML cross-tenant takeover; refresh-as-access tokens; billing self-upgrade | gateway auth/billing (§11) |
| P0 | `/app-preview` unauthenticated + header forwarding; generated apps unsandboxed | `app_preview_router`, `core/run_app` |
| P0 | Plaintext VPS password in uncommitted `plans2.md:205` — do not commit | `plans2.md` |
| P1 | Anthropic tier always fails | `core/model_router.py:466` |
| P1 | IR-path generated apps can't boot (`schemas` import), role checks 403 | `p04a/ir_generator_helpers.py:52,224-238` |
| P1 | s07 crashes when quality gate passes (`TaskResult(output=)`) | `stages/s07_healing` |
| P1 | Self-healing 5th-attempt NameError; overwrites tests | `p07b_self_healing/task_agent.py:217,252` |
| P1 | Parallel waves drop outputs; hook path mismatch | `orchestrator/parallel_runner.py`, `phase_hooks*.py` |
| P1 | Quality score reads wrong test path | `core/quality/metrics.py:184-200` |
| P1 | ~20 IDOR endpoints; org key → os.environ; webhook empty HMAC | §10, §11 |
| P2 | Alembic: 6 heads, not replayable; deploy target stale | `alembic/`, `deploy/deploy.sh` |
| P2 | p09 monitoring.py boot crash; p11 internal network | `p09_observability`, `p11_deployment` |
| P2 | Spec gate always waits 600 s | fixed by P0 docstring fix |
| P2 | Audit chain unverifiable + purge; policy engine always-allow | `core/audit`, `core/policy` |
| P3 | Dead code (~15K LOC across slices), doc drift (phase counts, API_REFERENCE, DATA_MODEL), pricing inconsistency | various |

---

## 6. What works today (demo-safe, once P0s are fixed)
- Prompt → research/requirements/architecture/domain IR with real LLM calls and fallbacks.
- Frontend generation with LLM page writers and compile-fix loop; golden-example retrieval.
- Self-healing loop attempts 1–4 with real pytest + uvicorn probes.
- Single-host Docker deploy of the generated app + `/app-preview` hosting (after auth fix).
- Multi-tenant platform: JWT/MFA/OAuth/SAML/SCIM, Guardian backups, compliance PDF/evidence ZIP, Razorpay/Stripe billing, SSE live run view, CLI/VS Code basics.

## 7. Open questions (need a VPS / real run)
1. Which commit is the VPS running? If before `0686b19`/`d81e33c`, prod still generates backends.
2. Do the 12 unmigrated tables exist on the VPS; which Alembic heads are applied?
3. Is SQS used in prod? Is Bedrock token renewed, and are OpenRouter/Ollama configured (since Anthropic tier is broken)?
4. Does p11's `--internal` network actually block the published port on the VPS?
5. Which frontend copy (`<project>/frontend` vs `p05_frontend/frontend`) is canonical for run_app?
6. Which pattern-injection path is intended (p04a keyword vs PatternSelector hook)?
