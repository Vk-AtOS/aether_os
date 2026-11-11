# 01 — Orchestration spine
Scope: `main.py`, `__init__.py`, `orchestrator/` (incl. `routing/`, `{routing}/`), `stages/s01–s12`, `phases/__init__.py`, `phases/base.py`, `phases/utils.py`, `phases/gateway/`, `agents/`, `integrations/`. 62 files, ~11,500 LOC. Git HEAD 052a101 (plus the uncommitted `agents/implementations.py` diff). Mapped 2026-11-08. Every file was read in full. Claims were checked with grep, ruff F821, and small Python runs.

---

## 1. Summary

This slice is the **control plane of the code factory**. A run enters through `FactoryPipeline.run()` (`orchestrator/factory_pipeline.py:112`). It gets a global concurrency semaphore and a 30-minute overall timeout. It builds one large `accumulated_context` dict, picks the stages to run (start_phase or checkpoint resume), and topologically sorts **12 stages** (`s01_intake … s12_specialist`) into 9 waves (`phase_dag.py`). Each stage is a `PhaseBase` supervisor (`phases/base.py:41`). The supervisor runs its legacy sub-phases (`phases/pXX_*/task_agent.run()`, about 50 of them) through an import-by-name call, then applies a gate with retry ×3 and escalation. After each stage, post-hooks run: spec-review gate, architecture/IR loading, knowledge graph, BackendAuditCouncil re-gen loop, quality-gate self-healing loop. When the pipeline finishes, background tasks run: DeliveryCouncil, notifications, webhooks, learning, embedding, S3, app auto-start. Events go to Redis pub/sub for SSE. State persists in the `runs` table (status, checkpoint_data, finished_at) and in `phase_completions`.

**Headline finding:** commit `d81e33c` ("move function-scoped imports to module level") pasted 26 import lines **inside the module docstring** of `factory_pipeline.py` (lines 10–35). Python never runs them. That leaves **48 undefined-name references** (ruff F821). Each one sits inside a `try/except Exception`, so the pipeline still "works", but it silently loses several features. These include run creation via `create_run`, the org autonomous_mode lookup, per-user learning, zero-trust tickets, the human-approval gate, guided-mode questionnaires, the external monitor bridge, escalation notifications, finished_at on abort or cancel, and change-request context loading. Section 7 lists each one.

---

## 2. Coverage table

