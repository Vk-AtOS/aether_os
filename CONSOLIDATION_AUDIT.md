# CONSOLIDATION AUDIT — AetherOS
**Date:** 2026-04-19  
**Repos audited:** Vk-AtOS/Aether-one · Vk-AtOS/aether2 · Vk-AtOS/DCSP  
**Total Python files read:** ~260  
**Output of:** Phase 0 — read-everything-first audit before any code is written

---

## 1. REPO OVERVIEW

### Aether-one (`/Users/apple/Desktop/Aether-one/`)
- **Design intent:** Enterprise-grade, offline-first code governance, fix engine, and software delivery platform. Takes existing codebases, applies AI-driven fixes, enforces policies, routes through human approval gates, scaffolds new domain-specific apps (Django/Next.js/ROS2/Firmware).
- **Entry point:** `aetherone/main.py` → Typer CLI → boots via `aetherone/bootstrap/runtime_manager.py`
- **Package:** `aetherone/`
- **Secondary snapshot demo:** `aether-one_snapshot_demo/aetherone/` (older, subset — do not use)
- **Key strength:** The most complete governance, policy, approval, identity, licensing, and telemetry layer of the three repos. Well-tested (35+ test files). Production-grade enterprise patterns.
- **Notable:** Has duplicate folder (`aether-one_snapshot_demo/`) with older, stripped-down version of same code — ignore this subtree during migration.

### aether2 (`/Users/apple/Desktop/aether2/`)
- **Design intent:** Autonomous NL-to-code pipeline. Takes a plain-English requirement, runs a linear pipeline of 12 specialist agents (requirements → architecture → codegen → review → security → tests → docs), self-heals with feedback loop (max 3 retries), exposes REST API + Typer CLI.
- **Entry point:** `main.py` → `aether/cli/main.py` or `aether/api/app.py`
- **Package:** `aether/`
- **Key strength:** Clean, lean pipeline architecture with DCSP stall monitoring and predictive failure engine. The retry/feedback loop is well-designed.
- **Notable:** All Ollama-based (local LLMs). Generated code is never written to disk — only returned in the API response. MemoryAgent is a pure in-memory dict.

### DCSP (`/Users/apple/Desktop/DCSP/`)
- **Design intent:** CI/CD self-healing system. Receives CI failure webhooks, parses logs, localises root cause via AST + call graph, fingerprints errors, reuses known patches from memory, or generates new patches via SLM (Ollama/deepseek-coder). Validates patches in sandbox, applies to repo, opens PR.
- **Entry point:** `main.py` → `src/api/main.py` (FastAPI)
- **Package:** `src/`
- **Key strength:** The most production-complete of the three. Real DB layer (SQLAlchemy + SQLite/PostgreSQL), multi-tenant, real webhook handling, real PR creation, Docker sandbox validation, prediction engine, federation registry. The DFLE (log parser + AST localiser + call graph) and DSEE (boundary + impact + test runner + verifier) subsystems are solid.
- **Notable:** Heavy dependency set (Celery, Redis, PostgreSQL, Docker). Some features need simplification for local-dev mode.

---

## 2. COMPLETE MODULE INVENTORY

### Aether-one (`aetherone/`)

