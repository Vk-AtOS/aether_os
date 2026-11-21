# 10_core_platform_governance: core platform services, governance, security, compliance, SRE
Scope: core/{approval,audit,compliance,policy,security,identity,guardian,snapshot,chaos_engineering,capacity_planner,cell_architecture,cloud_primitives,sandbox,run_app,telemetry,scheduler,queue,billing,webhooks,notifications,connectors,plugins,services,bootstrap,config,validators}/ plus core/{encryption,webhooks_model,api_key_store,app_state,artifact_store,context_helpers,db_utils,db,errors,error_registry(.py/.json),feature_flags,logging_config,models,pipeline_state,projects,prometheus_patch,rate_limiter,seed,workloop_monitor,workspace_model}.py
About 135 .py files, about 24.1K LOC. Commit 052a101. Mapped 2026-11-08. Read-only.

Status tags:
- **REAL**: working logic on a live path.
- **LLM**: LLM-driven.
- **TEMPLATE**: emits code or config for *generated apps*.
- **STUB**: hollow or placeholder.
- **DEAD**: no prod importers; verified by grep that excludes `__pycache__` and the file itself.

---

## 1. Summary

The platform's runtime backbone is real and reasonably built:
- async SQLAlchemy 2.x with a 33-table ORM
- a Redis-backed pipeline event bus, rate limiter and app state
- the Guardian DB backup and watchdog
- Fernet column encryption
- the audit ledger
- a regex compliance scanner with PDF reports
- an SQS producer and consumer
- token-cost metering
- HMAC webhook delivery
- SMTP mail
- an org-scoped plugin install registry

The governance layer claims more than it enforces:
- **Approval gates:** `core/approval/*` is DEAD or broken. The real gates live in `orchestrator/factory_pipeline.py:955-986` and `orchestrator/spec_review_gate.py`, and both **fail open** on timeout or error.
- **Policy engine:** always returns allow (`core/policy/engine.py:380-396`).
- **Audit hash chain:** written but never verified, and it does not link entries transitively (`core/audit/ledger.py:114-159`).
- **Zero-trust tickets:** only log a warning on failure (`phases/base.py:188-202`).

These modules only emit templates for generated apps and never touch the platform: chaos, capacity, cell architecture and cloud primitives. Fully DEAD:
- the sandbox package (generated apps run as bare host uvicorn processes)
- the scheduler
- telemetry spine and notifications
- bootstrap (runtime manager, safe mode, offline guard)
- the snapshot manager
- the duplicate model files

About 5K of the roughly 24K LOC in scope is dead.

Top live risks:
1. Platform webhooks are HMAC-signed with an **empty key**, because only a bcrypt hash of the secret is stored.
2. `/app-preview` is an unauthenticated proxy that forwards platform `Authorization` and `Cookie` headers to LLM-generated code running with the full platform environment.
3. Runtime validators are generated into the source tree and `exec`'d in-process across tenants. The template has a docstring-injection hole.
4. `save_api_key` writes one org's LLM key into `os.environ`, where it becomes every org's fallback.
5. Guardian auto-recovery restores the snapshot it just took, and a full disk triggers a destructive `pg_restore --clean`.
6. The connectors plugin package fails to import in Docker (circular, unprefixed `core.` imports).

---

## 2. Coverage table

### Governance: approval, audit, policy, compliance, security, identity, encryption

| File | LOC | Purpose | Tag |
|---|---|---|---|
| approval/arbitration.py | 502 | Agent-conflict resolution with escalation to a human, JSONL trail | DEAD |
| approval/guarded.py | 456 | Allow, needs-approval or block decision against a risk threshold | DEAD |
| approval/store.py | 486 | SQLite approval tickets and actions | DEAD in effect: its only importers want `get_approvals_store`, which does not exist |
| approval/workflow.py | 158 | Risk to decision mapping plus JSONL audit | DEAD in effect: legacy `orchestrator/pipeline.py` only |
| approval/__init__.py | 1 | — | — |
| audit/ledger.py | 291 | Runs, events and `audit_log` with a prev_hash, via async ORM | REAL |
| audit/logger.py | 127 | JSONL audit file plus an unbounded in-memory list | REAL (bus, state_machine) |
| audit/__init__.py | 5 | Re-exports | — |
| policy/engine.py | 423 | Presets (default, fintech, healthcare), blocked operations, risk threshold | REAL code; never denies in practice |
| policy/compliance.py | 483 | Rules for export control, EU residency, AI use, crypto, sensitive data | REAL (deterministic) |
| policy/compliance_india.py | 225 | DPDP, IT Act 43A, RBI, SEBI, CERT-In | REAL |
| policy/__init__.py | 11 | Re-exports | — |
| compliance/code_scanner.py | 547 | Regex FastAPI route scan mapped to HIPAA, GDPR, SOC2 and PCI, with a 0-100 score | REAL |
| compliance/pdf_report.py | 248 | fpdf2 PDF report, .txt fallback | REAL |
| compliance/manifest_writer.py | 162 | compliance_manifest.json plus drift fingerprint | DEAD in prod (duplicate of phases/p06_review_security/manifest.py) |
| compliance/artifact_generator.py | 71 | Wraps scan plus PDF | REAL |
| security/code_scanner.py | 178 | bandit, regex secrets, domain regexes, pip-audit | REAL (p06) |
| security/prompt_guard.py | 43 | Jailbreak and injection regex filter on intake | REAL |
| security/scanner_models.py | 11 | Duplicate `ScanResult` | DEAD |
| identity/zero_trust.py | 90 | HMAC-SHA256 per-phase tickets | REAL, not enforced |
| encryption.py | 77 | Fernet `EncryptedText` column type | REAL |

### SRE: guardian, snapshot, chaos, capacity, cells, cloud primitives

| File | LOC | Purpose | Tag |
|---|---|---|---|
| guardian/watchdog.py | 215 | 30s loop: detect, persist, snapshot, recover | REAL |
| guardian/threat_detector.py | 288 | Brute force (Redis), file integrity, disk, Redis and DB health | REAL |
| guardian/snapshot_manager.py | 372 | pg_dump/pg_restore or sqlite backup, SHA-256, keeps 10 | REAL |
| guardian/auto_recovery.py | 216 | Restore latest, alembic upgrade, probe | REAL, buggy |
| guardian/password_shield.py | 139 | Password rules plus HIBP k-anonymity | REAL |
| guardian/models.py | 43 | `guardian_events`, `guardian_snapshots` | REAL |
| guardian/__init__.py | 12 | Re-exports | — |
| snapshot/manager.py | 505 | Workspace file-tree snapshot, diff and restore | DEAD |
| snapshot/__init__.py | 1 | — | — |
| chaos_engineering/chaos_generator.py | 435 | LitmusChaos YAML for generated apps | TEMPLATE (P20) |
| capacity_planner/planner.py | 326 | HPA, KEDA, PDB and quota YAML | TEMPLATE (P20) |
| cell_architecture/cell_planner.py | 530 | Multi-region Terraform, nginx, runbook | TEMPLATE, DEAD (tests only) |
| cloud_primitives/gateway.py | 195 | Kong config | TEMPLATE, DEAD (tests only) |
| cloud_primitives/queue.py | 304 | NATS Helm, streams and client | TEMPLATE, DEAD (tests only) |
| cloud_primitives/storage.py | 271 | MinIO Helm and boto3 client | TEMPLATE, DEAD (tests only) |

### Runtime services: sandbox, run_app, telemetry, scheduler, queue, billing, webhooks, notifications, connectors