| File | LOC | Purpose | Status |
|---|---|---|---|
| `main.py` | 304 | Typer CLI: `start` (uvicorn `aether_os.gateway.api:app`), `demo`, `status`, `build-dashboard` | `start`/`status` REAL; **`demo` BROKEN** (no `org_id` → ValueError at factory_pipeline.py:233; imports nonexistent `core.pipeline_state.get_event_queue` at main.py:165) |
| `__init__.py` | 2 | `__version__ = "1.0.0"` | REAL |
| `orchestrator/__init__.py` | 1 | comment | — |
| `orchestrator/factory_pipeline.py` | **1231** | `FactoryPipeline`: the main run loop, phase execution, human approval, change requests, guided-mode questionnaire | REAL but **degraded** (docstring imports); **>600 lines** |
| `orchestrator/phase_sequence.py` | 154 | `PHASE_SEQUENCE` (12 stages), `CRITICAL_PHASES` (s01–s03), `PHASE_SUPERVISORS`, `_load_supervisor()` | REAL |
| `orchestrator/phase_dag.py` | 280 | `PHASE_DEPENDENCIES`, Kahn topo sort into waves, DFS cycle detection | REAL (p0x entries are legacy and inert) |
| `orchestrator/parallel_runner.py` | 283 | `run_phases_in_wave()`: asyncio.gather of a wave on a context snapshot | REAL with major propagation gaps (§7) |
| `orchestrator/phase_selector.py` | 145 | `select_phases`, `AREA_TO_PHASE`, `resolve_change_request_phase`, `restore_from_checkpoint` | REAL |
| `orchestrator/phase_hooks.py` | 470 | Post-stage hooks: s01 intake/spec gate, s02 arch+KG, s03 merge/patterns/BackendAuditCouncil, s06 quality gate→s07 loop | REAL code; several **path mismatches** make parts no-ops (§7) |
| `orchestrator/phase_hooks_helpers.py` | 168 | File loaders: live_url, design_brief, service_map, integration_map, permission_model, domain_ir | REAL |
| `orchestrator/spec_review_gate.py` | 160 | LLM spec critique, then waits on Redis for `spec_approved` (auto-approves after 600 s) | REAL + LLM-DRIVEN |
| `orchestrator/pipeline_completion.py` | 198 | Inline finished_at, then background tasks (auto-start, council, notif, webhook, learning, memory, embed, S3, Redis cleanup) | REAL |
| `orchestrator/artifact_collector.py` | 461 | embed_artifacts, upload_to_s3, DeliveryCouncil check and remediation, store_run_memory, extract_learning | REAL; **council remediation DEAD** (p0x names) |
| `orchestrator/run_state.py` | 108 | project-name regex, semaphore, `save_checkpoint`, `update_phase_state` | REAL |
| `orchestrator/context_schema.py` | 85 | Advisory key checks after each stage | REAL (advisory); most expected keys never produced |
| `orchestrator/events.py` | 51 | ContextVars `ACTIVE_RUN_ID/PHASE/ORG_ID`; `emit()` → Redis publish_event | REAL |
| `orchestrator/bus.py` | 176 | `MessageBus` (Redis RPUSH/BLPOP plus asyncio.Queue fallback), `get_bus`, `release_bus` | REAL but **write-only**: no production subscriber |
| `orchestrator/messages.py` | 40 | Pydantic `PhaseInput`, `PhaseResult`, `PhaseMessage` | REAL |
| `orchestrator/context.py` | 111 | `ExecutionContext` / `PhaseOutput` (legacy 10-phase model) | DEAD in prod (legacy `pipeline.py` and tests only) |
| `orchestrator/state_machine.py` | 228 | 26-state `PipelineStateMachine` + transition table | DEAD in prod (legacy `pipeline.py`, `routing/router.py`, tests) |
| `orchestrator/pipeline.py` | 303 | Deprecated 10-phase `Pipeline` (emits DeprecationWarning) | DEAD (tests only) |
| `orchestrator/pipeline_helpers.py` | 436 | Legacy phase implementations (LLM prompts, p07 runner, p08 repair, tar packaging) | DEAD (legacy), LLM-DRIVEN |
| `orchestrator/predictor.py` | 116 | Stage-duration z-score stall predictor | DEAD (no importers) + event-loop deadlock bug |
| `orchestrator/routing/__init__.py` | 1 | comment | — |
| `orchestrator/routing/router.py` | 64 | failure-type → retry-state map | DEAD (tests only) |
| `orchestrator/{routing}/` | 0 | empty dir (shell brace-expansion artifact) | DEAD |
| `stages/__init__.py` + 12 `sXX/__init__.py` | ~20 | re-export supervisors via **bare** `from stages.sXX…` | REAL (needs repo root on sys.path) |
| `stages/s01_intake/supervisor.py` | 263 | p00/p00b/p00c in parallel, then p01, then p01b | REAL orchestration (LLM in sub-phases) |
| `stages/s01_intake/helpers.py` | 32 | `merge_stage_outputs` | DEAD (never called) |
| `stages/s02_architecture/supervisor.py` | 271 | p02 → p02b (critical) → p02c → p03 | REAL |
| `stages/s03_backend/supervisor.py` | 426 | p04 (calls p04a) → p04b → p04c (if integrations) → ArchitectureGovernor | REAL |
| `stages/s03_backend/helpers.py` | 108 | required-file check, entity router count | REAL |
| `stages/s04_frontend/supervisor.py` | 359 | p05, plus p05b/c/d/e conditional | REAL |
| `stages/s05_quality/supervisor.py` | 368 | p06 ‖ p06b, then dimension critic, then critical-issue scan and LLM regen | REAL; **LLM regen DEAD** (llm never supplied) |
| `stages/s05_quality/helpers.py` | 109 | `quality_gate_summary` | REAL |
| `stages/s05_quality/gate_functions.py` | 304 | regex/AST critical scan, `regenerate_file` (LLM) | scan REAL; regen unreachable |
| `stages/s06_testing/supervisor.py` | 297 | p07a unit tests only (live tests deferred to s07); idempotent cache | REAL |
| `stages/s07_healing/supervisor.py` | 299 | p07b self-healing, validators, live perf/a11y/E2E | REAL; **crash bug** on the "already healed" path |
| `stages/s08_observability/supervisor.py` | 409 | p09 → (p11a ‖ p11b ‖ p11c) → p11d; Mimir config if high scale | REAL (TEMPLATE-heavy sub-phases) |
| `stages/s09_devops/supervisor.py` | 398 | p08_cicd_deployment → p11_deployment (TaskAgent class) → p11e conditional | REAL |
| `stages/s10_enterprise/supervisor.py` | 401 | p12a,p12b,p13,p16,p18,p21 in parallel; p17 conditional; autowire routers into main.py | REAL; autowire likely a no-op (§7) |
| `stages/s11_handoff/supervisor.py` | 303 | p10 → (p14 ‖ p15); delivery ZIP; quality_report.json | REAL |
| `stages/s12_specialist/supervisor.py` | 240 | conditional p05b/c/d/e, p19, p20 in parallel | REAL (duplicates s04 conditionals) |
| `phases/__init__.py` | 36 | sys.modules aliasing `aether_os` / `aether_os.phases` | REAL |
| `phases/base.py` | 298 | `TaskResult`, `GateOutcome`, `PhaseBase` (memory → task → gate → retry → escalate → bus/WhatsApp) | REAL |
| `phases/utils.py` | 57 | `memory_hint`, `phase_input_data` (used by 6 phases) | REAL |
| `phases/gateway/client_portal/{__init__,routes.py,index.html}` | 0/99/125 | stale copy of `gateway/client_portal`; `/approve` is a stub | DEAD (api.py mounts `aether_os.gateway.client_portal.routes`, api.py:281) |
| `agents/__init__.py`, `agents/tools/__init__.py` | 1/1 | comments; `tools/` is empty | — |
| `agents/base.py` | 195 | `AgentKind`, `AgentName` (14), `AgentContext`, `AgentResult`, `Agent`, `AgentRegistry` | REAL |
| `agents/implementations.py` | 435 | 14 agents + `get_agent_registry()`; served by `gateway/routers/agents_router.py` | mixed: 3 LLM-DRIVEN, rest heuristic/STUB; Snapshot broken |
| `integrations/__init__.py` | 0 | — | — |
| `integrations/aether2_bridge.py` | 95 | `ExternalMonitorBridge`: fire-and-forget HTTP telemetry on daemon threads | effectively DEAD (its only import is in the docstring → NameError → bridge=None) |

---

## 3. Components and how they work

### 3.1 Entry points
- **CLI** `main.py`: `start` runs `uvicorn.run("aether_os.gateway.api:app", workers=min(2×CPU,8))` (main.py:120). Docker instead uses `gateway.api:create_app --factory` (Dockerfile:46). The banner hardcodes "Tests: 639 passing" (main.py:110). `demo` calls `FactoryPipeline().run(...)` with no org_id (main.py:186). `status` checks env vars, `MemoryStore.stats()` and `ledger.get_run_history()`.
- **Production callers of `get_factory().run()`**:
  - `gateway/routers/factory_start_router.py:226` (main start endpoint, all enrichment fields)
  - `core/services/pipeline_service.py:86`
  - `core/queue/pipeline_consumer.py:28` (SQS worker; PreFlightCouncil first)
  - `gateway/routers/factory_runs_router.py:315,372` (rerun from phase, branch)
  - `gateway/routers/run_decisions_router.py:157` (restart)
  - `gateway/mcp_router.py:108` (MCP start)