| File | What it does | Quality | Migration target |
|------|-------------|---------|-----------------|
| `main.py` | CLI entrypoint (Typer: start/info/version), boots bootstrap | SOLID | `aether_os/main.py` |
| `bootstrap/runtime_manager.py` | 7-phase deterministic startup, power level management | SOLID | `core/bootstrap/runtime_manager.py` |
| `bootstrap/environment_detector.py` | OS/CPU/RAM/disk detection + minimum requirements check | SOLID | `core/bootstrap/environment_detector.py` |
| `bootstrap/offline_guard.py` | Network blocking + violation monitoring | SOLID | `core/bootstrap/offline_guard.py` |
| `bootstrap/safe_mode.py` | Failure detection and recovery | SOLID | `core/bootstrap/safe_mode.py` |
| `policy_engine.py` | Enterprise policy with strict mode, org presets (DEFAULT/FINTECH/HEALTHCARE), risk-based approval routing, JSON persistence | SOLID ⭐ | `core/policy/engine.py` |
| `licensing.py` | HMAC-SHA256 token licensing, feature gating, node-lock, expiry | SOLID ⭐ | `core/licensing/licensing.py` |
| `identity.py` | RBAC: users, bcrypt passwords, JWT, SQLite via SQLAlchemy | SOLID | `core/identity/identity.py` |
| `identity_engine.py` | Extended identity operations | SOLID | `core/identity/engine.py` |
| `zero_trust_exec.py` | HMAC-signed execution tickets, canonical payload signing | SOLID ⭐ | `core/identity/zero_trust.py` |
| `approvals_core.py` | SQLite-backed approval tickets: PENDING/APPROVED/DENIED with full action history | SOLID ⭐ | `core/approval/store.py` |
| `approval_workflow.py` | Risk→decision mapping (NONE/LOW→AUTO, MEDIUM→REQUIRE, HIGH→BLOCK), JSONL audit log | SOLID ⭐ | `core/approval/workflow.py` |
| `arbitration.py` | Multi-agent conflict resolution with deterministic voting, human escalation | SOLID | `core/approval/arbitration.py` |
| `deterministic_scheduler.py` | Seed-based deterministic task execution, priority queue, WAL audit | SOLID | `core/scheduler/scheduler.py` |
| `telemetry_spine.py` | Structured telemetry events with JSONL sink | SOLID | `core/telemetry/spine.py` |
| `time_travel_snapshots.py` | SHA-256 integrity, tar.gz archives, index file, restore/verify | SOLID ⭐ | `core/snapshot/manager.py` |
| `orchestrator.py` | Fix session coordinator: workspace scan → FixCandidate → diff apply → FixDecision | PARTIAL (broken `_apply_unified_diff`) | `orchestrator/fix_orchestrator.py` |
| `fix_engine.py` | Rule-based + LLM-based Python fix engine (syntax + runtime phases), policy-gated | PARTIAL (bad rules — see bugs) | `phases/p05_review/fix_engine.py` |
| `refactor_engine.py` | AI + deterministic refactoring, AST-validates result | SOLID | `phases/p05_review/refactor_engine.py` |
| `graph_rag.py` | Offline repo graph: import analysis, symbol index, file neighbors | SOLID | `core/memory/graph_rag.py` |
| `temporal_risk.py` | Fix-frequency based file risk forecasting (frequency + recency + severity scores) | SOLID | `phases/p08_cicd/temporal_risk.py` |
| `temporal_prediction.py` | Additional temporal prediction utilities | SOLID | `phases/p08_cicd/temporal_prediction.py` |
| `agents/adaptive_hybrid_mesh.py` | AHM: deterministic routing brain, health scoring, WAL audit, graceful fallback | SOLID ⭐ | `orchestrator/routing/ahm.py` |
| `agents/base.py` | Agent base class + registry | SOLID | `agents/base.py` |
| `agents/mesh.py` | Legacy mesh wrapper (calls AHM for backward compat) | PARTIAL | `agents/mesh.py` |
| `agents/code_review_agent.py` | LLM-driven code review agent | SOLID | `phases/p05_review/agents.py` |
| `agents/fix_engine_agent.py` | Fix engine agent wrapper | SOLID | `phases/p05_review/agents.py` |
| `agents/security_analyzer_agent.py` | Security analysis agent | SOLID | `phases/p06_security/agents.py` |
| `agents/test_agent.py` | Test generation agent | SOLID | `phases/p07_testing/agents.py` |
| `agents/refactor_agent.py` | Refactor agent | SOLID | `phases/p05_review/agents.py` |
| `agents/snapshot_agent.py` | Snapshot creation agent | SOLID | `agents/tools/snapshot_tool.py` |
| `agents/repo_reasoning_agent.py` | Repo analysis agent | SOLID | `phases/p01_requirements/agents.py` |
| `agents/memory_knowledge_agent.py` | Memory/knowledge retrieval agent | PARTIAL | `core/memory/` |
| `agents/stability_guardian.py` | Stability monitoring agent | SOLID | `phases/p08_cicd/agents.py` |
| `agents/risk_agent_service.py` | Risk assessment service | SOLID | `core/approval/` |
| `agents/policy_agent_service.py` | Policy evaluation service | SOLID | `core/policy/` |
| `agents/red_team_safety_agent.py` | Red team / safety testing agent | SOLID | `phases/p06_security/agents.py` |
| `agents/system_spec_profiler.py` | System hardware profiler | SOLID | `core/bootstrap/` |
| `agents/bus_network_manager.py` | Agent bus/network manager | PARTIAL | `orchestrator/routing/` |
| `framework_generators.py` | Domain-specific scaffold generators (Django/FinTech, Next.js/Healthcare, ROS2, Firmware) | SOLID | `phases/p03_scaffolding/generators.py` |
| `prompt_templates.py` | Prompt template bundles for framework generation | SOLID | `phases/p03_scaffolding/prompts.py` |
| `sandbox_manager.py` | Guarded Python execution sandbox | SOLID | `core/sandbox/manager.py` |
| `security_agent.py` | Comprehensive security analysis (OWASP, secrets, injection) | SOLID | `phases/p06_security/engine.py` |
| `test_generation.py` | pytest test generation | SOLID | `phases/p07_testing/engine.py` |
| `test_tools.py` | Test execution utilities | SOLID | `phases/p07_testing/tools.py` |
| `coverage_assistant.py` | Test coverage analysis | SOLID | `phases/p07_testing/coverage.py` |
| `python_tools.py` | Python syntax check + run utilities | SOLID | `core/sandbox/python_tools.py` |
| `llm_router.py` | Ollama-based LLM router with model selection | SOLID | `core/llm/ollama_client.py` (then replaced by unified client) |
| `llm_tools.py` | LLM-powered fix proposal utility | SOLID | `core/llm/` |
| `model_management.py` | Ollama model pull/list/status management | SOLID | `core/llm/model_management.py` |
| `workspace_api.py` | File/project workspace CRUD operations | SOLID | `gateway/workspace.py` |
| `api.py` | FastAPI app (broken CORS) | PARTIAL (allow_origins=["*"]) | `gateway/api.py` |
| `db.py` | SQLAlchemy async DB setup | SOLID | `core/db.py` |
| `db_migrations.py` | Schema migration utilities | SOLID | `core/db_migrations.py` |
| `models.py` | All SQLAlchemy + Pydantic models | SOLID | `core/models.py` |
| `cli.py` | Typer CLI commands | SOLID | `gateway/cli.py` |
| `client.py` | httpx CLI client (thin, calls local API) | SOLID | `gateway/client.py` |
| `onboarding.py` | Project onboarding flow | SOLID | `phases/p01_requirements/onboarding.py` |
| `architecture_onboarding.py` | Architecture-specific onboarding | SOLID | `phases/p02_architecture/onboarding.py` |
| `org_config.py` | Organisation-level configuration | SOLID | `core/config/org.py` |
| `compliance.py` | Compliance rules engine | SOLID | `core/policy/compliance.py` |
| `diagnostics.py` | System diagnostics reporting | SOLID | `core/bootstrap/diagnostics.py` |
| `error_recovery.py` | Error recovery orchestration | SOLID | `orchestrator/recovery.py` |
| `file_watcher.py` | File system change watcher | SOLID | `core/` |
| `filesystem.py` | Filesystem snapshot utilities | SOLID | `core/snapshot/filesystem.py` |
| `guarded_decision.py` | Guarded decision-making with approval gate | SOLID | `core/approval/guarded.py` |
| `intent_simulation.py` | Intent/impact simulation before actions | SOLID | `core/approval/` |
| `live_guardian.py` | Live system guardian / watchdog | SOLID | `orchestrator/` |
| `ai_arbitration.py` | AI-assisted conflict arbitration | SOLID | `core/approval/arbitration.py` |
| `agent_runtime.py` | Agent lifecycle runtime management | SOLID | `agents/runtime.py` |
| `comm/message.py` | Agent-to-agent message passing | SOLID | `agents/comm/` |
| `monorepo_reasoning.py` | Monorepo analysis and reasoning | SOLID | `phases/p02_architecture/` |
| `multi_path_planner.py` | Multi-path execution planning | SOLID | `orchestrator/planner.py` |
| `neural_synthesis.py` | Neural code synthesis utilities | PARTIAL | `phases/p04_codegen/` |
| `safety_pattern_miner.py` | Safety pattern mining from history | SOLID | `core/memory/` |
| `iot_robotics_support.py` | IoT/Robotics domain support | SOLID | `phases/p03_scaffolding/` |
| `lang_framework_detector.py` | Language + framework detection | SOLID | `phases/p01_requirements/` |
| `packaging_macos.py` | macOS app packager | SOLID | `phases/p10_packaging/macos.py` |
| `packaging_windows.py` | Windows app packager | SOLID | `phases/p10_packaging/windows.py` |
| `quantum_optimizer.py` | Quantum-inspired optimisation (placeholder) | STUB | DISCARD |
| `version.py` | Version string | SOLID | `core/version.py` |
| `cicd_agent.py` | CI/CD agent wrapper | SOLID | `phases/p08_cicd/` |
| `ui_backend.py` | WebSocket UI backend | SOLID | `gateway/` |
| `policy_agent.py` | Policy evaluation agent | SOLID | `core/policy/` |
| `policy_engine.py` | (see above) | SOLID ⭐ | `core/policy/engine.py` |
| `refactor_sample.py` | Example refactor demo | STUB | DISCARD |
| `repository_knowledge.py` | Repository knowledge base | SOLID | `core/memory/` |

### aether2 (`aether/`)

| File | What it does | Quality | Migration target |
|------|-------------|---------|-----------------|
| `agents/orchestrator.py` | Pipeline sequencer: dispatch + run_pipeline (7 stages, 3-retry loop, DCSP monitor) | SOLID ⭐ | `orchestrator/pipeline.py` |
| `agents/specialists.py` | 12 agents: Requirements, RepoReasoning, Architecture, CodeGen, Review, Security, Test, Refactor, Performance, Documentation, Memory, Snapshot | SOLID ⭐ | Distributed across `phases/p01`–`p09` |
| `agents/base.py` | BaseAgent interface (can_handle + handle) | SOLID | `agents/base.py` (merge) |
| `llm/engine.py` | Ollama LLM engine: model routing, fallback, generate/analyze/generate_code, ledger logging | SOLID | REPLACE with unified client in `core/llm/client.py` |
| `policy/engine.py` | Simple allow/deny/escalate policy engine with YAML loader | PARTIAL | DISCARD — use Aether-One's richer engine |
| `memory/ledger.py` | SQLite run/event ledger with thread-safe ops | SOLID | `core/audit/ledger.py` (merge) |
| `audit/logger.py` | JSONL append-only audit logger | SOLID | `core/audit/logger.py` (merge) |
| `snapshots/manager.py` | SHA-256 tar.gz snapshot manager | SOLID | DISCARD — use Aether-One's (same design, AO's is more complete) |
| `sandbox/guard.py` | Forbidden pattern scanner + pytest runner | SOLID | `core/sandbox/guard.py` |
| `monitor/dcsp_bridge.py` | Stage stall monitor: timing thresholds, health check | SOLID ⭐ | `orchestrator/monitor.py` |
| `monitor/predictor.py` | Historical stage timing predictor (avg + std dev) | SOLID ⭐ | `orchestrator/predictor.py` |
| `notify/webhooks.py` | Slack/email webhook notifier for pipeline events | SOLID | `core/telemetry/webhooks.py` |
| `core/config.py` | YAML config loader (singleton) | SOLID | `core/config/loader.py` |
| `core/models.py` | Command + ExecutionContext Pydantic models | SOLID | `orchestrator/context.py` |
| `core/errors.py` | Permission, SandboxViolation, InvariantViolation errors | SOLID | `core/errors.py` |
| `api/app.py` | FastAPI REST API (broken CORS, custom JWT) | PARTIAL | `gateway/api.py` (rewrite JWT, fix CORS) |
| `cli/main.py` | Typer CLI: build/history/inspect/predict/monitor | SOLID | `gateway/cli.py` (merge) |
| `generation/` | Empty placeholder | STUB | DISCARD |
| `reasoning/` | Empty placeholder | STUB | DISCARD |