| File | LOC | Purpose | Tag |
|---|---|---|---|
| sandbox/manager.py | 599 | Host subprocess with rlimits, plus an SSH (paramiko) runner | DEAD |
| sandbox/guard.py | 108 | Regex code blocklist, path jail, pytest | DEAD |
| sandbox/python_tools.py | 101 | py_compile and run a file | DEAD |
| run_app/process_manager.py | 520 | pip/npm/vite build, patch the app, launch uvicorn | REAL |
| run_app/process_manager_helpers.py | 475 | Fallback HTML, stub app, regex patches | REAL/TEMPLATE |
| telemetry/langsmith_tracer.py | 166 | Opt-in LangSmith tracing of LLM calls | REAL (opt-in) |
| telemetry/spine.py | 415 | JSONL event log | DEAD |
| telemetry/notifications.py | 49 | Imports `src.notifications.*`, which does not exist | DEAD, broken |
| scheduler/scheduler.py | 444 | In-memory priority queue | DEAD |
| queue/sqs_client.py | 112 | boto3 SQS | REAL (if `SQS_QUEUE_URL` is set) |
| queue/pipeline_consumer.py | 156 | SQS poll loop that calls factory.run | REAL |
| billing/impl.py (+`__init__` 7) | 196 | LLM token cost metering into `llm_call_records` | REAL |
| billing/router.py | 14 | Picks razorpay vs stripe by country | DEAD |
| webhooks/delivery.py (+`__init__` 1) | 180 | HMAC outbound webhooks with retry and an SSRF check | REAL (signing broken) |
| webhooks_model.py | 20 | Duplicate `webhooks` table | DEAD; would fail if imported |
| notifications/email.py (+`__init__` 4) | 100 | smtplib STARTTLS | REAL |
| connectors/ldap_connector.py | 298 | ldap3 bind, search, auth | REAL (but its import is broken, see §7) |
| connectors/salesforce_connector.py | 217 | httpx to Salesforce REST v58 | REAL (same) |

### Platform layer: plugins, services, bootstrap, config, validators

| File | LOC | Purpose | Tag |
|---|---|---|---|
| plugins/registry.py | 542 | Hardcoded catalog (13 connectors, 10 skills) plus per-org install in Postgres | REAL |
| plugins/connectors.py | 358 | Base class plus GitHub, GitLab, Jira, Linear, Slack | REAL; import broken |
| plugins/connectors_registry.py | 299 | Figma, Vercel, Sentry, Supabase, AWS, GCP (stub), Stripe, PlanetScale | REAL/partial STUB |
| plugins/skills.py | 524 | 10 prompt-template codegen skills | LLM |
| services/pipeline_service.py | 162 | start, pause, resume, cancel | REAL; marketplace path only |
| services/run_service.py | 255 | Run queries | REAL; 8 of its functions dead |
| services/run_app_service.py | 54 | Port pick plus RunAppManager wrapper | REAL |
| services/account_service.py | 270 | Usage, GDPR export and erase, org settings | REAL; 6 of its functions dead |
| services/settings_service.py | 235 | LLM config, org keys, phase config, SAML CRUD | REAL |
| services/guardian_service.py | 196 | Guardian event and snapshot stats | REAL |
| services/memory_service.py | 234 | Similar-run lookup (Chroma, then fingerprint), prefs | REAL wrapper |
| services/learning_service.py | 255 | Per-user learned patterns | REAL |
| services/global_pattern_service.py | 137 | Cross-org quality averages | REAL |
| bootstrap/{runtime_manager 383, safe_mode 232, environment_detector 171, offline_guard 210, __init__ 41} | 1037 | 7-step bootstrap, safe mode, psutil probe, network monkey-patch | DEAD + STUB |
| config/loader.py (+`__init__` 4) | 160 | Defaults plus YAML singleton | REAL; the documented env overlay is missing |
| validators/registry.py | 90 | `exec_module` on every `auto_generated/*.py` | REAL; security risk |
| validators/__init__.py, auto_generated/__init__.py | 27+3 | `run_all_validators()` | REAL |

### Core top-level: DB layer and infrastructure helpers

| File | LOC | Purpose | Tag |
|---|---|---|---|
| db.py | 222 | Async engine, session factory, `get_db`, `init_db` (create_all) | REAL (~97 importers) |
| models.py | 534 | 33 ORM tables | REAL |
| db_utils.py | 370 | Run, phase and live_url queries, completion email | REAL; some functions dead |
| api_key_store.py | 141 | Per-org LLM key lookup: cache, then DB, then env | REAL; cross-tenant leak |
| app_state.py | 231 | Run-app port and pid in Redis (2h TTL) plus memory | REAL |
| artifact_store.py | 318 | JSON embeddings, numpy cosine, S3 | REAL |
| context_helpers.py | 259 | Helpers for the pipeline accumulated_context | REAL |
| errors.py | 96 | AetherError hierarchy | REAL |
| error_registry.py / .json | 214 / 1 | JSON file of codegen failure categories (currently `[]`) | REAL, file-backed |
| feature_flags.py | 124 | GrowthBook, then env, then defaults | STUB: `is_on` is never called |
| logging_config.py | 70 | structlog JSON | REAL |
| pipeline_state.py | 140 | Redis pub/sub event bus plus control keys, also inserts into Postgres | REAL (25 importers) |
| projects.py | 98 | `~/.aether_os/projects/_index.json` manager | REAL (filesystem) |
| prometheus_patch.py | 45 | Monkey-patch for the instrumentator route name | REAL |
| rate_limiter.py | 475 | Redis ZSET sliding window, SSE tokens, port registry, client IP | REAL |
| seed.py | 128 | Admin user and org from env vars, 10 marketplace skills | REAL |
| workloop_monitor.py | 312 | 5-minute LLM diagnosis of runs that auto-sets `os.environ` | LLM |
| workspace_model.py | 18 | Duplicate `workspaces` table | DEAD; would fail if imported |

No file in scope is over 600 lines. The largest is `sandbox/manager.py` at 599 (dead), then `compliance/code_scanner.py` (547), `registry.py` (542), `models.py` (534) and `cell_planner.py` (530). There are no bare `except:`, but there are many debug-level `except Exception` swallows.

---

## 3. Components and how they work

### 3.1 DB layer (db.py, models.py, db_utils.py)

**Engine and sessions**
- SQLAlchemy 2.x async only (db.py:19-24). `DATABASE_URL` with a `postgres(ql)://` scheme is rewritten to `postgresql+asyncpg://` (db.py:43-50).
- If `DATABASE_URL` is unset, it falls back to `sqlite+aiosqlite:///~/.aether_os/aether_os.db` (db.py:53-55), with NullPool, WAL and foreign_keys=ON (db.py:71-111).
- Postgres pool: size `DB_POOL_SIZE` 3, overflow 7, recycle 300, pre_ping, and a 30s statement_timeout (db.py:84-95). The docstring's "20/40" (db.py:7) is stale.
- Sessions use `expire_on_commit=False`. `get_db` commits on success and rolls back on error (db.py:124-147). Most code opens `get_session_factory()()` directly instead.

**Schema management**
- `init_db()` runs `Base.metadata.create_all` plus 19 `CREATE INDEX IF NOT EXISTS` on every startup (db.py:150-199; called from gateway/lifespan.py:131).
- Alembic has 55 versions with multiple heads, so deploy.sh upgrades named revisions (deploy/deploy.sh:47-57).
- **12 tables exist only through create_all**, with no migration: audit_log, llm_cache_entries, token_budget_records, llm_call_records, installed_plugins, llm_config, user_learning_patterns, learning_clarifications_pending, run_specs, notifications, pipeline_events, questionnaire_sessions. A migration creates `org_code_profiles`, which no model uses; the model uses `codebase_profiles` (models.py:440).