### 3.2 `FactoryPipeline` (factory_pipeline.py)
- `run()` (:112) reads `PIPELINE_TIMEOUT_MINUTES` (default 30). It acquires the `_get_pipeline_semaphore()` slot (`PIPELINE_MAX_CONCURRENT`, default 2; run_state.py:43) and calls `asyncio.wait_for(_execute_pipeline(...))`. On timeout it sets status `timeout` and publishes `pipeline_complete`.
- `_execute_pipeline()` (:173):
  1. `init_org_llm_context` (:214). **NameError, swallowed.**
  2. `~/.aether_os/projects/<run_id>/` plus `project_memory` init (:219–229).
  3. Hard-requires `org_id` (:231).
  4. `create_run` (:237). **NameError**, so it falls back to `ledger.async_save_run`.
  5. council_preflight persist (:251). **NameError.**
  6. Org `autonomous_mode` lookup (:267). **NameError**, so `decision_mode` is always `"approval_required"`.
  7. Builds `accumulated_context` (:278–334) with ~35 keys: identity, plan, raw_input, domain, decisions log, tech_prefs, designer_spec (merged from tech_preferences :335–348), personas, brand, realtime, multi_tenancy, mode, questionnaire fields.
  8. User learning injection (:351). **NameError.**
  9. `select_phases` then `restore_from_checkpoint` (:365–372).
  10. `ExternalMonitorBridge` if `MONITOR_URL` is set (:376). **NameError.**
  11. Waves from `get_execution_waves` (:396). Falls back to sequential if that fails.
- **Multi-stage wave** (:406–465): `run_phases_in_wave()`, then per phase `save_checkpoint` + `_pm_update`, abort if a critical phase failed, check the cancel control.
- **Single-stage wave** (:467–827):
  - set ContextVars; `_update_state(running)`; emit `phase_start`; build `PhaseInput`
  - s04 is skipped when frontend is "none" (:495–523)
  - per-phase timeout `PHASE_TIMEOUT_<NAME>` → `PHASE_TIMEOUT_SECONDS` → 600 (s04 1200, s09 1800) (:493–531)
  - `wait_for(_run_phase)`; guided-mode pause (:549); escalation, then notification and `_await_human_approval` (:559–593)
  - emit `file_written` for each file (:596–621)
  - set `{phase}_output` / `{phase}_path`, **merge `metadata` into context** (:629–632)
  - `assert_context` + `validate_context_after_stage` (:635–645); confidence trail and `low_confidence_phases` (<0.5) (:648–662); `phase_summaries` sliding window (:666–680)
  - `save_checkpoint` (:683); `run_phase_hooks` (:689)
  - `_update_state(passed|completed)`, project memory, emit `phase_complete`
  - Timeout or exception sets status timeout/failed and aborts if critical (:730–787). Pause/cancel polling every 2 s (:797–827).
- Completion (:831–886): phase state `pipeline=complete`, run status `council_review`, `persist_finished_at`, publish `pipeline_complete(status=council_review)`, `schedule_completion_tasks(...)`, `release_bus`.
- `_run_phase()` (:888): `_load_supervisor(name)`; zero-trust `issue_ticket` (:906, **NameError** → no ticket); `supervisor.run(phase_input)`. Maps `TaskResult` to status `escalated|passed|failed` plus confidence/issues/metadata/artifacts/duration. Catches `BaseException` (re-raises only CancelledError).
- `_await_human_approval()` (:956): `DecisionEngine.request_approval` + `await_decision` (`HUMAN_APPROVAL_TIMEOUT` 300 s); denied → `set_control(cancel)`. **NameError → logs an error and continues.**
- `run_change_request()` (:993): `resolve_change_request_phase` (default `s03_backend`); loads original `project_memory.json` (`_json` **NameError** → empty); then calls `run(start_phase=..., is_change_request=True)`.
- `_pause_for_questionnaire()` (:1054): creates a `QuestionnaireSession` (token TTL 7 d), sets run status `waiting_for_input`, polls the DB every 30 s, and releases/re-acquires the semaphore around each sleep. **First call `get_stage_questions` is a NameError**, so guided mode is a silent no-op.

### 3.3 Stage registry, DAG, selection
- `PHASE_SEQUENCE` (phase_sequence.py:90). `PHASE_SUPERVISORS` maps to `aether_os.stages.sXX.supervisor.<Class>` (:108). `_load_supervisor` tries `aether_os.stages…` and then bare `stages…` (:124–154). It returns None for unknown names (used by council remediation).
- `INACTIVE_PHASE_DIRS` (:46) is documentation only; it is imported (factory_pipeline.py:65) but never used.
- `PHASE_DEPENDENCIES` (phase_dag.py:24). Computed waves (verified by running it):
  `[s01] [s02] [s03] [s04] [s05, s12] [s06] [s07] [s08, s09, s10] [s11]`.
  `build_dag` drops deps that are not in the run set and falls back to the previous list item for unknown names (:122–152).
- `select_phases` slices from `start_phase` (phase_selector.py:48). `restore_from_checkpoint` reads `Run.checkpoint_data{last_completed_phase, accumulated_context}` and resumes at index+1 (:83–145). `AREA_TO_PHASE` maps 26 area words to stages (:17).

### 3.4 Parallel runner (parallel_runner.py)
- `_fast_snapshot` JSON round-trips context values (deepcopy fallback) (:45). Every phase in the wave gets the same snapshot.
- Per phase: timeout `PHASE_TIMEOUT_<NAME>` → `PHASE_TIMEOUT_SECONDS` → 600 (s04 1200; **s09 not special-cased**) (:63–67).
- After the gather it merges **only** `{phase}_output`, `{phase}_path`, the confidence trail and phase summaries (:238–270).
- It does **not** merge `metadata`, does not run `run_phase_hooks`, does not handle guided mode or escalation, and does not run `assert_context`.