### DCSP (`src/`)

| File | What it does | Quality | Migration target |
|------|-------------|---------|-----------------|
| `pipeline.py` | End-to-end repair orchestrator: log→localise→fingerprint→match→SLM→DSEE→sandbox→result | SOLID ⭐ | `phases/p08_cicd/pipeline.py` |
| `dfle/log_parser.py` | CI log parser: extracts stack traces, test names, error patterns (Python/Java/JS) | SOLID ⭐ | `phases/p08_cicd/dfle/log_parser.py` |
| `dfle/localizer.py` | Root cause candidate scoring: AST proximity + stack depth + dep radius + test coverage | SOLID ⭐ | `phases/p08_cicd/dfle/localizer.py` |
| `dfle/ast_index.py` | Incremental AST index: function/class definitions per file | SOLID ⭐ | `phases/p08_cicd/dfle/ast_index.py` |
| `dfle/call_graph.py` | Python call graph builder | SOLID ⭐ | `phases/p08_cicd/dfle/call_graph.py` |
| `dsee/boundary.py` | Boundary enforcement: validates patch scope | SOLID | `phases/p08_cicd/dsee/boundary.py` |
| `dsee/impact.py` | Impact simulation: dependency radius + risk level | SOLID | `phases/p08_cicd/dsee/impact.py` |
| `dsee/test_runner.py` | Tiered test runner (unit → integration → e2e) | SOLID | `phases/p08_cicd/dsee/test_runner.py` |
| `dsee/verifier.py` | Stability verification after patch | SOLID | `phases/p08_cicd/dsee/verifier.py` |
| `slm/ollama_client.py` | Ollama deepseek-coder client with semaphore, retry, diff validation | SOLID | REPLACE with unified LLM client |
| `slm/context_builder.py` | RAG context builder from CI failure + AST index | SOLID ⭐ | `phases/p08_cicd/slm/context_builder.py` |
| `slm/prompt_templates.py` | Repair prompt templates | SOLID | `phases/p08_cicd/slm/prompts.py` |
| `slm/patch_validator.py` | Unified diff validation + extraction | SOLID ⭐ | `phases/p08_cicd/slm/validator.py` |
| `feedback/fingerprinter.py` | Error log fingerprinting (normalise → SHA-256 hex) | SOLID ⭐ | `core/memory/fingerprinter.py` |
| `feedback/repair_memory.py` | JSON file-based repair memory (fingerprint→patch, success count) | PARTIAL | REPLACE with SQLite continuous learning module |
| `patch_reuse/fingerprint.py` | Additional patch fingerprinting | SOLID | `core/memory/fingerprinter.py` (merge) |
| `patch_reuse/matcher.py` | Patch similarity matcher | SOLID | `core/memory/matcher.py` |
| `repo/patch_applier.py` | git apply wrapper: dry-run check → apply → branch → commit | SOLID ⭐ | `phases/p08_cicd/repo/patch_applier.py` |
| `repo/pr_creator.py` | GitHub/GitLab PR/MR creator via API | SOLID ⭐ | `phases/p08_cicd/repo/pr_creator.py` |
| `repo/git_manager.py` | Git repo clone/fetch management | SOLID | `phases/p08_cicd/repo/git_manager.py` |
| `repo/ast_indexer.py` | Universal AST indexer (delegates to language adapters) | SOLID | `phases/p08_cicd/dfle/ast_index.py` (merge) |
| `repo/indexer.py` | Universal multi-language indexer | SOLID | `phases/p08_cicd/repo/indexer.py` |
| `sandbox/docker_sandbox.py` | Docker-based patch validation sandbox | SOLID | `phases/p08_cicd/sandbox/docker.py` |
| `intelligence/predictor.py` | ML-based failure prediction | SOLID | `phases/p08_cicd/intelligence/predictor.py` |
| `knowledge/graph.py` | Knowledge graph for error patterns | SOLID | `core/memory/knowledge_graph.py` |
| `lang/detector.py` | Multi-language detector (Python/Java/JS) | SOLID | `phases/p08_cicd/lang/detector.py` |
| `lang/python_adapter.py` | Python language AST adapter | SOLID | `phases/p08_cicd/lang/python.py` |
| `lang/java_adapter.py` | Java language adapter | SOLID | `phases/p08_cicd/lang/java.py` |
| `lang/javascript_adapter.py` | JavaScript language adapter | SOLID | `phases/p08_cicd/lang/javascript.py` |
| `adapters/github_actions.py` | GitHub Actions CI adapter | SOLID | `phases/p08_cicd/adapters/github.py` |
| `adapters/gitlab_ci.py` | GitLab CI adapter | SOLID | `phases/p08_cicd/adapters/gitlab.py` |
| `adapters/jenkins.py` | Jenkins CI adapter | SOLID | `phases/p08_cicd/adapters/jenkins.py` |
| `adapters/detector.py` | CI platform auto-detection | SOLID | `phases/p08_cicd/adapters/detector.py` |
| `api/main.py` | FastAPI app entrypoint | SOLID | `gateway/api.py` (merge) |
| `api/webhook.py` | CI webhook handler (broken: _CALL_GRAPH=None) | PARTIAL | `phases/p08_cicd/webhook.py` |
| `api/auth.py` | JWT auth | SOLID | `gateway/auth.py` |
| `api/auth_router.py` | Auth routes | SOLID | `gateway/auth.py` (merge) |
| `api/dashboard.py` | Dashboard endpoint | SOLID | `gateway/` |
| `api/predict.py` | Prediction API endpoint | SOLID | `gateway/` |
| `api/tenant_router.py` | Multi-tenant routing | SOLID | `gateway/tenants.py` |
| `api/tenant_middleware.py` | Tenant isolation middleware | SOLID | `gateway/tenants.py` (merge) |
| `api/websocket_manager.py` | WebSocket manager | SOLID | `gateway/websockets.py` |
| `api/incident_router.py` | Incident management endpoints | SOLID | `gateway/` |
| `api/github_router.py` | GitHub App integration routes | SOLID | `gateway/` |
| `api/api_key_auth.py` | API key authentication | SOLID | `gateway/auth.py` (merge) |
| `api/api_key_router.py` | API key management routes | SOLID | `gateway/` |
| `api/state.py` | Global job history state | PARTIAL | `orchestrator/state.py` |
| `db/job_repo.py` | Job DB repository | SOLID | `core/db/repos/job.py` |
| `db/audit_repo.py` | Audit DB repository | SOLID | `core/db/repos/audit.py` |
| `db/incident_repo.py` | Incident DB repository | SOLID | `core/db/repos/incident.py` |
| `db/tenant_repo.py` | Tenant DB repository | SOLID | `core/db/repos/tenant.py` |
| `db/api_key_repo.py` | API key DB repository | SOLID | `core/db/repos/api_key.py` |
| `database.py` | SQLAlchemy DB setup | SOLID | `core/db.py` (merge) |
| `models.py` | All DB models | SOLID | `core/models.py` (merge) |
| `federation/registry_server.py` | Federation pattern registry (in-memory, no SQLite) | PARTIAL (in-memory only) | `core/memory/federation.py` |
| `federation/registry_client.py` | Federation client | SOLID | `core/memory/federation.py` (merge) |
| `federation/anonymizer.py` | Pattern anonymizer before federation share | SOLID | `core/memory/federation.py` (merge) |
| `notifications/router.py` | Multi-channel notification router | SOLID | `core/telemetry/notifications.py` |
| `notifications/slack_notifier.py` | Slack notifier | SOLID | `core/telemetry/notifications.py` (merge) |
| `notifications/email_notifier.py` | Email notifier | SOLID | `core/telemetry/notifications.py` (merge) |
| `queue/worker.py` | Celery task worker | SOLID | Simplify — use asyncio queue for local mode |
| `queue/repair_task.py` | Repair task definition | SOLID | `phases/p08_cicd/tasks.py` |
| `queue/tasks.py` | Task definitions | SOLID | `phases/p08_cicd/tasks.py` (merge) |
| `queue/retry_manager.py` | Retry management | SOLID | `orchestrator/retry.py` |
| `security/hmac_verifier.py` | GitHub webhook HMAC verification | SOLID | `gateway/security.py` |
| `security/rate_limiter.py` | Rate limiting | SOLID | `gateway/security.py` (merge) |
| `security/audit.py` | Security audit logging | SOLID | `core/audit/` (merge) |
| `security/secret_manager.py` | Secret management | SOLID | `core/config/secrets.py` |
| `billing.py` | Usage billing tracking | SOLID | `gateway/billing.py` |
| `redis_cache.py` | Redis cache layer | PARTIAL | optional — SQLite fallback for local mode |
| `license_check.py` | License validation (hardcoded SECRET_KEY bug) | BROKEN | REPLACE with Aether-One's licensing system |
| `integrations/aether2_bridge.py` | Bridge to aether2 (incomplete wiring) | STUB | `orchestrator/` (wire properly) |
| `integrations/github_app.py` | GitHub App integration | SOLID | `gateway/github_app.py` |