**Tables (models.py)**
- **Tenancy and auth:** organisations (:15; slug, plan, trial counters, scim_token plaintext plus scim_token_hash, stripe_customer_id, soft delete); users (:39; FK org; **email globally unique** :44; role; mfa_secret EncryptedText :52); api_keys (:60; SHA-256 key_hash); org_api_keys (:203; EncryptedText api_key, unique org+provider); saml_configs (:231).
- **Runs:** runs (:73; org_id FK nullable, user_id no FK, JSON phases blob, checkpoint_data, parent_run_id); events (:109); snapshots (:121; full file content); phase_completions (:132; PK run+phase); run_metadata (:152); pipeline_events (:486; FK runs CASCADE); run_specs (:412); llm_traces (:497; full prompt and response).
- **Configuration:** phase_configs (:143; PK org+phase); decisions (:159); webhooks (:178; secret plaintext deprecated, secret_hash); workspaces (:191; no membership table); llm_config (:354; nullable org means global).
- **LLM and cost:** llm_cache_entries (:293); token_budget_records (:308); llm_call_records (:326).
- **Learning:** artifact_embeddings (:250; JSON plus an optional pgvector `Vector(1536)` that nothing writes); global_patterns (:277); user_learning_patterns (:378); learning_clarifications_pending (:395); codebase_profiles (:438); build_feedback (:452); golden_builds (:466).
- **Other:** audit_log (:217; prev_hash :229); marketplace_profiles (:263); installed_plugins (:341; config_json Text "encrypted", which it is not); notifications (:423); questionnaire_sessions (:517; plaintext access_token).
- **Guardian (guardian/models.py):** guardian_events, guardian_snapshots, created in alembic revision_guardian_module.py.

**Dual import paths:** 5 sites use `from core.db import` instead of `aether_os.core.db` (api_key_store.py:55,85; core/vector_store.py:27; 2 scripts). That risks two engines and two metadata objects.

### 3.2 Multi-tenancy

**Scoping model**
- Isolation is by `org_id` only, applied by hand in each query. There is no Postgres row-level security.
- Workspaces are a flat table (`created_by`, `is_shared`) with no membership table.
- `get_current_user` returns the **JWT payload**, so org and role come from token claims and are not refreshed from the DB (gateway/dependencies.py:28-96).
- API keys map to `role:"api"` (dependencies.py:118-130). Role checks are ad hoc per router; there is no central `require_role`.

**Where the org filter is weak or missing**
- **Optional:** `get_run_detail`, `update_run_status` (db_utils.py:138,237).
- **Missing:** `record_phase_completion` (:202), `async_update_run_live_url` (:364), `artifact_store.get_artifact` (:201), `learning_service` `session.get(Run)` (:139), `run_service` RunMetadata (:107), `stop_run_app` (gateway run_app_router.py:99-121).
- **Global by design:** `projects.py` tenancy is a `client_id` in a JSON file, unrelated to the DB orgs. The run-app "current run" is a single key for the whole platform (app_state.py:32).

### 3.3 Approval and human gates

**`core/approval` (mostly dead)**
- `store.py`: SQLite at `<project>/.aetherone_approvals.db`, tables approvals_ticket and approvals_action (:178-218), statuses PENDING/APPROVED/DENIED.
  - `gateway/client_portal/routes.py:243` and `phases/gateway/client_portal/routes.py:73` import `get_approvals_store`, which does not exist, so **POST /{project_id}/approve always returns 500**. Even if fixed, the handler records nothing (:245-251).
- `guarded.py:254-455`: severity order NONE<LOW<MEDIUM<HIGH<CRITICAL against a threshold. Its `_store_create_ticket` passes `project_root=`, which `create_ticket` (store.py:260) does not accept; the TypeError is swallowed at debug level (:190-200).
- `arbitration.py`: kept in memory, with a JSONL file in `~/.aetherone/arbitration/`.
  - "consensus" and "safety_first" both just pick the highest confidence (comments :372-397).
  - Escalates to a human on security or policy conflicts, or confidence below 0.5 (:161-177).
  - Nothing calls `submit_human_decision`.
- `workflow.decide_for_risk` (:63-100): NONE/LOW apply automatically, MEDIUM needs approval, HIGH and unknown are blocked. It is called only from legacy `orchestrator/pipeline_helpers.py:294`.

**Real gates (outside scope; for the lead)**
- `factory_pipeline._await_human_approval` (:955-986): builds a `core.decisions` Decision with timeout `HUMAN_APPROVAL_TIMEOUT`=300, emits `approval_required`, then awaits. Deny cancels the run. **Timeout continues (:983); an exception continues (:985).**
- `spec_review_gate.py:133-157`: polls Redis and **approves automatically** after `SPEC_REVIEW_TIMEOUT`=600.
- Routes that grant approval: `POST /pipeline/approve/{ticket_id}` (factory_ops_router.py:57-90) and `/factory/runs/{id}/decisions/{did}/approve|approve-spec` (run_spec_router.py:45,130).
- There are three risk-mapping functions that disagree on HIGH: workflow blocks it, while policy and guarded both send it to approval.

### 3.4 Audit

**ledger.py**
- Writes `runs`, `events` and `audit_log` through the async ORM.
- `async_log_audit_event` (:119-163) sets the new row's `prev_hash` to sha256 of the previous row's id, org, user, action, resource and created_at.

**Why the chain is not tamper-evident**
- The previous row's own prev_hash is excluded, so editing a row breaks only the next link and the chain is not transitive. Metadata and IP address are not hashed.
- It finds the last row by a float `created_at` with no lock, so concurrent writes fork the chain.
- **No verifier exists anywhere in the repo.**
- `DELETE /audit/logs/purge` (compliance_router.py:102-122) removes the anchor rows.
- Writes fail open (WARNING, then the event is dropped).
- `drain_audit_futures` (:275) is never called, so in-flight events are lost at shutdown.
- The sync wrappers are fire-and-forget inside a running event loop, so the sync getters return None (:247-272).

**Other audit sinks**
- `audit/logger.py` writes JSONL to `~/.aether_os/audit.jsonl` and keeps an unbounded `_entries` list (:28).
- In all there are four audit sinks: arbitration JSONL, workflow `.aetherone_audit.log`, logger JSONL and the DB `audit_log`.

### 3.5 Policy engine

- Policies are Python dataclass presets (default, fintech, healthcare; engine.py:121-155). A project can override them with `.aetherone_policy.json` (:188-228). There is no YAML and no OPA.
- `evaluate_operation` (:256-351) checks, in order: blocked operation, then strict mode with an unguarded operation, then risk above the threshold (allowed with `requires_approval`), then allow. An unknown risk counts as HIGH.
- `check_pipeline_start` (:380-396) is called from `services/pipeline_service.py:53-59` and `agents/implementations.py:47-53`.
- It **always allows**: `requires_approval` is ignored by both callers, `org_id` is unused, and the project JSON is never loaded on this path.
- Both callers fail open (`except ImportError: pass`; "allowing by default").
- Bug: `logger` is defined inside the docstring (:3), so a malformed policy file raises NameError (:209).

### 3.6 Compliance frameworks

**`policy/compliance.ComplianceEngine.evaluate` (:153-227)** works on declared metadata, not on code.
- **Rules:**
  - Embargo list IR/KP/SY/CU/RU: critical, or high when on-prem with sensitive data (:130,231-282).
  - EU residency with a non-EU cloud: high.
  - High-risk AI uses and defense: high.
  - Weak crypto with sensitive data: medium.
  - Children's data on SaaS, or biometrics in the EU/UK: high.
- **India rules** (compliance_india.py): DPDP §9 children, §16 cross-border, significant data fiduciary, IT Act 43A, **RBI localisation is critical for any fintech SaaS** (:127-145), SEBI CSCRF, CERT-In. They trigger for country IN **or any APAC region** (compliance.py:182).
- **Outcome:** any critical finding denies; any high or medium needs approval.
- **Consumers:** RiskAgent blocks only on deny and fails open (implementations.py:87-92); `factory_run_background.run_compliance_precheck` (:209-236); the org report in compliance_router.py:231.

**`compliance/code_scanner.py`** scans code with regex, not an AST.
- Route detection matches `@(app|router).<verb>(` (:135). Auth, rate-limit, validation and audit flags come from a 50-line window after each decorator (:188), which spills into neighbouring routes.
- **Checks:**
  - HIPAA 164.312(d), (b), (c)(1).
  - GDPR Art.17 (needs any DELETE route) and Art.32 (CORS present, not a wildcard).
  - SOC2 CC6.6 (rate limit on more than 50% of routes), CC6.7 (HTTPS keyword), CC6.1 (secret regex).
  - PCI-DSS 7 (auth on payment-named paths).