### 3.5 Post-stage hooks (phase_hooks.py, phase_hooks_helpers.py)
`run_phase_hooks` (phase_hooks.py:35) calls every hook in turn; each hook checks `phase_name` itself:
- **s09** `hook_persist_live_url` writes `Run.live_url` (helpers:17). Unreachable in practice: s09 runs in a parallel wave, which skips hooks.
- **s01**:
  - `_hook_p01_intake` (:158) reads `p01_intake_requirements/intake/intake.json` → `project_name`, then runs `run_spec_review_gate` if `decision_mode != autonomous` (:194). Because of the NameError this happens on **every run**.
  - `hook_load_research` → `build_profile`, `domain_knowledge`; `hook_load_architecture_planner` → `service_map`; `hook_load_integration_discovery` → `integration_map`.
- **s02**:
  - `_hook_p02_architecture` (:211) → `architecture_json`, then builds a `KnowledgeGraph` (domain/tech/endpoint/model nodes) → `graph_context`, `knowledge_graph.gpickle`.
  - `hook_load_permission_model`; `hook_load_domain_ir` → `domain_ir_path` + `save_ir_to_knowledge_graph`.
- **s03** `_hook_p04_backend` (:274):
  - "S11" merge of `project_dir/p04_backend/backend_codegen/src` into the p03 scaffold → `backend_src_dir`
  - `api_routes_path`; `PatternSelector.apply_all` (pattern library)
  - **BackendAuditCouncil**: `run_council()` on main.py + crud/models/schemas/auth (12k chars, 90 s timeout). If score < `COUNCIL_THRESHOLD` (0.70), injects `council_feedback` and re-runs s03 (up to 2 retries).
- **s06** `_hook_quality_gate` (:76): `score_project(project_dir)`.
  - ≥80 → sets `s07_healing_done`.
  - Otherwise injects `quality_score_details` and calls `run_phase_fn("s07_healing", phase_input)`, up to 2×. On the 3rd failure it sends a notification and raises `PipelineBlockedError`.

### 3.6 Spec review gate (spec_review_gate.py)
`_run_spec_critique` builds the spec text from `p01_intake_requirements_output`. That key is never set; the sequential path writes `s01_intake_output`. So it effectively uses raw_input/project/domain. It then calls `critique_spec(text, llm)` (LLM). `run_spec_review_gate` (:82):
- `set_control("spec_review")`, emit `spec_review_ready`
- poll `get_control` every 3 s for `spec_approved` (set by `gateway/routers/run_spec_router.py:212`) or `cancel` (raises RuntimeError → s01 fails → critical abort)
- auto-approves after `SPEC_REVIEW_TIMEOUT` (600 s)

### 3.7 Completion (pipeline_completion.py, artifact_collector.py)
`schedule_completion_tasks` (pipeline_completion.py:113) creates tasks tracked in `_background_tasks`:
- `auto_start_app` (`run_app_service._launch_generated_app` as a system admin user)
- `delivery_council_check` (DeliveryCouncil, 120 s): score < 0.5 → `_run_council_remediation_phases` → second council → persist `completed | needs_review` + `council_delivery`
- completion `Notification`, `pipeline.complete` webhook, `extract_learning` (UserPattern upserts + `GlobalPattern` running averages)
- project memory finalize, Redis cleanup after 300 s, `store_run_memory` (MemoryService), `embed_artifacts` (≤`ARTIFACT_EMBED_LIMIT` 5000 files), `upload_to_s3`

On council timeout or error the run is marked `completed` with `council_delivery_passed(note=council_timeout|error)` (artifact_collector.py:341–374).

### 3.8 PhaseBase (phases/base.py) — the shared supervisor pattern
`run()` (:178):
1. Verify `_zt_ticket` if present. A failure is only a **warning**, so zero trust is not enforced. In practice no ticket exists (NameError upstream).
2. `fingerprint(str(input_data))` → `memory_before` (MemoryStore top-5).
3. Loop `max_retries=3`: `run_task` → `validate_gate`.
   - Pass: write `gate_result.json`, `memory_after` (MemoryStore + ChromaDB, with **org_id=domain**, :124), `communicate(passed)` → MessageBus.
   - Fail: prepend `{"failure": issues}` to memory_ctx and retry.
4. On exhaustion: `_escalate` → bus message `escalated` → `TaskResult(escalated=True)`.
5. `_send_whatsapp` through WAHA (`WAHA_URL`). Only used when `whatsapp_msg` is passed; no stage passes it.

### 3.9 Stages s01–s12 → legacy phases
Each stage calls `importlib.import_module("aether_os.phases.<pXX>.task_agent").run(phase_input, memory_ctx, out_dir)`. Output goes to `project_dir/<pXX>/` (`ProjectManager.get_output_dir`, core/projects.py:73). The one exception is s03, which nests under `project_dir/s03_backend/p04_backend/…` (s03 supervisor :245).

| Stage | Sub-phases (order) | Critical | Gate | File:line |
|---|---|---|---|---|
| s01_intake | (p00_research ‖ p00b_data_archaeology ‖ p00c_architecture_planner) → p01_intake_requirements (on a deep-copied input) → p01b_integration_discovery | yes | `entities` + `project_contract` present | s01:107–181, 200–217 |
| s02_architecture | p02_architecture → p02b_domain_ir (critical) → p02c_permission_modeling → p03_scaffolding | yes | domain_ir.json exists, non-empty, ≥1 entity | s02:96–197, 216–261 |
| s03_backend | p04_backend (internally runs p04a_backend_codegen + p04_uiux_design) → p04b_business_logic → p04c_integration_codegen (only if `integration_map.integrations`) → ArchitectureGovernor phantom-entity check | yes | `backend_output_path` set and ≤2 of 5 required files missing | s03:48–186, 192–230 |
| s04_frontend | p05_frontend; then p05b_mobile / p05c_desktop / p05d_cli / p05e_serverless based on `build_profile` | no (but blocks via retries/escalation) | index.html/App.tsx/App.jsx exists **and** success | s04:107–260, 262–307 |
| s05_quality | (p06_review_security ‖ p06b_formal_verification) → dimension critic → `detect_critical_issues` → LLM `regenerate_file` (unreachable) | no | always pass | s05:71–255 |
| s06_testing | p07a_unit_testing only; p07b_performance/p07c_a11y/p07d_e2e are deferred to s07 | no | always pass | s06:56–66, 103–189 |
| s07_healing | p07b_self_healing → `run_all_validators` → live tests (p07b_performance_testing, p07c, p07d) if L1 passed | no | always pass | s07:76–243 |
| s08_observability | p09_observability → (p11a_monitoring ‖ p11b_error_tracking ‖ p11c_analytics) → p11d_alerting; Mimir files if users>10k / enterprise / k8s high load | no | always pass (warnings) | s08:151–339 |
| s09_devops | p08_cicd_deployment → p11_deployment (`TaskAgent().run()` dict) → p11e_enterprise_deployment (if k8s/microservices) | no | always pass (warnings) | s09:152–310, 349–397 |
| s10_enterprise | (p12a_feature_flags ‖ p12b_ab_testing ‖ p13_app_memory ‖ p16_iam ‖ p18_billing_metering ‖ p21_sre_agent) → p17_control_plane (if k8s/microservices) → autowire routers into main.py | no | always pass | s10:210–374 |
| s11_handoff | p10_docs_delivery → (p14_client_portal ‖ p15_handoff) → `project_delivery.zip` + `quality_report.json` | no | always pass | s11:93–167 |
| s12_specialist | conditional: p05b, p05c, p05d, p05e, p19_service_catalog (cloud_platform), p20_multiregion (k8s + microservices) | no | always pass | s12:87–214 |