---

## 3. OVERLAPPING / DUPLICATE COMPONENTS

### 3.1 LLM Client / Ollama Interface
- **aether2** `aether/llm/engine.py`: `LLMEngine` — model routing, fallback chain, task→model map, per-call ledger logging. Uses `urllib.request` (no deps).
- **Aether-one** `aetherone/llm_router.py` + `llm_tools.py`: Ollama LLM router + fix proposal utilities.
- **DCSP** `src/slm/ollama_client.py`: `OllamaClient` — semaphore-limited, retry with diff validation, uses `requests`.
- **Winner:** DISCARD ALL THREE — replace with new `core/llm/client.py` using Anthropic API as primary + Ollama fallback. Aether2's task routing logic and DCSP's retry/validation pattern are worth reusing in the new client.

### 3.2 Policy Engine
- **aether2** `aether/policy/engine.py`: Simple `allow/deny/escalate` with fnmatch glob patterns + YAML loader. No risk levels, no org presets.
- **Aether-one** `aetherone/policy_engine.py`: Full `PolicyConfig` with strict mode, org profiles (DEFAULT/FINTECH/HEALTHCARE), risk-based approval routing, JSON persistence, deterministic evaluation.
- **Winner:** Aether-one's engine — it's strictly more capable and covers all of aether2's use cases.

### 3.3 Snapshot Manager
- **aether2** `aether/snapshots/manager.py`: SHA-256 tar.gz archives, index.json, restore with integrity check. Uses `InvariantViolation`.
- **Aether-one** `aetherone/time_travel_snapshots.py`: Same core design (SHA-256, tar.gz, JSON index) but with more restore options (dir vs single file), delete, exists check.
- **Winner:** Aether-one's — superset of aether2's. Aether2's version can be discarded.

### 3.4 License Checker
- **aether2** `license_check.py`: Dead simple — just checks a hardcoded SECRET_KEY. No real enforcement.
- **DCSP** `license_check.py`: SHA-256 hash check but SECRET_KEY hardcoded (`"vkatos_enterprise_secret_2026"`).
- **Aether-one** `aetherone/licensing.py`: Full HMAC-SHA256 token system, feature gating, expiry, node-lock, `LicenseManager` class, env var secret.
- **Winner:** Aether-one's — the only real implementation.

### 3.5 Memory / Ledger / Storage
- **aether2** `aether/memory/ledger.py`: `DecisionLedger` — SQLite with runs/events/snapshots tables, thread-safe.
- **aether2** `aether/agents/specialists.py` `MemoryAgent`: In-memory dict. Lost on restart.
- **DCSP** `src/feedback/repair_memory.py`: `RepairMemory` — JSON file persistence, fingerprint→patch mapping, success count.
- **Aether-one**: No unified memory module, but has `repository_knowledge.py`, `safety_pattern_miner.py`, `memory_knowledge_agent.py`.
- **Winner:** Build new `core/memory/` continuous learning module (SQLite + FTS5). Migrate DCSP's fingerprint scheme into it. Replace aether2's MemoryAgent dict. Keep aether2's ledger as the audit/run-log layer.

### 3.6 Audit Logger
- **aether2** `aether/audit/logger.py`: `AuditLogger` — in-memory list + optional JSONL file append.
- **Aether-one** `aetherone/approvals_core.py`: JSONL audit entries to `.aetherone_audit.log`.
- **DCSP** `src/security/audit.py` + `src/db/audit_repo.py`: DB-backed audit via SQLAlchemy.
- **Winner:** Build a unified `core/audit/` that wraps JSONL (hot path, append-only) + SQLite (queryable), combining all three patterns.

### 3.7 Sandbox / Test Runner
- **aether2** `aether/sandbox/guard.py`: Forbidden pattern scanner + `subprocess`-based pytest runner. Validates test files in `/tmp`.
- **Aether-one** `aetherone/sandbox_manager.py`: More complete — guarded Python execution, policy integration.
- **DCSP** `src/sandbox/docker_sandbox.py`: Docker-based sandbox (most isolated, but heavy dep).
- **Winner:** Use Aether-one's sandbox as default + DCSP's Docker sandbox as an optional upgrade for CI phase. aether2's guard.py can be merged in.

### 3.8 Webhook Notifier
- **aether2** `aether/notify/webhooks.py`: Slack/email on pipeline start/stage-fail/complete.
- **DCSP** `src/notifications/`: Multi-channel router (Slack, email, push). More complete.
- **Winner:** DCSP's notification router. aether2's webhooks are a subset.

### 3.9 RBAC / Identity
- **Aether-one** `aetherone/identity.py`: bcrypt + JWT + SQLite users table.
- **DCSP** `src/api/auth.py` + `src/api/auth_router.py`: Similar JWT auth.
- **Winner:** Aether-one's identity.py — more complete (roles, RBAC helpers).

### 3.10 Base Agent Interface
- **aether2** `aether/agents/base.py`: `BaseAgent` with `can_handle(Command) → bool` + `handle(Command, ExecutionContext)`.
- **Aether-one** `aetherone/agents/base.py`: `Agent` with role/goal/backstory, `AgentContext`, `AgentRegistry`, health scoring hooks.
- **Winner:** Aether-one's base — richer interface needed for AHM routing. aether2's specialist agents need to be adapted to implement the AO interface.

---

## 4. BROKEN COMPONENTS — EXACT BUGS

### Bug 1 — Aether-one: `_apply_unified_diff` calls non-existent function
- **File:** `aetherone/orchestrator.py` line **317**
- **Bug:** `difflib.patch_from_unified_diff(patch)` — this function **does not exist** in Python's `difflib` module. The actual difflib API has no patch application function. The whole `_apply_unified_diff` method is broken.
- **Fix:** Replace with `patch` command via subprocess, or use the `whatthepatch` library (`pip install whatthepatch`), or implement manual unified diff application by parsing `@@` hunks.
```python
# FIX: Use subprocess git apply or whatthepatch
import whatthepatch
def _apply_unified_diff(self, original: str, diff_text: str) -> str:
    try:
        patches = list(whatthepatch.parse_patch(diff_text))
        if not patches:
            return original
        result = list(whatthepatch.apply_diff(patches[0], original.splitlines(keepends=True)))
        return "".join(result)
    except Exception:
        return original
```