- Score: 100 - 25×critical - 15×high - 5×medium + 2×passed (:533-547).
- `pdf_report.py` uses **fpdf2** (:49), with a .txt fallback, grades A-F and a table capped at 30 routes.
- Used by phase p06 (subtasks.py:16-17) and factory_run_compliance_router.py:44-45. ISO 27001 is only mentioned by name.

**`security/code_scanner.py`**
- `bandit -r` runs synchronously with no timeout inside async code (:100), followed by secret regexes (`sk-`, `AKIA`, PEM, password literals), per-domain regexes (several are broken lookaheads) and `pip-audit`. Used by p06 task_agent.py:74.
- It overlaps the compliance scanner on secrets and CORS with different formats, and p06 runs both.

### 3.7 Security, identity and encryption

**prompt_guard**
- Rejects input over 10k characters, 10 jailbreak regexes and 5 injection regexes (backticks, `$(`, `<script`, `; rm`). The 400 response is sent at factory_start_router.py:278-282.
- It blocks many legitimate requirements, such as "admin can override", "bypass cache" or any backtick, and is easy to get around.

**zero_trust**
- HMAC-SHA256 over JSON {project, resource, action, exp}, 300s TTL, `compare_digest` (:26-90). The key comes from `AETHER_ONE_ZT_SECRET`, which is required, but its length is not checked.
- It is issued in factory_pipeline.py:906 and checked in phases/base.py:188. **Every failure is only a warning or debug log.** There is no nonce, so tickets can be replayed within the TTL.

**encryption.py**
- Fernet (AES-128-CBC + HMAC) with `AETHER_FIELD_KEY` (:28).
- Production without a key raises an error. Any other ENVIRONMENT value silently uses an **ephemeral key** (:31-43), so encrypted data written then cannot be decrypted after a restart or by another worker.
- A decrypt failure returns None (:70-77), which silently loses `org_api_keys.api_key`. MFA fails closed in that case (gateway/auth_mfa.py:184).
- There is no key rotation (no MultiFernet). Encrypted columns: users.mfa_secret and org_api_keys.api_key.

**password_shield**
- Minimum length 10, a 30-word blocklist that includes `demo1234` (:31), at least 3 of 4 character classes, and at least 4 unique characters. HIBP is queried with a 5-character SHA-1 prefix and padding, and the check **fails open**.
- Used at signup and password reset (auth_router.py:78; auth_password_router.py:183,221).

### 3.8 Guardian (platform self-protection)

**Lifecycle and schedule**
- Started with `asyncio.create_task(get_watchdog().start())` (gateway/lifespan.py:281). `stop()` only sets a flag (:300).
- Ticks every 30s: health checks and brute-force detection. Every 5 minutes: file integrity. Every 6h: a snapshot (watchdog.py:27-105). Because the timer uses monotonic time, every boot snapshots immediately.

**Detection** (threat_detector.py)
- Counts `login:*` ZSETs in Redis, which the rate limiter writes: 15 or more is high, 45 or more is critical (:40,132-157).
- SHA-256 of 5 hard-coded files (gateway/api.py, gateway/auth.py, core/models.py, core/db.py, alembic/env.py; listed in core/guardian/build_identity.py). The baseline is tied to the deployed build (see "Integrity baseline per build" below). It can also be re-baselined by superadmin endpoints (`POST /guardian/update-baseline`, `/admin/system/deploy`) and, on legacy installs, scripts/post-deploy.sh.
- Disk: 80% or more is medium; **92% or more is critical `service_crash`**. A failed Redis ping is high; a failed DB `SELECT 1` is critical (:195-254).
- The "rate anomaly" detector listed in its docstring is not implemented.

**Integrity baseline per build** (build_identity.py, threat_detector.py `load_or_create_baseline`)
- Why: the baseline used to be written to Redis on first boot only. The Redis volume outlives image rebuilds, so every compose/Kubernetes deploy raised a false critical `TAMPER DETECTED`, which teaches operators to ignore the real one.
- At image build the Dockerfile writes `/srv/aether_os/.guardian_build_manifest.json` (root-owned, mode 0444; the app runs as `aether` and cannot rewrite it) with the critical files' hashes. Optional build arg `AETHER_BUILD_ID` (compose passes `${AETHER_BUILD_ID:-}`, e.g. `AETHER_BUILD_ID=$(git rev-parse HEAD) docker compose up -d --build`) is baked into the image env.
- Build id at start: `env:<AETHER_BUILD_ID>` if set, else `manifest:<digest of the manifest>`, else none.
- With a build id the baseline is the manifest's hashes, stored with HSETNX in Redis hash `guardian:baseline:<build_id>` (field = path relative to the package root); `guardian:current_build` records the active build. A new build id gets a fresh baseline and no alert; the previous build's hash expires after 7 days (rolling deploys keep it while old pods drain). The change is logged at WARNING: `Guardian: new build X (previous Y) — file integrity baseline re-established`.
- Within one build the stored baseline is never overwritten at start, so a file changed while that build runs is detected, also after a container restart. Because the manifest is written at build time, a change made between build and first start is detected too.
- Trade-off: without `AETHER_BUILD_ID`, the id is derived from the manifest. An attacker who is root inside the container (not just the app user) can rewrite a critical file and the manifest together and restart; that yields a new build id and a quiet re-baseline, visible only as the WARNING above. With `AETHER_BUILD_ID` set the id comes from the image config, which nothing inside the container can change, so the same attack is still reported. Set it in production. Startup never re-baselines unconditionally.
- No manifest and no `AETHER_BUILD_ID` (bare-metal/systemd installs from deploy/deploy.sh): legacy behaviour, unchanged. Baseline in `guardian:file_hash:<md5(abs path)>` on first boot; refreshed by scripts/post-deploy.sh and the admin deploy route.
- Redis unavailable: the same baseline (manifest, or the files at start) is held in memory and checked against; it is also the fallback when a Redis baseline key is missing.
- `file_tamper` is still alert + `pre_threat` snapshot only, never a restore.

**Event handling** (watchdog.py:109-187)
- Events are de-duplicated with Redis `SET NX EX 600` and persisted to guardian_events.
- High or critical events trigger a `pre_threat` snapshot.
- **Only a critical `service_crash` triggers auto-recovery.** File tampering deliberately does not.

**Snapshots** (snapshot_manager.py)
- `pg_dump --format=custom <DATABASE_URL>` with a 300s timeout, or the sqlite backup API. Stored in `GUARDIAN_SNAPSHOT_DIR` (default `./snapshots/guardian`), keeping 10, with a SHA-256 in guardian_snapshots.
- Restore is `pg_restore --clean --if-exists` with a 600s timeout; exit code 1 counts as success (:278-294). SQLite keeps a .bak to roll back to.
- Manual triggers: superadmin-only `POST /snapshots` and `POST /restore/{id}` (guardian_snapshots_router.py:93-129), with no confirmation and no check for running runs.

**Auto-recovery** (auto_recovery.py:25-183)
- Waits up to 150s for running runs to finish, takes a `pre_recovery` snapshot, restores `get_latest()`, runs `alembic upgrade heads`, then probes `SELECT COUNT(*) FROM organisations`.
- The placeholder comment `# ... rest of the original recover() logic ...` is still in the code (:56).

### 3.9 Snapshot manager (DEAD)

- `snapshot/manager.py` copies a project workspace to `<project>/.aetherone_snapshots/<ts>/` with snapshot.json, and provides diff (SHA-256), materialize, and an in-place restore that requires force=True (:225-504).
- No importers. Unrelated to the Guardian DB snapshots. If it were ever wired up, `snapshot_id` and `destination_path` are not checked for path traversal.

### 3.10 Chaos, capacity, cells, cloud primitives (TEMPLATE for generated apps)