The sequence and supervisors do **not** register p00_intake, p00a_intake, p01_requirements or p09_documentation (marked dead, phase_sequence.py:49), and they do not register p08_cicd directly (p08_cicd_deployment wraps it). Every `STAGE_CONTRACT` dict (s01:49, s02:46, s06:68, s07:43, s10:169, s11:51, s12:51) is documentation only; nothing reads it.

### 3.10 Agents (agents/)
`get_agent_registry()` (implementations.py:421) registers 14 agents. They are reached only through `GET /agents` and `POST /agents/{name}/run` (gateway/routers/agents_router.py:22,40). The factory pipeline never calls them.

| Agent | What it does | Status |
|---|---|---|
| PolicyAgent | `policy.engine.check_pipeline_start` | REAL |
| RiskAgent | `ComplianceEngine.evaluate` | REAL |
| SnapshotAgent | writes `Snapshot(phase=, data=)`, but the model has no such columns (core/models.py:121) | BROKEN, returns error |
| MemoryKnowledgeAgent | MemoryStore retrieve | REAL |
| RedTeamSafetyAgent | substring blocklist | TEMPLATE/heuristic |
| StabilityGuardianAgent | DB/Redis ping | REAL, but **bug** below |
| SystemSpecProfilerAgent | platform info | STUB |
| BusNetworkManagerAgent | counts `pipeline:events:*` keys | REAL |
| FixEngine / CodeReview / Refactor | `client.call` | LLM-DRIVEN (works only with the uncommitted diff) |
| TestAgent | regex pass/fail count | heuristic |
| SecurityAnalyzerAgent | substring patterns + compliance | heuristic |
| RepoReasoningAgent | `ProjectMatcher.find_similar` | REAL |

### 3.11 Integrations
`ExternalMonitorBridge` (aether2_bridge.py:20): `register_pipeline`, `report_stage_start/complete`, `report_failure` (POST `/webhook/ci-auto`). Calls are fire-and-forget `requests` on daemon threads. It is wired at factory_pipeline.py:376–386, 533–540, 723–770, but it is unreachable because of the docstring import.

---

## 4. Control flow and data flow

```
HTTP POST /factory/start (factory_start_router) | SQS consumer | MCP | rerun/branch/restart | CLI demo(broken)
  └─ get_factory().run(client_id, raw_input, org_id, …~30 kwargs)
       ├─ semaphore(PIPELINE_MAX_CONCURRENT=2) + wait_for(PIPELINE_TIMEOUT_MINUTES=30)
       └─ _execute_pipeline
            ├─ project_dir ~/.aether_os/projects/<run_id>; project_memory.json
            ├─ Run row (create_run → NameError → ledger.async_save_run)
            ├─ accumulated_context{…}   ← the ONLY real inter-stage data channel
            ├─ select_phases(start_phase) → restore_from_checkpoint(Run.checkpoint_data)
            ├─ get_execution_waves → 9 waves
            ├─ for wave:
            │    single → _run_phase → Supervisor(PhaseBase).run
            │               ├─ memory_before → run_task (sub-phase task_agent.run ×N) → validate_gate
            │               ├─ retry ×3 → escalate (bus msg) → TaskResult(escalated)
            │               └─ communicate → MessageBus (Redis list, never consumed)
            │             → metadata merged into context → checkpoint → run_phase_hooks
            │             → guided pause (no-op) / escalation approval (no-op)
            │    multi  → parallel_runner: snapshot → gather → merge only _output/_path
            │    control check: cancel / pause (Redis pipeline:control:<run_id>)
            ├─ status council_review, finished_at, pipeline_complete event
            └─ background: auto-start app, DeliveryCouncil→completed|needs_review, notif, webhook,
                           learning, memory, embeddings, S3, Redis cleanup(+300 s)
```

- **Event bus (SSE):** `orchestrator/events.emit()` → `core.pipeline_state.publish_event` (Redis pub/sub + history). Event types emitted in this slice:
  - `phase_start`, `phase_complete`, `file_written`, `wave_start`, `wave_complete`
  - `pipeline_resumed`, `approval_required`, `spec_review_ready`, `spec_review_timeout`, `gate_error`
  - `quality_gate_passed`, `llm_chunk` (quality gate), `pipeline_complete`
  - `council_remediation_start/complete`, `council_delivery_review/passed`
  - `artifact_embed_truncated`, `s3_upload_complete`, `app_started`

  ContextVars `ACTIVE_RUN_ID/PHASE/ORG_ID` let the LLM client tag `llm_chunk` events and cost (events.py:20–24). They are set only on the sequential path; parallel phases inherit the parent's values, which may be unset.