### Bug 2 — Aether-one: hardcoded dev secret in `zero_trust_exec.py`
- **File:** `aetherone/zero_trust_exec.py` line **1022**
- **Bug:** `raw = "aether-one-dev-zero-trust-secret"` — hardcoded fallback means any code without the env var uses a publicly known secret, making all tickets forgeable.
- **Fix:** Remove the hardcoded fallback. Raise `RuntimeError` if `AETHER_ONE_ZT_SECRET` is not set.
```python
def _get_secret() -> bytes:
    raw = os.environ.get(_ZT_SECRET_ENV)
    if not raw:
        raise RuntimeError(f"Zero-trust secret not configured. Set {_ZT_SECRET_ENV} env var.")
    return raw.encode("utf-8")
```

### Bug 3 — Aether-one `api.py`: `allow_origins=["*"]`
- **File:** `aetherone/api.py` line **64**
- **Bug:** `allow_origins=["*"]` — allows any origin. The comment says "tighten for real deployments" but this must be enforced now.
- **Fix:** Read from env: `allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")`.

### Bug 4 — aether2 `api/app.py`: `allow_origins=["*"]`
- **File:** `aether/api/app.py` line **84**
- **Bug:** Same CORS wildcard. Also has hardcoded `SECRET_KEY = config.get("api.secret_key", "vkatos-aether2-dev")` — dev key in default.
- **Fix:** Same CORS fix. Remove dev default for SECRET_KEY — raise error if not set.

### Bug 5 — DCSP `webhook.py`: `_CALL_GRAPH = None` never wired
- **File:** `src/api/webhook.py` line **30** (and lines **136**, **302**)
- **Bug:** `_CALL_GRAPH = None` — the `run_repair()` call passes `None` as the call graph. The pipeline handles `None` safely (creates empty `CallGraph()`), but this means zero call-graph-based scoring — all AST proximity scores default to 0.5 (degraded mode).
- **Fix:** In the API startup event, build the call graph: `_CALL_GRAPH = CallGraph.build_call_graph(repo_root)`. Update on each webhook receipt for the relevant repo.

### Bug 6 — DCSP `license_check.py`: hardcoded `SECRET_KEY`
- **File:** `license_check.py` line **10**
- **Bug:** `SECRET_KEY = "vkatos_enterprise_secret_2026"` — hardcoded in source.
- **Fix:** `SECRET_KEY = os.environ.get("DCSP_LICENSE_SECRET")` — raise if not set. Better: replace entire file with Aether-one's `licensing.py`.

### Bug 7 — DCSP `federation/registry_server.py`: in-memory only
- **File:** `src/federation/registry_server.py` lines **17-18**
- **Bug:** `_PATTERNS: dict[str, dict] = {}` — all federation patterns stored in a module-level dict. Lost on restart. Comment says "production would use PostgreSQL".
- **Fix:** Replace `_PATTERNS` dict with SQLite table in `core/memory/` continuous learning module.

### Bug 8 — aether2 `specialists.py`: `MemoryAgent` in-memory dict
- **File:** `aether/agents/specialists.py` (class `MemoryAgent`, `_store` class var)
- **Bug:** `_store: Dict[str, Memory] = {}` — class-level dict, lost on process exit.
- **Fix:** Replace with continuous learning module in `core/memory/`.

### Bug 9 — aether2: generated code never written to disk
- **File:** `aether/agents/orchestrator.py` `run_pipeline()` return value
- **Bug:** `generated_code` is stored in `ExecutionContext` and returned in the API response dict, but never written to any file on disk. A client that runs the pipeline gets code in the response but has no project directory.
- **Fix:** Add a `write_output_to_disk(output_dir, context)` step after docs generation in `run_pipeline()`.

### Bug 10 — Aether-one `fix_engine.py`: bad rule-based fixes produce wrong code
- **File:** `aetherone/fix_engine.py` `_auto_fix_syntax` (lines ~1162-1186) and `_auto_fix_runtime` (lines ~1190-1232)
- **Bug 10a (syntax):** The rule `if stripped.strip().endswith("=")` — appending ` None` is wrong for augmented assignment operators, type hints, etc. (e.g., `x: int =` would become `x: int = None`). Produces syntactically valid but semantically wrong code silently.
- **Bug 10b (runtime):** The NameError fix `{var_name} = None` — setting arbitrary undefined variables to None masks bugs rather than fixing them. A missing import becomes a `None` reference.
- **Fix:** Remove both rule-based strategies entirely. Keep only the LLM path (`propose_python_fix`). The rule-based fixes are more dangerous than the errors they claim to fix.

---

## 5. SOLID COMPONENTS — KEEP THESE

| Component | Source | Why it's good | Migration target |
|-----------|--------|---------------|-----------------|
| Aether-one policy engine | `aetherone/policy_engine.py` | Deterministic, org presets, risk levels, JSON persistence, well-tested | `core/policy/engine.py` |
| Aether-one licensing system | `aetherone/licensing.py` | HMAC-SHA256, feature gating, expiry, node-lock, no network required | `core/licensing/` |
| Aether-one approvals core | `aetherone/approvals_core.py` | SQLite-backed, full action history, clean API | `core/approval/store.py` |
| Aether-one AHM | `aetherone/agents/adaptive_hybrid_mesh.py` | Deterministic routing, health scoring, WAL audit, fallback | `orchestrator/routing/ahm.py` |
| Aether-one bootstrap | `aetherone/bootstrap/` | 7-phase startup, power levels, offline guard, safe mode | `core/bootstrap/` |
| Aether-one zero-trust tickets | `aetherone/zero_trust_exec.py` | HMAC signing, canonical payload, verified execution | `core/identity/zero_trust.py` |
| aether2 pipeline orchestrator | `aether/agents/orchestrator.py` | Clean retry loop with feedback injection, DCSP integration | `orchestrator/pipeline.py` |
| aether2 12 specialist agents | `aether/agents/specialists.py` | Complete coverage of all dev phases | Distributed across phases/ |
| aether2 stall monitor + predictor | `aether/monitor/` | Stage timing + prediction, integrates with orchestrator | `orchestrator/monitor.py` |
| DCSP log parser | `src/dfle/log_parser.py` | Multi-language, robust regex parsing of real CI logs | `phases/p08_cicd/dfle/` |
| DCSP AST localiser | `src/dfle/localizer.py` | Weighted confidence scoring (AST + stack depth + dep radius) | `phases/p08_cicd/dfle/` |
| DCSP AST index | `src/dfle/ast_index.py` | Clean incremental Python AST indexer | `phases/p08_cicd/dfle/` |
| DCSP call graph | `src/dfle/call_graph.py` | Python call relationship graph | `phases/p08_cicd/dfle/` |
| DCSP confidence scorer | `src/pipeline.py` `score_confidence()` | Weighted multi-factor scoring (5 inputs) | `phases/p08_cicd/pipeline.py` |
| DCSP patch applier | `src/repo/patch_applier.py` | `git apply` with dry-run + branch + commit | `phases/p08_cicd/repo/` |
| DCSP PR creator | `src/repo/pr_creator.py` | GitHub/GitLab API, clean abstraction | `phases/p08_cicd/repo/` |
| DCSP fingerprinter | `src/feedback/fingerprinter.py` | Stable normalised error signature | `core/memory/fingerprinter.py` |
| DCSP patch validator | `src/slm/patch_validator.py` | Unified diff extraction + validation | `phases/p08_cicd/slm/validator.py` |
| DCSP context builder | `src/slm/context_builder.py` | RAG context from CI failure | `phases/p08_cicd/slm/context_builder.py` |
| DCSP DSEE subsystem | `src/dsee/` | boundary + impact + test runner + verifier | `phases/p08_cicd/dsee/` |
| Aether-one framework generators | `aetherone/framework_generators.py` | Domain-specific scaffolds with client requirements | `phases/p03_scaffolding/generators.py` |
| Aether-one temporal risk | `aetherone/temporal_risk.py` | Fix-history based file risk scoring | `phases/p08_cicd/temporal_risk.py` |
| Aether-one telemetry spine | `aetherone/telemetry_spine.py` | Structured events, JSONL sink | `core/telemetry/spine.py` |
| Aether-one graph RAG | `aetherone/graph_rag.py` | Offline import graph + symbol index | `core/memory/graph_rag.py` |