**chaos_generator**
- Emits LitmusChaos into `output_dir/chaos/`: rbac.yaml, pod-delete, network-partition and cpu-hog for each entity, a ChaosSchedule and a test plan.
- Called by phase P20 (phases/p20_multiregion/task_agent.py:20,65), only for `deployment_target=="kubernetes"`. P20 itself is triggered by stages/s12_specialist/supervisor.py:61,123.
- It does **not** inject faults into AetherOS.
- Output defects: the field selector is invalid, the ChaosSchedule schema is wrong, and the ClusterRole grants CRUD on secrets and nodes.

**capacity_planner**
- Deterministic tier tables (standard, high_throughput, real_time, batch) giving HPA CPU%/memory%/min/max values, e.g. standard 70/80/2/10 (:22-27), plus KEDA (Kafka lag 50 or CPU), PDB (67% or 50%) and quota/LimitRange.
- No LLM involved. Used by P20.
- Output defects: an HPA and a KEDA ScaledObject target the same Deployment, and scale-to-zero is promised but `minReplicaCount` is always at least 1.

**cell_planner** (test-only)
- EKS per region, Global Accelerator, Route53, a VPC mesh, an nginx cell router (70% primary, hashing on `X-Tenant-Id`), a cell_health.py and a failover runbook.
- Output defects: the generated cell_health.py uses `socket` without importing it, the Global Accelerator Terraform is invalid, and the runbook sets weights on latency records.

**cloud_primitives** (test-only)
- Kong (CORS `*` with credentials; JWT with `consumers: []`, so every call gets 401), NATS (subject and slug mismatch) and MinIO.
- The generated `_bucket_for` never returns its value, and `rstrip("s")` mangles bucket environment names, so storage is broken. Placeholder `changeme` secrets.
- There are no boto3, redis or nats runtime adapters; those libraries appear only inside the generated strings.

### 3.11 Sandbox (DEAD)

- `sandbox/manager.py` runs code with host `subprocess.Popen` plus `setsid`, RLIMIT_CPU 10s, RLIMIT_AS 1GB and a 30s wall-clock timeout followed by killpg (:219-299).
- There is **no network isolation** (`allow_network` is "reserved", :78), and the **full `os.environ` is inherited** (:252).
- Shell mode runs `/bin/sh -c` (:260). An SSH/paramiko backend uses RejectPolicy (:380).
- `guard.py` is a regex blocklist (`os.system`, `subprocess.`, `exec(`, …) that is easy to get around.
- **Nothing imports `core.sandbox`.** There is no Docker sandbox anywhere in scope. A separate `phases/p08_cicd/sandbox/` exists but belongs to another worker.

### 3.12 run_app (launching generated-app previews)

**Launch sequence**
- `POST /factory/runs/{id}/run-app`, then `run_app_service._launch_generated_app`, then `RunAppManager.start` (run_app_service.py:46-54; process_manager.py:67).
- `pip install` of the generated requirements (Postgres drivers stripped) **into the platform interpreter** (:129-149).
- `npm install` and `npx vite build`, retried with less memory on OOM (:224-326).
- Optional `alembic upgrade head`, then `python -m uvicorn src.main:app --host 127.0.0.1 --port N` in a new session (:366-401).
- The app's database is swapped for SQLite `preview.db` (:361), and it runs with `env={**os.environ}` (:360).

**Ports, health and fallbacks**
- The port comes from binding `127.0.0.1:0`; the socket is released before uvicorn starts, which leaves a TOCTOU race (run_app_service.py:32-43).
- The health check calls `poll()` right after Popen and never again (:402,453), so crashes go undetected.
- Fallbacks: if Vite fails, an API-explorer HTML page is served; if the backend fails, a stub FastAPI app with mock data runs (helpers.py:21-164).

**Patching the generated code** (helpers.py:167-475)
- Strips RBAC 403s from crud.py (:393-397).
- Makes foreign keys nullable.
- Sets the seed admin password to `Admin1234!` and writes it to `preview_credentials.json` (:443-473).
- Rewrites react-router-dom imports to @tanstack/react-router.

**State, proxy and cleanup**
- State is kept in four places: in-process dict, Redis (`app:state:{run_id}`, 2h TTL; app_state.py:29-32), `run_app_state.json`, and DB `live_url="/app-preview/"`.
- The **proxy is FastAPI, not nginx** (gateway/routers/app_preview_router.py, httpx). There is **one global preview** (`__current__`), **no auth dependency** (:27), every header including Authorization and Cookie is forwarded (:120-124), and CSP is set to `default-src * 'unsafe-inline' 'unsafe-eval'` (:129). On ConnectError it restarts the app as a system user with org_id=None (:144-146).
- Cleanup happens only through `DELETE /run-app`: terminate, wait 5s, then kill. There is no idle reaper, and log file handles leak.
- The synchronous `subprocess.run` calls in async `start()` block the event loop for up to about 21 minutes.

### 3.13 Telemetry, scheduler, queue

**Telemetry**
- Live: only the LangSmith tracer, gated on `LANGSMITH_OPT_IN` plus an API key (:43-53) and wrapped around `model_router.call` (model_router.py:93). Its synchronous `create_run` and `update_run` calls block the event loop.
- `spine.py` (a JSONL sink with 500MB rotation) is DEAD. `phases/p08_cicd/temporal_prediction.py:31` imports a `.telemetry_spine` module that does not exist. `telemetry/notifications.py` imports a `src.notifications` package that does not exist.
- There is no OpenTelemetry. Prometheus metrics come from prometheus_fastapi_instrumentator in the gateway, patched by prometheus_patch.py.

**Scheduler (DEAD)**
- An in-memory list sorted by (-priority, seq) and awaited serially, with no cron, no APScheduler and no driving loop. Its `schedule(name, coro, priority, *args)` signature mis-binds arguments.

**Queue**
- **SQS only. There is no Redis, arq or Celery.**
- If `SQS_QUEUE_URL` is set, factory_start_router.py:339-353 sends the job; if sending fails, or SQS is unset, the run executes in-process with `asyncio.create_task`.
- The consumer starts in lifespan.py:269 and long-polls with a 20s wait and 1h visibility timeout. Its heartbeat runs every 10 minutes using synchronous boto3.
- Consumer defects:
  - No concurrency cap (`create_task` per message, no stored reference).
  - It forwards only 14 fields, so `user_personas`, `mode`, `intake_answers`, `app_brand`, `multi_tenancy` and `agency_*` are dropped (pipeline_consumer.py:58-74 vs factory_start_router.py:324-336).
  - A failed message is not deleted, so it reruns every hour with no attempt counter or DLQ.

### 3.14 Billing, webhooks, notifications, connectors

**Billing**
- `billing/impl.py` meters only: hardcoded per-token prices with environment overrides (:23-40), written fire-and-forget to llm_call_records. Errors are logged at debug level.
- Payments live in gateway/routers: Razorpay in billing_router.py (HMAC webhook, :236-246) and Stripe in billing_stripe_router.py (`construct_event`, :109-131).
- `billing/router.py` is not an HTTP router; it is dead.

**Webhooks**
- `delivery.deliver_event` loads the org's active `models.Webhook` rows and fires a task per hook. Each hook is signed with `X-AetherOS-Signature-256: sha256=HMAC(secret, body)` and retried 3 times at 5, 30 and 120s, with an SSRF check on each attempt (:26-180).
- Called from orchestrator/pipeline_completion.py:92.
- **Signing bug:** `create_webhook` stores `secret=None` and keeps only a bcrypt hash (webhooks_router.py:75-80). Delivery then signs with `w.secret or ""`, an **empty key** (delivery.py:176).
- SSRF gaps: `gethostbyname` resolves IPv4 only and blocks; `update_webhook` does not re-validate the URL; `test_webhook` performs no SSRF check at all (webhooks_router.py:100-138).

**Notifications**
- smtplib with STARTTLS in `to_thread` (email.py:36-62). Sends run complete/failed mail (db_utils.py:271-283), auth and password-reset mail, and admin mail. `project_name` and `url` are inserted into the HTML unescaped.