- **Message bus** (`bus.py`): `PhaseBase.communicate` publishes `PhaseMessage` to Redis `aetheros:bus:<run>:<to_phase>` plus `__broadcast__` (TTL 1 h), plus an in-process `asyncio.Queue(maxsize=1000)` that is always appended to and never drained in production. `subscribe()`/`drain()` are called only in tests. The docstring claim "All inter-phase communication goes through the MessageBus only" (factory_pipeline.py:5) is false: data moves through `accumulated_context` and files on disk.
- **State machine:** the live path does **not** use `PipelineStateMachine`. Live state is:
  - `phase_completions` rows (`update_phase_state`, run_state.py:89; statuses running/passed/completed/failed/timeout/skipped)
  - `runs.status` (running → paused/cancelled/failed/timeout/waiting_for_input → council_review → completed | needs_review)
  - `runs.checkpoint_data`, `runs.finished_at`, `runs.live_url`
  - Redis control key values `run|pause|cancel|spec_review|spec_approved|running`

  The 26-state enum is used only by deprecated `pipeline.py` and `routing/router.py`.
- **Spec review gate:** after s01, if `decision_mode != "autonomous"` (currently always, because of the NameError). It waits up to 600 s per run unless someone approves.
- **Phase selection:** start_phase slice → checkpoint resume. Change requests map areas to the earliest stage. Rerun/branch pass `start_phase=req.from_phase`.
- **Stages vs phases:** the 12 `sXX` stages are the only units the orchestrator schedules. The ~50 `pXX` dirs are a library that stages import (table §3.9). Hooks and `phase_hooks_helpers` still read p-named sub-directories (`p01_intake_requirements/intake/intake.json`, `p00_research/design_brief.json`, `p02_architecture/architecture.json`, `p02b_domain_ir/domain_ir.json`, `p04_backend/backend_codegen/src`). `phase_dag.py`, `state_machine.py`, `context_schema.py` and `artifact_collector._CRITERION_TO_PHASES` keep legacy p-names.

---

## 5. Plane mapping

| Plane | Components in this slice |
|---|---|
| **SDLC (build)** | `FactoryPipeline`, `phase_sequence`, `phase_dag`, `parallel_runner`, `phase_selector` (change requests / rerun), s01 intake/requirements, s02 architecture/IR/scaffold, s03 backend, s04 frontend, s12 specialist, s11 docs/handoff; KG + pattern-library hooks; legacy `pipeline.py`/`pipeline_helpers.py` |
| **STLC (testing / quality)** | s05 quality gate (p06 security review, p06b Z3, dimension critic, critical-issue scan), s06 unit tests, s07 live perf/a11y/E2E, `_hook_quality_gate` (score ≥80 + heal loop), `PhaseBase` gates + retries, s02/s03/s04 gates, ArchitectureGovernor, BackendAuditCouncil, DeliveryCouncil, `context_schema` |
| **SRE / self-healing** | s07 healing (p07b, L1–L4 probes, validators, repair learning), s08 observability generation (Prometheus/Grafana/Sentry/PostHog/Alertmanager/Mimir), s10 p21_sre_agent, `predictor.py` (dead), `routing/router.py` (dead), per-phase timeouts, pause/cancel, checkpoint resume, external monitor bridge (dead) |
| **Security** | zero-trust ticket issue/verify (issue dead, verify warn-only), s05 security scan + secrets/missing-auth AST checks, p06 security review, BackendAuditCouncil, RedTeamSafety/SecurityAnalyzer agents, org_id required (quota bypass guard, :231) |
| **Compliance** | p06 compliance PDF/score through s05; RiskAgent/SecurityAnalyzer → `ComplianceEngine`; `quality_report.json` (s11); audit log of bus publishes + state transitions (`core.audit.logger`) |
| **Deployment** | s09 (p08_cicd_deployment, p11_deployment Docker build/run + live_url, p11e Helm/Terraform), s10 p17 K8s operator, s12 p20 multiregion, `auto_start_app` after the pipeline, S3 upload, delivery ZIP |
| **Admin control / HITL** | spec review gate, human approval on escalation (dead), guided-mode questionnaire (dead), pause/cancel control keys, `decision_mode` from org autonomous_mode (dead → always approval_required), concurrency semaphore, notifications |
| **API management** | none directly. Generated-app routers are wired by s10 autowire; `/agents` API (agents_router) exposes the registry; stale `phases/gateway/client_portal` `/portal/*` routes (dead) |
| **Learning / memory (extra plane)** | PhaseBase memory_before/after (MemoryStore + Chroma), `extract_learning` (UserPattern / GlobalPattern), `store_run_memory`, `embed_artifacts`, KG build, `save_ir_to_knowledge_graph`, `repair_learning` + `stage_feedback` from s03/s05/s07, `project_memory.json` |
| **Observability of the factory itself (extra plane)** | SSE events, ledger, `phase_completions`, confidence trail / `low_confidence_phases`, `phase_summaries`, ExternalMonitorBridge (dead), predictor (dead) |
| **Billing / tenancy (extra)** | org_id required, plan in context, s10 p18 billing scaffold for the generated app, `multi_tenancy` flag sync |

---

## 6. Interfaces and dependencies

**Imports from `core/`:**
- `pipeline_state` (publish_event, get/set_control, clear_run, get_redis), `projects` (ProjectManager), `audit.ledger`, `audit.logger`, `project_memory`
- `db` / `models` (Run, PhaseCompletion, Notification, Organisation, QuestionnaireSession, GlobalPattern, Snapshot), `db_utils.create_run`
- `llm.client` (get_llm_client, init_org_llm_context), `identity.zero_trust`, `decisions.decision_engine`, `questionnaire.stage_questions`
- `services.{learning_service, memory_service, run_app_service}`, `council` (DeliveryCouncil, council_reviewer.run_council), `artifact_store`, `webhooks.delivery`
- `memory.{store, fingerprinter, vector_store, knowledge_graph, matcher}`, `knowledge_graph_integration`
- `quality.{metrics, dimension_critic, dimension_scorer}`, `architecture_governor`, `validators`, `repair_learning`, `stage_feedback`, `errors.PipelineBlockedError`
- `policy.{engine, compliance}`, `approval.workflow`, `config.loader`