---

## 6. STUB / PLACEHOLDER COMPONENTS

| File | Pretends to do | Current state |
|------|---------------|---------------|
| `aether2/aether/generation/__init__.py` | Code generation module | Empty `__init__.py` only |
| `aether2/aether/reasoning/__init__.py` | Reasoning module | Empty `__init__.py` only |
| `aether2/aether/ui/__init__.py` | UI module | Empty `__init__.py` only |
| `Aether-one/aetherone/quantum_optimizer.py` | "Quantum-inspired" optimisation | Name implies capability it doesn't have; basic heuristic at best |
| `Aether-one/aetherone/refactor_sample.py` | Refactor demo | Demo only, not a real module |
| `Aether-one/aetherone/neural_synthesis.py` | Neural code synthesis | Partially implemented |
| `DCSP/src/integrations/aether2_bridge.py` | Bridge to aether2 | Incomplete wiring, stub methods |
| `aether-one_snapshot_demo/` (entire subtree) | Older version of aetherone | Superseded by main aetherone/ — ignore |

---

## 7. CONFLICT RESOLUTION DECISIONS

| Component | Decision | Rationale |
|-----------|----------|-----------|
| LLM client | **Build new** `core/llm/client.py` (Anthropic primary + Ollama fallback) | All three existing clients are Ollama-only. New system requires Anthropic. Keep task routing from aether2, retry/validation from DCSP. |
| Policy engine | **Aether-one wins** (`policy_engine.py`) | More complete: strict mode, org presets, risk-based approval, JSON persistence. aether2's engine is a strict subset. |
| Snapshot manager | **Aether-one wins** (`time_travel_snapshots.py`) | Superset: single-file restore, delete, exists check. aether2's version is equivalent but less complete. |
| License checker | **Aether-one wins** (`licensing.py`) | Only real implementation. DCSP and aether2 have hardcoded keys, not real license enforcement. |
| Memory / repair memory | **Build new** `core/memory/` (SQLite + FTS5) | aether2's is in-memory dict, DCSP's is JSON file, Aether-one has none. All three are inadequate for production. |
| Audit logger | **Merge all three** into `core/audit/` | Each has unique value: aether2's JSONL append, DCSP's SQLite DB queries, Aether-one's approval log. |
| Sandbox | **Aether-one base + DCSP Docker as upgrade** | Aether-one has better policy integration. DCSP Docker sandbox is optional heavyweight add-on. |
| Webhook notifier | **DCSP wins** (`notifications/router.py`) | Multi-channel routing vs aether2's simple Slack-only. |
| Identity / RBAC | **Aether-one wins** (`identity.py`) | More complete: roles, bcrypt, SQLite, JWT. DCSP's auth is equivalent. |
| Agent base interface | **Aether-one wins** (`agents/base.py`) | Richer interface with health scoring hooks needed for AHM routing. |
| Orchestrator / pipeline | **Merge**: aether2 retry loop + Aether-one fix orchestrator + new state machine | aether2 has the better NL→code pipeline; Aether-one has the better fix/governance flow. |
| DB layer | **DCSP wins** for schema, **keep both** backends | DCSP has the most complete schema (tenants, jobs, incidents, API keys). Use SQLite for local dev, PostgreSQL optional. |

---

## 8. MIGRATION MAP

### KEEP AS-IS (copy to new location)
| Source | Destination |
|--------|-------------|
| `Aether-one/aetherone/policy_engine.py` | `aether_os/core/policy/engine.py` |
| `Aether-one/aetherone/licensing.py` | `aether_os/core/licensing/licensing.py` |
| `Aether-one/aetherone/approvals_core.py` | `aether_os/core/approval/store.py` |
| `Aether-one/aetherone/approval_workflow.py` | `aether_os/core/approval/workflow.py` |
| `Aether-one/aetherone/arbitration.py` | `aether_os/core/approval/arbitration.py` |
| `Aether-one/aetherone/zero_trust_exec.py` | `aether_os/core/identity/zero_trust.py` (**+fix Bug 2**) |
| `Aether-one/aetherone/identity.py` | `aether_os/core/identity/identity.py` |
| `Aether-one/aetherone/identity_engine.py` | `aether_os/core/identity/engine.py` |
| `Aether-one/aetherone/telemetry_spine.py` | `aether_os/core/telemetry/spine.py` |
| `Aether-one/aetherone/time_travel_snapshots.py` | `aether_os/core/snapshot/manager.py` |
| `Aether-one/aetherone/deterministic_scheduler.py` | `aether_os/core/scheduler/scheduler.py` |
| `Aether-one/aetherone/bootstrap/` (all 4 files) | `aether_os/core/bootstrap/` |
| `Aether-one/aetherone/agents/adaptive_hybrid_mesh.py` | `aether_os/orchestrator/routing/ahm.py` |
| `Aether-one/aetherone/agents/base.py` | `aether_os/agents/base.py` |
| `Aether-one/aetherone/framework_generators.py` | `aether_os/phases/p03_scaffolding/generators.py` |
| `Aether-one/aetherone/prompt_templates.py` | `aether_os/phases/p03_scaffolding/prompts.py` |
| `Aether-one/aetherone/graph_rag.py` | `aether_os/core/memory/graph_rag.py` |
| `Aether-one/aetherone/temporal_risk.py` | `aether_os/phases/p08_cicd/temporal_risk.py` |
| `Aether-one/aetherone/temporal_prediction.py` | `aether_os/phases/p08_cicd/temporal_prediction.py` |
| `Aether-one/aetherone/sandbox_manager.py` | `aether_os/core/sandbox/manager.py` |
| `Aether-one/aetherone/python_tools.py` | `aether_os/core/sandbox/python_tools.py` |
| `Aether-one/aetherone/test_generation.py` | `aether_os/phases/p07_testing/engine.py` |
| `Aether-one/aetherone/coverage_assistant.py` | `aether_os/phases/p07_testing/coverage.py` |
| `Aether-one/aetherone/security_agent.py` | `aether_os/phases/p06_security/engine.py` |
| `Aether-one/aetherone/refactor_engine.py` | `aether_os/phases/p05_review/refactor_engine.py` |
| `Aether-one/aetherone/packaging_macos.py` | `aether_os/phases/p10_packaging/macos.py` |
| `Aether-one/aetherone/packaging_windows.py` | `aether_os/phases/p10_packaging/windows.py` |
| `Aether-one/aetherone/compliance.py` | `aether_os/core/policy/compliance.py` |
| `Aether-one/aetherone/org_config.py` | `aether_os/core/config/org.py` |
| `Aether-one/aetherone/workspace_api.py` | `aether_os/gateway/workspace.py` |
| `Aether-one/aetherone/onboarding.py` | `aether_os/phases/p01_requirements/onboarding.py` |
| `Aether-one/aetherone/architecture_onboarding.py` | `aether_os/phases/p02_architecture/onboarding.py` |
| `Aether-one/aetherone/lang_framework_detector.py` | `aether_os/phases/p01_requirements/lang_detector.py` |
| `Aether-one/aetherone/monorepo_reasoning.py` | `aether_os/phases/p02_architecture/monorepo.py` |
| `aether2/aether/monitor/dcsp_bridge.py` | `aether_os/orchestrator/monitor.py` |
| `aether2/aether/monitor/predictor.py` | `aether_os/orchestrator/predictor.py` |
| `aether2/aether/core/errors.py` | `aether_os/core/errors.py` |
| `aether2/aether/sandbox/guard.py` | `aether_os/core/sandbox/guard.py` |
| `DCSP/src/dfle/log_parser.py` | `aether_os/phases/p08_cicd/dfle/log_parser.py` |
| `DCSP/src/dfle/localizer.py` | `aether_os/phases/p08_cicd/dfle/localizer.py` |
| `DCSP/src/dfle/ast_index.py` | `aether_os/phases/p08_cicd/dfle/ast_index.py` |
| `DCSP/src/dfle/call_graph.py` | `aether_os/phases/p08_cicd/dfle/call_graph.py` |
| `DCSP/src/dsee/boundary.py` | `aether_os/phases/p08_cicd/dsee/boundary.py` |
| `DCSP/src/dsee/impact.py` | `aether_os/phases/p08_cicd/dsee/impact.py` |
| `DCSP/src/dsee/test_runner.py` | `aether_os/phases/p08_cicd/dsee/test_runner.py` |
| `DCSP/src/dsee/verifier.py` | `aether_os/phases/p08_cicd/dsee/verifier.py` |
| `DCSP/src/slm/context_builder.py` | `aether_os/phases/p08_cicd/slm/context_builder.py` |
| `DCSP/src/slm/patch_validator.py` | `aether_os/phases/p08_cicd/slm/validator.py` |
| `DCSP/src/slm/prompt_templates.py` | `aether_os/phases/p08_cicd/slm/prompts.py` |
| `DCSP/src/feedback/fingerprinter.py` | `aether_os/core/memory/fingerprinter.py` |
| `DCSP/src/patch_reuse/matcher.py` | `aether_os/core/memory/matcher.py` |
| `DCSP/src/repo/patch_applier.py` | `aether_os/phases/p08_cicd/repo/patch_applier.py` |
| `DCSP/src/repo/pr_creator.py` | `aether_os/phases/p08_cicd/repo/pr_creator.py` |
| `DCSP/src/repo/git_manager.py` | `aether_os/phases/p08_cicd/repo/git_manager.py` |
| `DCSP/src/sandbox/docker_sandbox.py` | `aether_os/phases/p08_cicd/sandbox/docker.py` |
| `DCSP/src/intelligence/predictor.py` | `aether_os/phases/p08_cicd/intelligence/predictor.py` |
| `DCSP/src/knowledge/graph.py` | `aether_os/core/memory/knowledge_graph.py` |
| `DCSP/src/lang/` (all) | `aether_os/phases/p08_cicd/lang/` |
| `DCSP/src/adapters/` (all) | `aether_os/phases/p08_cicd/adapters/` |
| `DCSP/src/notifications/router.py` | `aether_os/core/telemetry/notifications.py` |
| `DCSP/src/security/hmac_verifier.py` | `aether_os/gateway/security.py` |
| `DCSP/src/security/rate_limiter.py` | `aether_os/gateway/security.py` |
| `DCSP/src/integrations/github_app.py` | `aether_os/gateway/github_app.py` |