**Connectors**
- LDAP uses ldap3 for real; the username is **put into the search filter unescaped** (ldap_connector.py:234-236).
- Salesforce makes real httpx calls to the REST API. The `instance_url` comes from the request (SSRF and token exfiltration), the token travels in a query string (plugins_connectors_router.py:166-169), and `object_name` is not URL-encoded (:143).

### 3.15 Plugins and skills

**Discovery and install**
- The docstring promises YAML manifests from built-in, `~/.aether_os/plugins` and DB sources (registry.py:4-28). In reality the catalog is a hardcoded `BUILTIN_PLUGINS` list (:103-354). `entry_point` strings are never resolved; classes come from the static `_CONNECTOR_MAP` (connectors_registry.py:266) and `_SKILL_MAP` (skills.py:501).
- There is no third-party code loading, so no plugin sandbox is needed.
- Install is per org in installed_plugins, with an upsert on (org_id, plugin_id) (:400-416).
- Plan gating uses trial<starter<growth<enterprise. The plan "pro", which seed and account code use, raises ValueError and becomes a 500 (:498-503).
- `config_json` is stored **in plaintext** (:406,412,452). `to_dict` masks only the keys token, secret, password and api_key, so fields such as bot_token, access_token, secret_access_key, service_key and credentials_json leak (:95-96).

**Connectors and skills**
- Connectors: GitHub, GitLab, Jira, Linear and Slack (connectors.py); Figma, Vercel, Sentry and Supabase over httpx; AWS via boto3 STS; Stripe and PlanetScale with a test call only; GCP is a stub that always reports ok (connectors_registry.py:214-216). Salesforce, LDAP and AD load lazily.
- **Import is broken:** connectors.py:346 imports `core.plugins.connectors_registry`, which imports `core.plugins.connectors` back (:13), both without the `aether_os.` prefix. Under Docker's `PYTHONPATH=/srv` (Dockerfile:34) this raises ModuleNotFoundError, so `/v2/plugins/installed/{id}/test` and `/v2/connectors/invoke` return 500 (plugins_router.py:156,188). Confirmed by an import probe.
- Skills are 10 near-identical f-string prompts sent through `LLMClient`. They are reachable only from `POST /v2/plugins/skills/generate` (plugins_connectors_router.py:90-116), which has no install or plan gate, and no pipeline phase uses them.

### 3.16 Services layer

All services use the async ORM with org_id scoping; the only parameterised `text()` is in guardian_service.py:183.

- **pipeline_service.start_run** (:28-103): rate limits, then policy, then create_run, then the memory context, then `get_factory().run` as a background task. **Only marketplace_router uses it**; factory_start_router bypasses it, so normal runs skip the policy check and the cross-run memory context.
- **settings_service**: CRUD for llm_config, org_api_keys, phase_configs and saml_configs.
- **guardian_service**: stats, with a superadmin bypass.
- **memory_service**: Chroma first, then a SQLite fingerprint fallback; user prefs live in `users.user_preferences`.
- **learning_service**: per org and user. `store_clarification` is never called.
- **global_pattern_service**: cross-org rolling averages with an unlocked read-modify-write.
- **account_service**: GDPR export and erase. The erase call **deactivates every API key in the org** (:153-155).
- run_service has 8 dead functions and account_service has 6.

### 3.17 Bootstrap, config, validators

**Bootstrap (DEAD)**
- Nothing imports the bootstrap package. The app starts through `uvicorn aether_os.gateway.api:create_app` (Dockerfile:46) and `gateway/lifespan.py`.
- runtime_manager steps 5 and 6 are just `asyncio.sleep(0.1)` (:262-306).
- safe_mode's `is_active()` is never checked, and `factory_reset` does nothing.
- offline_guard patches only `socket.create_connection` and `urlopen`, so httpx and asyncio connections still get through.

**Config loader**
- Hardcoded defaults (loader.py:39-102), deep-merged with YAML from `$AETHER_CONFIG_PATH` or `~/.aether_os/config.yaml`.
- The documented `AETHER_<KEY>` environment overlay **is not implemented** (:20-38). Most real configuration comes from `os.environ` read directly all over the code.

**Validators**
- `validators/registry.py:28-90` loads every `auto_generated/*.py` with `exec_module`, in-process, and calls `validate(output_dir)`. It is called from stages/s07_healing/supervisor.py:136.
- These files are written at runtime by `core/repair_learning.py:390-432`, which is called from p07b quality_helpers.py:44, s05 gate_functions.py:295 and s03 supervisor.py:134. They come from templates that embed `{event.domain!r}` inside a `"""` docstring.
- A domain string containing `"""` breaks out of the docstring and becomes code. The only check is `ast.parse`, and the domain is derived by the LLM.
- The files land in the shared source tree, so all tenants run them. They are timestamped and accumulate without limit.

### 3.18 Other infrastructure helpers

**rate_limiter**
- A Redis ZSET sliding-window log (:102-112) plus an INCR counter for concurrency.
- Defaults: 5 concurrent runs per org, 20 starts per hour, 10 factory starts per minute, 5 logins per IP per 15 min, 5 registrations per hour, 5 resets per 15 min, 100 public requests per minute (:140-144,325,367).
- When Redis is unreachable, login and registration fall back to per-worker memory; factory and public limits fail open. Localhost is exempt outside production.
- **The client IP is taken from the leftmost X-Forwarded-For entry**, which the client can spoof (:62-65).
- Check and record are separate calls (a race), and ZSET members are millisecond timestamps, so same-millisecond hits collide.

**pipeline_state**
- Redis pub/sub on `pipeline:events:{id}`, history with a 24h TTL, and `pipeline:control:{id}` with a 1h TTL (:68-108). Every event is also inserted into Postgres `pipeline_events`.
- Falls back to memory without Redis. The failed Redis client is cached for the life of the worker (:43-44).
- It is also the JWT blacklist client. Without Redis the blacklist is skipped (dependencies.py:90).

**api_key_store**
- Lookup order is a 60s cache, then org_api_keys (encrypted), then environment variables (:42-79).
- **`save_api_key` writes the org's key into `os.environ`** (:138-141), where it becomes every org's fallback.

**artifact_store**
- Embeddings stored as JSON, with numpy cosine scoring over `LIMIT limit*4` rows fetched without ORDER BY, so results are an arbitrary subset (:125-128).
- Content is resolved from snapshots, then the project directory, then S3. The directory path is joined without a containment check (:218).

**workloop_monitor**
- Every 300s it reads the last 20 runs across **all orgs**, asks `model_router` (task_type=summarize) for a diagnosis, and with `WORKLOOP_AUTO_FIX` (on by default) **sets `os.environ` keys** from an allowlist (PRIMARY_LLM, BEDROCK_*, timeouts; :241-273).
- Its health event uses run_id `__platform__`, which violates the pipeline_events foreign key, so it fails silently.

**seed**
- Creates the admin user and org from the required `AETHER_ADMIN_EMAIL` and `AETHER_ADMIN_PASS` (:28-40): org id `org_demo_aetheros_ai`, plan pro, trial limit 999, bcrypt cost 12, plus 10 marketplace rows. No password is hardcoded.

**feature_flags**
- Order is GrowthBook, then `FEATURE_*`, then defaults. Nothing calls `is_on()`; only system_info_router lists the flags.

**error_registry**
- A JSON array with a lock and atomic swap. Categories: relative_import, ast_parse_failure, missing_all_routers, seed_unique_violation, missing_router_reference, unknown. Per host; currently empty.

**projects.py**: a JSON index rewritten with no lock.

**app_state**: the per-worker memory copy is read before Redis, so readers can see stale data.

---

## 4. Control flow and data flow