**Imports from `phases/`:**
- every `pXX.task_agent.run` listed in §3.9
- `p11_deployment.task_agent.TaskAgent`, `p01_intake_requirements.spec_critique`, `p11a_monitoring.mimir_config`, `phases.patterns.PatternSelector`
- legacy only: `p07_testing`, `p08_cicd.pipeline.run_repair`

**Imports from `gateway/`:** none (gateway → orchestrator only).

**Callers of this slice:**
- gateway routers (factory_start, factory_runs, run_decisions, mcp, agents, run_spec via control key)
- `core/services/pipeline_service.py`, `core/queue/pipeline_consumer.py`
- `core/llm/providers.py` + `core/model_router.py` + many phases import `orchestrator.events`
- phases import `phases.base`, `phases.utils`, `orchestrator.messages`

**Env knobs:**
- `PIPELINE_TIMEOUT_MINUTES`, `PIPELINE_MAX_CONCURRENT`, `PHASE_TIMEOUT_SECONDS`, `PHASE_TIMEOUT_<STAGE>`
- `HUMAN_APPROVAL_TIMEOUT`, `SPEC_REVIEW_TIMEOUT`, `COUNCIL_THRESHOLD`, `ARTIFACT_EMBED_LIMIT`
- `MONITOR_URL` / `MONITOR_API_KEY`, `WAHA_URL`, `DATABASE_URL` (predictor)

---

## 7. Reality check (bugs, dead code, gaps)

**P0: imports trapped in the docstring** (factory_pipeline.py:10–35, introduced by d81e33c; ruff F821 ×48). Each line below is a NameError that is swallowed:

| Line | Swallowed failure | Effect |
|---|---|---|
| :214 | `init_org_llm_context` | per-org LLM keys not pre-warmed |
| :237 | `_create_run` | falls back to `ledger.async_save_run`; fields like project_name/domain/raw_input/client_id may never be set on the Run |
| :254 | council_preflight | never persisted |
| :270 | `Organisation` | autonomous_mode never read → **spec review gate blocks every run for up to 600 s** (unless approved), and escalations always route to the approval gate |
| :354 | `get_user_context` | no personalisation |
| :380 | ExternalMonitorBridge | never constructed |
| :569 | `_Notif_esc` | escalation notifications dropped |
| :747, :777, :804 | `_gsf_fa/_fb/_canc` | finished_at not written on abort or cancel |
| :906 | `_zt_issue` | no zero-trust ticket; phases log "No zero-trust ticket" |
| :962 | `get_decision_engine` | human approval skipped; escalated phases just continue |
| :1028 | `_json` | change requests lose their original context |
| :1079–1211 | questionnaire symbols | guided mode does nothing |

The same commit edited `artifact_collector.py` and `pipeline_helpers.py`; those are clean for F821, though `artifact_collector.py:26` has a duplicate import (F811). Elsewhere in the repo ruff F821 also flags `phases/p21…`, `p08_cicd/pipeline.py`, `p07b`, `p05`, `p04`, `p00`, `core/sandbox/manager.py` and others (25 more hits), which belong to other sections.

**Parallel-wave data loss** (parallel_runner.py:238–270 vs factory_pipeline.py:629–632, 689):
1. `metadata` is not merged for s05, s12, s08, s09 or s10. `PhaseInput(input_data=dict)` copies the outer dict (verified with pydantic 2.13), so in-place writes to `phase_input.input_data` inside stages never reach the master context.
   - s06/s07 never see `security_findings`, `dimension_critique`, `healing_priority`, `compliance_score`.
   - s11's `quality_report.json` gets null compliance/dimension data.
   - s11 never sees s08–s10 outputs.
2. `run_phase_hooks` does not run for parallel stages, so `hook_persist_live_url` (s09) never runs and **`Run.live_url` is never persisted**.
3. Escalation and guided mode are ignored for parallel stages.
4. **s09 timeout is 600 s** in the parallel path. The 1800 s override exists only in the sequential path (factory_pipeline.py:525), yet s09 always runs in a parallel wave.
5. **Checkpoint corruption:** wave `[s05, s12]` saves s05 and then s12 as `last_completed_phase` (factory_pipeline.py:436). If the run crashes after that wave, resume starts at index(s12)+1 = end, so **s06–s11 are skipped**.

**Path mismatches:**
- s03 writes p04 to `project_dir/s03_backend/p04_backend/backend_codegen/src` (s03:245; p04 task_agent:277). `_hook_p04_backend` looks for `project_dir/p04_backend/backend_codegen/src` and `…/src/main.py` (phase_hooks.py:292, 346–350), so the S11 scaffold merge **and BackendAuditCouncil probably never run** (debug "main.py not found, skipping"). No local run reached s03 under the stage pipeline, so this is not confirmed empirically (`~/.aether_os/projects` has 1 stage-era run, which stopped at s01).
- s10 autowire looks for `backend_output_path/main.py` (s10:98), but `backend_output_path` is the dir containing `src/` (s03 helpers:15–21), so it likely always skips. Router candidates are also searched under backend_src, while sub-phases write to `project_dir/p12a_*`.
- `spec_review_gate` reads `p01_intake_requirements_output` (:39), a key that never exists.
- `context_schema.PHASE_OUTPUTS`/`REQUIRED_AFTER_STAGE` expect keys nobody produces (`quality_score`, `observability_config`, `enterprise_features`, `handoff_package`, `domain_ir` for s02, etc.), which causes constant warning noise.