### MIGRATE AND FIX
| Source | Destination | Fix required |
|--------|-------------|-------------|
| `Aether-one/aetherone/orchestrator.py` | `aether_os/orchestrator/fix_orchestrator.py` | Fix `_apply_unified_diff` (Bug 1) |
| `Aether-one/aetherone/fix_engine.py` | `aether_os/phases/p05_review/fix_engine.py` | Remove bad rule-based fixes (Bug 10) |
| `Aether-one/aetherone/api.py` | `aether_os/gateway/api.py` | Fix CORS wildcard (Bug 3) |
| `aether2/aether/api/app.py` | `aether_os/gateway/api.py` (merge) | Fix CORS + hardcoded SECRET_KEY (Bug 4) |
| `aether2/aether/agents/orchestrator.py` | `aether_os/orchestrator/pipeline.py` | Add disk write for generated code (Bug 9) |
| `aether2/aether/agents/specialists.py` | Distributed across phases/ | Replace MemoryAgent dict (Bug 8) |
| `aether2/aether/memory/ledger.py` | `aether_os/core/audit/ledger.py` | Update imports |
| `DCSP/src/api/webhook.py` | `aether_os/phases/p08_cicd/webhook.py` | Wire `_CALL_GRAPH` properly (Bug 5) |
| `DCSP/src/pipeline.py` | `aether_os/phases/p08_cicd/pipeline.py` | Update imports to unified LLM client |
| `DCSP/src/federation/registry_server.py` | `aether_os/core/memory/federation.py` | Replace in-memory dict with SQLite (Bug 7) |

### DISCARD
| Source | Reason |
|--------|--------|
| `aether2/aether/policy/engine.py` | Inferior to Aether-one's engine |
| `aether2/aether/snapshots/manager.py` | Inferior to Aether-one's snapshots |
| `aether2/aether/llm/engine.py` | Replaced by new unified LLM client |
| `Aether-one/aetherone/llm_router.py` | Replaced by new unified LLM client |
| `DCSP/src/slm/ollama_client.py` | Replaced by new unified LLM client |
| `DCSP/license_check.py` | Replaced by Aether-one's licensing |
| `aether2/license_check.py` | Replaced by Aether-one's licensing |
| `Aether-one/aetherone/quantum_optimizer.py` | Not real, misleading name |
| `Aether-one/aetherone/refactor_sample.py` | Demo only |
| `aether2/aether/generation/__init__.py` | Empty stub |
| `aether2/aether/reasoning/__init__.py` | Empty stub |
| `aether-one_snapshot_demo/` (entire subtree) | Superseded by main aetherone/ |
| `DCSP/src/integrations/aether2_bridge.py` | Replace with proper orchestrator wiring |
| `DCSP/src/redis_cache.py` | Optional only — SQLite fallback for local dev |

---

## 9. NEW COMPONENTS NEEDED

| Component | Location | What it must do | Inputs / Outputs | Depends on |
|-----------|----------|-----------------|------------------|------------|
| **Unified LLM client** | `core/llm/client.py` | Anthropic primary (claude-sonnet-4-6 + claude-haiku-4-5), Ollama fallback. Task routing, cost tracking, retry with backoff. Single `async call(prompt, task_type, context)` interface. | prompt: str, task_type: str → response: str | `core/telemetry/spine.py`, `core/config/` |
| **Continuous learning module** | `core/memory/` | SQLite + FTS5 store for successful outcomes (patches, code, fixes). Retrieve top-5 similar by input hash. Inject into agent prompts. Replace DCSP repair_memory + aether2 MemoryAgent. | store(record): None, retrieve(input_hash, k=5): List[Record] | `core/memory/fingerprinter.py` |
| **Phase gate system** | `phases/pXX/gate.py` (10 gates) | Each phase has a typed exit gate. PhaseOutput in → GateResult(passed, issues, confidence) out. 3 retries then human escalation. | PhaseOutput (per-phase Pydantic model) → GateResult | `core/approval/workflow.py`, `core/policy/engine.py` |
| **CrewAI crew definitions** | `agents/crews/` | One crew per phase (2-4 agents per crew). Agents share context via CrewAI memory. Tools: unified LLM, memory retrieval, snapshot, policy check. | NL task description + phase context → CrewOutput | `core/llm/client.py`, `core/memory/`, `agents/tools/` |
| **Pipeline state machine** | `orchestrator/state_machine.py` | States: IDLE→REQUIREMENTS→...→COMPLETE/FAILED/GATED_HUMAN. Transition logging to AuditTrail. Resume from last successful phase. GATED_HUMAN pauses and creates approval ticket. | PhaseID, PhaseResult → next PhaseID | `core/audit/`, `core/approval/store.py` |
| **Shared execution context** | `orchestrator/context.py` | Typed Pydantic model passed between all phases. Contains: requirement, architecture, generated code, review findings, security report, test results, CI result, docs, packaging artifact. | Constructed at pipeline start, mutated by each phase | All phases |
| **Unified API** | `gateway/api.py` | Single FastAPI app. Routes: /pipeline/start, /pipeline/status, /pipeline/approve, /ci/webhook, /auth, /health. JWT auth. Fixed CORS. | HTTP requests → JSON responses | `core/identity/`, `orchestrator/` |
| **Phase router** | `orchestrator/router.py` | Routes failures back to correct phase. Maps failure types to phase IDs. | FailureType, PhaseID → target PhaseID | `orchestrator/state_machine.py` |
| **Main entrypoint** | `aether_os/main.py` | `python aether_os/main.py` starts everything: bootstrap → API server → dashboard. Typer CLI with start/demo/status commands. | CLI args → running system | All core modules |
| **Completion report generator** | `aether_os/scripts/report.py` | Generates COMPLETION_REPORT.md after demo run | Pipeline run context → markdown report | `orchestrator/context.py` |