```
startup  gateway/lifespan.py
  ├─ init_db()                      create_all + indexes                      (db.py:150)
  ├─ ensure_demo_user()             env admin + marketplace seed              (seed.py)
  ├─ get_watchdog().start()         Guardian 30s loop                         (lifespan:281)
  ├─ workloop_monitor loop          LLM diagnosis → os.environ                (lifespan:275)
  └─ SQS pipeline_consumer          if SQS_QUEUE_URL                          (lifespan:269)

POST /factory/start (factory_start_router)
  prompt_guard.guard ─400─▶ reject
  rate_limiter checks (Redis ZSET)
  [SQS_QUEUE_URL] sqs_client.send ─▶ consumer.create_task(factory.run)   (drops ~10 fields)
  [else / send fail] asyncio.create_task(run_pipeline_background)
      (marketplace path only: services/pipeline_service → policy.check_pipeline_start [always allow] → memory ctx)
  factory_pipeline
     ├─ zero_trust.issue → phases/base verify (warn-only)
     ├─ ComplianceEngine.evaluate (precheck; deny only on critical; fail-open)
     ├─ _await_human_approval (core.decisions; timeout/exception ⇒ continue)
     ├─ spec_review_gate (Redis poll; auto-approve 600s)
     ├─ p06: security/code_scanner (bandit, pip-audit) + compliance/code_scanner → pdf_report
     ├─ s03/s05/p07b: repair_learning → writes core/validators/auto_generated/*.py
     ├─ s07: validators.run_all_validators → exec_module in-process
     ├─ P20 (k8s): chaos_generator + capacity_planner → YAML into output_dir
     ├─ every LLM call: model_router → langsmith_tracer (opt-in) + billing.impl → llm_call_records
     ├─ events: pipeline_state.publish → Redis pub/sub + pipeline_events row → SSE
     └─ completion: db_utils.update_run_status → email; webhooks.deliver_event (empty-key HMAC)

POST /factory/runs/{id}/run-app
  run_app_service.acquire_free_port → RunAppManager.start
    pip (platform interpreter) → npm/vite → patch code → uvicorn 127.0.0.1:N (env=os.environ)
    state → app_state(Redis) + run_app_state.json + runs.live_url
  GET /app-preview/* (no auth) → httpx → 127.0.0.1:N (forwards Authorization/Cookie)

Guardian tick
  detect (Redis login:* | file sha | disk/Redis/DB) → dedup (Redis NX) → guardian_events
  high/critical → pg_dump snapshot ; critical service_crash → auto_recovery
     → pre_recovery snapshot → get_latest() (= that same snapshot) → pg_restore --clean → alembic upgrade heads

Audit: routers → ledger.async_log_audit_event → audit_log(prev_hash) ; purge endpoint deletes oldest
```

Where state is stored:
- **Postgres or SQLite:** all ORM tables.
- **Redis:** pipeline events and control, rate-limit ZSETs, the JWT blacklist, run-app state, Guardian file hashes, dedup and cooldown keys.
- **Filesystem:**
  - `~/.aether_os/projects/*` and `_index.json`
  - `./snapshots/guardian/*.dump`
  - `core/error_registry.json`
  - `core/validators/auto_generated/`
  - `~/.aether_os/audit.jsonl`
  - `<project>/run_app.log`, `preview.db` and `run_app_state.json`
- **S3:** artifact uploads, if `S3_BUCKET` is set.
- **SQS:** pipeline jobs, if configured.

---

## 5. Plane mapping

- **Security:**
  - Encryption: encryption.py, EncryptedText columns.
  - API keys: SHA-256 hashed api_keys; Fernet-encrypted org_api_keys.
  - Passwords: password_shield; bcrypt in seed and auth.
  - Intake: prompt_guard.
  - Code scanning: security/code_scanner (bandit, pip-audit, secrets).
  - zero_trust (warn-only).
  - Guardian threat_detector (brute force, file tamper).
  - rate_limiter (login, register and reset limits; spoofable IP).
  - JWT blacklist via pipeline_state Redis.
  - Webhook HMAC (broken) and SSRF checks.
  - Dead: sandbox.
  - Gaps: run_app isolation, the app-preview proxy.
- **Compliance:**
  - policy/compliance + compliance_india (export control, EU residency, AI Act-like rules, DPDP, RBI, SEBI, CERT-In).
  - compliance/code_scanner (HIPAA, GDPR, SOC2, PCI) with pdf_report (fpdf2) and manifest (duplicated in p06).
  - audit/ledger audit_log with a non-verifying prev_hash chain.
  - GDPR export and erase in account_service.
  - The purge endpoint.
  - policy/engine presets for fintech and healthcare (not enforced).
- **SRE:**
  - Guardian: watchdog, threat_detector, snapshot_manager, auto_recovery; guardian_service plus the routers.
  - workloop_monitor (LLM self-tuning).
  - langsmith_tracer.
  - prometheus_patch with the gateway instrumentator.
  - logging_config (structlog).
  - DB pool settings and `statement_timeout`.
  - SQS visibility heartbeat.
  - Dead: telemetry/spine, scheduler, bootstrap safe mode, snapshot/manager.
- **Generated-app SRE (TEMPLATE):** chaos_generator, capacity_planner (P20); cell_planner and cloud_primitives (test-only).
- **Admin control:**
  - Guardian superadmin endpoints: manual snapshot, restore, re-baseline.
  - settings_service (LLM config, org keys, phase config, SAML).
  - seed (admin bootstrap).
  - feature_flags (inert).
  - account_service (org soft delete, settings).
  - Plugin install and plan gating.
  - The client-portal approve route (broken).
  - Decision approval routes (outside scope).
- **API management:**
  - rate_limiter (per org, per IP, public 100/min).
  - api_key_store (per-org provider keys).
  - api_keys table (SHA-256).
  - billing/impl (token metering) and the gateway Stripe/Razorpay routers.
  - Webhooks (outbound).
  - Plugin connectors (GitHub, Jira, Slack, Salesforce, LDAP and others; import broken).
  - Kong gateway config (generated-app TEMPLATE, dead).
- **Deployment:**
  - run_app (local preview runtime).
  - SQS producer and consumer (job distribution).
  - init_db with create_all versus Alembic's multiple heads.
  - Guardian alembic upgrade during recovery.
  - deploy.sh calls post-deploy.sh to re-baseline Guardian.
  - P20 Kubernetes YAML.
- **Data:** db.py, models.py (33 tables), db_utils, artifact_store (embeddings and S3), pipeline_state (event stream), projects.py, error_registry, app_state.
- **Learning and pipeline support:** services/{memory, learning, global_pattern}; validators plus repair_learning; context_helpers; plugins/skills (LLM).

---

## 6. Interfaces and dependencies

**Consumed by this scope**
- Redis (redis.asyncio, through `pipeline_state.get_redis` and the rate_limiter client).
- SQLAlchemy async with asyncpg or aiosqlite.
- cryptography (Fernet), bcrypt.
- boto3 (SQS, S3, AWS STS), httpx (webhooks, proxy, connectors, HIBP), ldap3, paramiko (dead).
- fpdf2; bandit and pip-audit command-line tools; pg_dump and pg_restore binaries; npm/npx/vite; uvicorn; alembic.
- psutil (dead bootstrap), growthbook (optional), langsmith (optional), structlog, prometheus_fastapi_instrumentator, smtplib, PyYAML.
- Internal: core.llm.LLMClient and model_router (skills, workloop, billing hooks); core.decisions (real gates); core.repair_learning (validator writer).

**Exposed to other code**
- `get_session_factory`, `get_db`, `init_db`, `Base` and the models (~97 importers).
- `pipeline_state.publish`, `set_control` and `get_redis`.
- `rate_limiter.check_*` and `record_*`.
- `DecisionLedger` (audit).
- `ComplianceEngine.evaluate`, `scan_file`/`generate_pdf`, `CodeScanner.scan_project`, `guard()`.
- `issue_ticket`/`verify_ticket`.
- `get_watchdog`, `SnapshotManager`.
- `RunAppManager.start`, `deliver_event`, `send_*` email functions, `get_connector`, `get_skill`, `PluginRegistry`.
- `run_all_validators`, `get_config`.