**Stage bugs:**
- **s07 crash** (s07_healing/supervisor.py:99–119): `TaskResult(success=True, output={…}, …)`. `TaskResult` has no `output` field and `output_path` is required, so it raises TypeError (verified). It triggers exactly when the quality-gate hook succeeded (score ≥80, `s07_healing_done=True`). PhaseBase then retries 3× and escalates.
- s07:139 `result.output` gives an AttributeError (swallowed), so `validator_violations` are never attached.
- When the quality score is <80, the hook runs s07 twice and the scheduled s07 runs a third time; the hook then raises `PipelineBlockedError`, which marks s06 failed (non-critical, so the run continues). Hook-triggered s07 runs get the s06 `phase_input` snapshot, which lacks the `quality_score_details` injected afterwards.
- **s05 LLM regeneration unreachable**: `llm = getattr(phase_input,"llm",None) or data.get("llm")` (s05:160). Neither is ever set, so `regenerate_file` never runs. `quality_gate_passed` is computed before the dimension critique is overlaid (helpers.py:96–101 vs s05:149).
- s01/s02 sequential `_run_sub_phase` **re-raises** (s01:196–198, s02:212–214). The `isinstance(result, Exception)` "non-critical" branches are dead, so a failure in p01b, p02, p02c or p03 fails the whole stage → retry ×3 → escalate. Unused `_clone_phase_input` (s02:267).
- s04 and s12 both run p05b/p05c/p05d/p05e under the same `build_profile` conditions, writing into the same `project_dir/p05x` dirs (duplicate work). s12 uses `architecture == "serverless"`; s04 also accepts `event_driven`.
- s08/s09 fall back to `Path("/tmp")` and rglob it (s08:293, s09:250).
- s09 returns `output_path` as a `Path`, not a str (s09:286).
- Spec gate: `get_control` defaults to `"run"` (core/pipeline_state.py:117), so every first gate entry emits a spurious `gate_error` "Gate decision not found…" (spec_review_gate.py:113).
- Council remediation maps criteria to p-names (`p06_review_security`, `p07_testing`, …; artifact_collector.py:114–121), but `_load_supervisor` only knows s-names, so **remediation re-runs nothing**. The second council pass re-scores the same `results`.
- Guided mode, if fixed, waits up to 7 days inside a 30-minute `wait_for` (factory_pipeline.py:155), so the whole run would time out.
- The semaphore log line uses XOR (`sem._value ^ …`) and prints garbage (:148). `exclude_patterns` is unused (:599).

**Agents / other:**
- `StabilityGuardianAgent` calls `_blocked(name, msg, checks)` with 3 args (implementations.py:209), but `_blocked` takes 2, so it raises TypeError exactly when the DB is unreachable.
- `SnapshotAgent` uses nonexistent `Snapshot.phase/data` columns.
- The uncommitted diff (`client.complete` → `client.call`, 3 sites) is **correct**: `LLMClient` has `call()` (core/llm/client.py:123) and no `complete()`. Without it the 3 LLM agents always return an error.
- `predictor.get_stage_baseline` schedules a coroutine on the running loop and then blocks that same loop on `fut.result(timeout=5)` (predictor.py:47–48). That deadlocks for 5 s and returns (0, 0). The module has no importers (DEAD).
- `phases/base.py:124` stores Chroma memories with `org_id=domain`, which breaks cross-tenant isolation semantics for phase-level memory.
- MessageBus in-process queue (maxsize 1000) is never drained. `put` would block at 1000 messages per run. Low risk (~12–60 messages/run) but unbounded across retries.
- Bare `stages.*` imports in `stages/sXX/__init__.py` and s03/s05 supervisors (`from stages.s03_backend.helpers …`, s03:23,194; s05:41–42) need the repo root on `sys.path`. When the code is imported as `aether_os.stages…` this loads duplicate module objects. `phases/__init__.py` does sys.modules aliasing to paper over the same dual-path issue.

**Dead code:** `orchestrator/{pipeline, pipeline_helpers, context, state_machine, predictor}.py`, `orchestrator/routing/router.py`, `orchestrator/{routing}/`, `stages/s01_intake/helpers.py`, `phases/gateway/client_portal/*`, `INACTIVE_PHASE_DIRS` import, all `STAGE_CONTRACT` dicts, `integrations/aether2_bridge.py` (unreachable), `PhaseBase._send_whatsapp` (no caller passes `whatsapp_msg`). In the legacy pipeline, `phase_packaging` runs before `write_output_to_disk`, so it always reports "Project dir not found" (pipeline.py:194 vs :204).

**Docs vs code:**
- factory_pipeline docstring says "29-Phase", the class docstring says "26-phase", the code runs 12 stages. main.py demo says "29-phase"; the banner lists the 10 legacy phases.
- "All inter-phase communication goes through the MessageBus only" is false.
- s06 docstring says "Runs all four test layers concurrently", but only unit tests run.
- s07 says "MAX_ATTEMPTS=5", while the docstring header says 3.
- phase_hooks docstrings still say "After p07_testing" / "p01".

**Files >600 lines:** `orchestrator/factory_pipeline.py` (1231). Project CLAUDE.md pre-approves it as an allowed large file; it is still twice the limit.

---

## 8. Open questions

1. Does p04/p04a write anything to `project_dir/p04_backend/…` (outside the s03-nested dir), so that `_hook_p04_backend` / BackendAuditCouncil actually fire? Needs a real end-to-end stage-era run; only 1 local run exists and it stopped at s01.
2. Do any sub-phases write their outputs into `backend_output_path/` (e.g. `feature_flags/flag_admin_router.py`) so that s10 autowire can work, or is it always a no-op?
3. Where does `score_project` (core/quality/metrics) look? Is ≥80 realistic? That decides whether the s07 crash path (score ≥80) or the triple-heal path (<80) is the common case.
4. Is `Run.live_url` set anywhere else (gateway / run_app_service)? If not, the deployed URL never reaches the DB, because the s09 hook is skipped in parallel waves.
5. Does `ledger.async_save_run` (the fallback after the `create_run` NameError) fill `org_id`, `project_name` and `client_id` well enough for quota/billing and the dashboard?
6. Is the `aether_os` package installed (`pip install -e .`) in Docker/VPS? If so, how do the bare `from stages.…` imports resolve there (PYTHONPATH)?
7. Should the 12-stage DAG run s05 ‖ s12 at all, given that both mutate the project tree (s12 re-runs p05b/c/d/e that s04 already ran)?
8. Are the tests that cover `pipeline.py`, `state_machine.py` and `routing/router.py` (tests/test_pipeline.py, test_core.py) still counted in the "639 passing" claim? They exercise only dead code.