---

## 10. DEPENDENCY ANALYSIS

### aether2 dependencies
```
fastapi, uvicorn, sqlmodel, typer, rich, pyyaml, httpx, pytest, pytest-asyncio, aiofiles
```
All standard. No heavy deps.

### Aether-one dependencies (from pyproject.toml + tests)
```
fastapi, uvicorn, sqlalchemy[asyncio], aiosqlite, typer, rich, pyyaml, httpx,
passlib[bcrypt], python-jose[cryptography], pytest, pytest-asyncio,
websockets, watchdog
```
Heavy: `python-jose`, `passlib`, `sqlalchemy[asyncio]`, `aiosqlite`. All justified.

### DCSP dependencies (requirements.txt — heavy)
```
fastapi, uvicorn, sqlalchemy, pydantic, celery, redis, psycopg2-binary,
alembic, requests, networkx, ruff, pytest, httpx, python-dotenv,
python-multipart, websockets
```
**Problem deps for local dev:**
- `celery` + `redis` — heavy async queue. Replace with `asyncio.Queue` for local dev mode.
- `psycopg2-binary` — PostgreSQL. Make optional; SQLite default.
- `alembic` — worth keeping for migrations.
- `networkx` — used for call graph. Lightweight enough, keep.

### Unified requirements for aether_os
```
# Core
fastapi>=0.110.0
uvicorn>=0.27.0
pydantic>=2.5.0
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
alembic>=1.13.0

# Auth
passlib[bcrypt]>=1.7.4
python-jose[cryptography]>=3.3.0

# LLM
anthropic>=0.30.0           # PRIMARY — new
httpx>=0.25.0               # for Ollama fallback

# CLI / UX
typer>=0.9.0
rich>=13.0.0

# Config
pyyaml>=6.0
python-dotenv>=1.0.0

# Agents
crewai>=0.30.0              # NEW — for crew definitions

# Analysis
networkx>=3.2.0             # call graph
whatthepatch>=1.0.0         # FIXED — replaces broken difflib.patch_from_unified_diff

# Dev / test
pytest>=7.4.0
pytest-asyncio>=0.21.0
aiofiles>=23.0.0
ruff>=0.1.0

# Optional (CI phase)
requests>=2.31.0            # GitHub/GitLab PR API
python-multipart>=0.0.6     # file uploads
websockets>=12.0

# Optional (heavy — only if Docker sandbox enabled)
# docker>=7.0.0

# Optional (production queue — not needed for local dev)
# celery>=5.3.0
# redis>=5.0.0
# psycopg2-binary>=2.9.0
```

---

## 11. RISK FLAGS

| Risk | Description | Severity | Mitigation |
|------|-------------|----------|-----------|
| **Async/sync mismatch** | Aether-one uses SQLAlchemy `async`, aether2 uses sync sqlite3, DCSP mixes both. Combining them risks blocking the async event loop. | HIGH | Standardise on async SQLAlchemy (`aiosqlite` backend) for all new code. Wrap any remaining sync DB calls in `asyncio.run_in_executor`. |
| **Global singleton state** | aether2's `_engine`, `_ledger`, `_policy_engine` are module-level singletons. DCSP has `GLOBAL_REPAIR_MEMORY`, `GLOBAL_NOTIFICATION_ROUTER`. These break when running multiple pipeline instances in parallel. | HIGH | Replace all global singletons with dependency injection via FastAPI's `Depends()`. |
| **Circular import risk** | All three repos import from each other's submodules without a clean dependency hierarchy. Migration risk: `core/` depending on `phases/`, or `phases/` depending on `orchestrator/`. | MEDIUM | Enforce strict layer hierarchy: `core/` ← `phases/` ← `orchestrator/` ← `gateway/`. No reverse imports. |
| **Thread safety** | aether2's `DecisionLedger` uses `threading.Lock()`. Aether-one's DCSP uses `threading.Semaphore`. FastAPI is async. Mixing `threading.Lock` with `asyncio` is unsafe without care. | MEDIUM | Replace `threading.Lock` with `asyncio.Lock` in all async-path code. |
| **Missing error propagation** | Both aether2 and Aether-one catch broad `Exception` and return silent failures (empty string, `None`, `original`). These mask bugs and make debugging the pipeline very hard. | MEDIUM | Replace all bare `except Exception: return ""` with structured `GateResult(passed=False, issues=[str(e)])`. |
| **Ollama dependency for fallback** | New system uses Anthropic as primary, but Ollama is fallback. If neither is available, the entire pipeline fails silently in several places. | LOW | Add explicit health check at startup. If no LLM is available, refuse to start (clear error). |
| **Node_modules in Aether-one** | `Aether-one` has `node_modules/` committed (confirmed by gitignore analysis). These are large binary files that will bloat the new repo if not excluded. | LOW | Add `node_modules/` to `aether_os/.gitignore` before first commit. |
| **DCSP Redis/Celery coupling** | DCSP's queue system is tightly coupled to Celery + Redis. Removing them for local dev mode requires rewriting `queue/worker.py`. | MEDIUM | For Phase 1: replace with `asyncio.Queue`. Phase 2+: make Celery optional via config flag. |

---

## 12. RECOMMENDED BUILD ORDER

**Phase 0 (this audit):** COMPLETE

**Phase 1 — Foundation (build these first, everything depends on them):**
1. `aether_os/core/errors.py` — error types
2. `aether_os/core/config/loader.py` — config loading (YAML + env)
3. `aether_os/core/db.py` — SQLAlchemy async engine + session factory
4. `aether_os/core/audit/logger.py` + `ledger.py` — audit trail
5. `aether_os/core/policy/engine.py` — migrate from Aether-one
6. `aether_os/core/licensing/licensing.py` — migrate from Aether-one
7. `aether_os/core/identity/` — migrate from Aether-one
8. `aether_os/core/approval/` — migrate from Aether-one
9. `aether_os/core/snapshot/manager.py` — migrate from Aether-one
10. `aether_os/core/telemetry/spine.py` — migrate from Aether-one

**Phase 2 — LLM and Memory (new components):**
11. `aether_os/core/llm/client.py` — build unified Anthropic+Ollama client
12. `aether_os/core/memory/fingerprinter.py` — migrate from DCSP
13. `aether_os/core/memory/` continuous learning module — build new (SQLite FTS5)

**Phase 3 — Orchestrator:**
14. `aether_os/orchestrator/context.py` — shared execution context
15. `aether_os/orchestrator/state_machine.py` — pipeline state machine
16. `aether_os/orchestrator/pipeline.py` — merge aether2 orchestrator
17. `aether_os/orchestrator/monitor.py` — migrate aether2 DCSP bridge
18. `aether_os/orchestrator/routing/ahm.py` — migrate Aether-one AHM

**Phase 4 — Phases (each phase + its gate):**
19–28. `aether_os/phases/p01_requirements/` through `p10_packaging/` — one at a time in order

**Phase 5 — Gateway and Tests:**
29. `aether_os/gateway/api.py` — unified FastAPI
30. `aether_os/gateway/auth.py`
31. `aether_os/agents/crews/` — CrewAI crew definitions
32. `aether_os/main.py` — single startup entrypoint
33. `aether_os/tests/` — full test suite

---

*End of Phase 0 Audit. Proceed to Phase 1 only after this document is reviewed and accepted.*