**Gateway routers using this scope**
- auth*, account*, settings, guardian, guardian_snapshots, admin_platform, compliance, factory_run_compliance, factory_start, factory_runs, factory_ops, run_app, app_preview, webhooks, plugins, plugins_connectors, billing, billing_stripe, marketplace, memory, learning, system_info, health, client_portal.

---

## 7. Reality check

### Security (highest first)

1. **Webhooks are signed with an empty key** (delivery.py:176 together with webhooks_router.py:75-80). Signatures can be forged, and the customer's own secret never verifies.
2. **`/app-preview` has no authentication.** It is one global preview shared by all tenants, forwards Authorization and Cookie to LLM-generated code, and sets a CSP of `*` (app_preview_router.py:27,120-129). The generated app inherits the full platform `os.environ`, pip-installs into the platform interpreter, has its RBAC stripped and an admin password of `Admin1234!` (process_manager.py:145-148,360; helpers.py:393-473). `stop_run_app` performs no org check.
3. **Runtime validators allow code injection and are shared across tenants.** Files are executed with `exec_module` in-process (validators/registry.py:28-34), and the templates are injectable through `{domain!r}` inside `"""` (repair_learning.py:69-74).
4. **Cross-tenant LLM key leak and billing:** `save_api_key` sets `os.environ` (api_key_store.py:138-141).
5. **workloop_monitor lets an LLM change platform environment variables**, based on run error text that can be influenced from outside (workloop_monitor.py:205,254-260).
6. **Spoofable X-Forwarded-For** lets clients get around login and registration limits (rate_limiter.py:62-65). The JWT blacklist is skipped when Redis is down (dependencies.py:90).
7. **SSRF:** `test_webhook` has no SSRF check, and `update_webhook` does not re-validate. The LDAP host and Salesforce `instance_url` come from the request. There is LDAP filter injection (ldap_connector.py:234) and the Salesforce token is sent in a query string.
8. **Plaintext secrets:** installed_plugins.config_json, scim_token, webhooks.secret (deprecated) and questionnaire access_token. The plugin mask misses most secret field names. pg_dump and pg_restore receive `DATABASE_URL` with its password on the command line (snapshot_manager.py:68,84,283). Snapshot dumps are not encrypted.
9. **Ephemeral Fernet key** whenever ENVIRONMENT is anything other than exactly "production" (encryption.py:31-43). A failed decrypt silently returns None.
10. Path traversal in artifact_store (:218); HTML injection in email (email.py:68-90); reflected XSS in the fallback page (process_manager.py:335).
11. The HIBP check and policy, compliance, zero-trust and human-gate checks all **fail open**.

### Correctness and bugs

- **Guardian:**
  - Auto-recovery restores its own `pre_recovery` snapshot (auto_recovery.py:59-61 with snapshot_manager.py:215-218).
  - Disk usage of 92% or more causes a destructive restore, repeated every 10 minutes (threat_detector.py:205; watchdog.py:130).
  - When the DB is down, recovery throws before restoring (auto_recovery.py:41).
  - `row.id` is read before flush, so it is None (watchdog.py:177).
  - On restore failure the snapshot stays in `restoring` state and its file leaks.
  - `pg_restore --clean` reverts guardian_snapshots too.
  - The pg_dump fallback is dead code (:80-92).
  - `postgresql+asyncpg://` URLs break pg_dump.
- **Approval:** `get_approvals_store` does not exist, so the client-portal approve route returns 500. `guarded.py` passes a wrong keyword argument.
- **Policy:** `logger` is undefined (engine.py:3), and `requires_approval` is ignored.
- **Audit:** the chain is not transitive, races, is never verified and can be purged. `drain_audit_futures` is never called. `AuditLogger._entries` grows without bound.
- **Imports:**
  - Connectors package import is broken (connectors.py:346 ↔ connectors_registry.py:13).
  - `telemetry/notifications.py` imports a `src.notifications` that does not exist.
  - `temporal_prediction.py:31` imports a missing `.telemetry_spine`.
  - `core.db` and `core.config.loader` are imported without the `aether_os.` prefix.
- **SQS consumer:** drops enrichment fields, has no concurrency cap, and rereads a failed message every hour forever.
- **run_app:**
  - The health check is ineffective.
  - It blocks the event loop for up to about 21 minutes.
  - Port TOCTOU race.
  - The stub app is always regenerated.
  - The `run_preview.py` template is missing `import secrets`.
- **Data layer:**
  - 12 tables exist only through create_all, so schema drift goes unnoticed.
  - The PhaseConfig composite primary key is misused in db_utils:337-363 (dead code).
  - The `__platform__` run_id violates a foreign key.
  - artifact search returns arbitrary rows instead of the top-k.
- **Rate limiting:** check and record race each other, and same-millisecond entries collide.
- **Services:**
  - GDPR erase revokes every API key in the org (account_service.py:153).
  - An unknown plan such as "pro" raises in plugin gating (registry.py:500).
  - global_pattern averages are not atomic.
- **Config loader:** the documented env-var overlay does not exist.
- **Prompt guard:** blocks legitimate application requirements.
- **India rules:** fire for all of APAC; RBI rules deny every fintech SaaS.
- **Templates for generated apps:**
  - Chaos: invalid field selector and schedule schema.
  - Capacity: HPA and KEDA both scale the same Deployment.
  - Cell: missing `socket` import and invalid Global Accelerator Terraform.
  - Cloud primitives: storage `_bucket_for` returns nothing, `rstrip("s")` mangles names, and Kong JWT rejects every request (401).

### Dead modules (about 5K LOC)

- core/bootstrap/ (1,037)
- core/sandbox/ (808)
- core/scheduler/ (444)
- core/snapshot/manager.py (505)
- core/telemetry/spine.py (415) and notifications.py (49)
- core/approval/arbitration.py and guarded.py (958); store.py and workflow.py are dead in effect
- core/compliance/manifest_writer.py (prod)
- core/security/scanner_models.py
- core/billing/router.py
- core/webhooks_model.py and core/workspace_model.py (would fail if imported)
- cell_architecture and cloud_primitives (test-only, ~1,300)
- feature_flags evaluation; the unused pgvector column
- 8 functions in run_service, 6 in account_service, 3 in db_utils; `learning_service.store_clarification`; `memory_service.build_repo_graph`

### Duplication

- Two code scanners.
- Two manifest writers.
- Two `ScanResult` classes.
- Three risk-mapping functions that disagree.
- Four audit sinks.
- Duplicate Webhook and Workspace models.
- Two snapshot systems for different purposes.
- A validator loader in both validators/registry and repair_learning.

### Size and style

- No file is over 600 lines; sandbox/manager.py is at 599.
- Imports inside functions are common.
- Repeated model imports in account_service.py:12-18 and db_utils.py:14-27.

---

## 8. Open questions

1. Is `core/decisions` (another worker's scope) the intended approval system, making `core/approval` obsolete? Should human gates fail closed in regulated (fintech or healthcare) runs?
2. Is SQS used in production on the VPS? If not, all runs execute in-process inside the API worker and the consumer path is untested. Do the dropped enrichment fields matter?
3. Who calls the webhook secret-reveal flow? Is the bcrypt-only storage intentional, and if so how were signatures meant to be verified?
4. Should run_app previews move to Docker (compose already exists for the platform) with a scrubbed environment and per-org authentication on `/app-preview`?
5. Is the Guardian snapshot directory on a persistent volume in docker-compose? Is `DATABASE_URL` in production plain `postgresql://`, so that pg_dump works?
6. Are `audit_log` and the other 11 create_all-only tables present and in sync on the VPS database? Which Alembic heads does production sit on?
7. Is `phases/p08_cicd/sandbox/` (out of scope) the real execution sandbox for generated tests?
8. Is `WORKLOOP_AUTO_FIX` enabled in production? It is on by default.
9. The demo login `demo1234` sits in password_shield's blocklist, and seed requires environment credentials. Which mechanism actually created the demo account on the VPS?
10. Is the connectors import failure masked in any environment where `core` happens to be on `sys.path`, such as local runs from the repo root?
