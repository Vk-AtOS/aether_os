# 02_ph_discovery_design: discovery and design phases (p00 → p04_uiux)

Scope: `phases/p00_research`, `p00b_data_archaeology`, `p00c_architecture_planner`, `p01_intake_requirements`, `p01b_integration_discovery`, `p02_architecture`, `p02b_domain_ir`, `p02c_permission_modeling`, `p03_scaffolding`, `p04_uiux_design`. That is 58 files and 8,145 LOC, all read in full. Commit 052a101. Mapped 2026-11-08.
Wiring context was read so the call path could be verified: `orchestrator/phase_sequence.py`, `stages/s01_intake/supervisor.py`, `stages/s02_architecture/supervisor.py`, `orchestrator/phase_hooks*.py`, `orchestrator/factory_pipeline.py:620-690`, `core/llm/client.py:101-420`.

---

## 1. Summary

- **Execution model.** The orchestrator does not run these phases itself. `PHASE_SEQUENCE` contains only the 12 stage supervisors (`orchestrator/phase_sequence.py:90-103`), and every p0x directory is listed in `INACTIVE_PHASE_DIRS` (`:46-71`).
  - `s01_intake` runs **p00, p00b and p00c in parallel** with `asyncio.gather` (`stages/s01_intake/supervisor.py:107-118`). It then runs **p01** (critical) and **p01b** in sequence (`:134-173`).
  - `s02_architecture` runs **p02 → p02b (critical) → p02c → p03** in sequence (`stages/s02_architecture/supervisor.py:96-185`).
  - Both stages call `phases.<p>.task_agent.run()` directly through `importlib` (`s01:185-198`, `s02:201-214`).
- **Consequence.** Every per-phase `supervisor_agent.py` and `gate.py` in scope is bypassed at runtime. Gates are reached only from `tests/test_phases.py`. The only real gates are the two stage-level ones (`s01:200-217`, which needs `entities` and `project_contract`; `s02:216-261`, which needs a non-empty `domain_ir.json`) plus p02b's internal validator.
- **`p04_uiux_design` is DEAD.** No stage imports it. It has no supervisor, and the only reference is its name in `INACTIVE_PHASE_DIRS`.
- **LLM usage.** Every live phase except p03 makes real LLM calls through `core.llm.client.LLMClient`: `call`, `call_json`, `call_structured` or `call_vision`. Each falls back to a deterministic or canned result. LLM failure never stops the pipeline except in p02b, which hard-fails on 0 entities or a circular FK.
- **The data spine** is `phase_input.input_data`, which becomes `accumulated_context`. The key artifacts are:
  - `design_brief.json` and `build_profile` from p00
  - `requirements.json`, `project_contract` and `entities` from p01
  - `integration_map` from p01b
  - `architecture.json` from p02
  - **`domain_ir.json`** from p02b, the canonical input to all codegen
  - `permission_model.json` from p02c
  - the scaffold directory from p03
- **High-impact defects** (detail in §7):
  1. p02 cannot tell when the LLM failed, for any domain. `call_structured` returns the schema example on failure, and the generic `/items` CRUD example is then accepted as the real architecture (verified).
  2. p02c's validator rejects every response that follows its own prompt, so the LLM result is always discarded and the default model is used (verified).
  3. p02b crashes the critical stage if a workflow step dict has extra keys (`IRWorkflowStep(**s)`), and treats any 2-entity FK cycle as fatal.
  4. p00's Playwright fallback and LLM fallback both raise `NameError` (missing imports), which is caught silently.
  5. p01's intent verification calls a method that does not exist (`llm.complete`), and its "rejected" branch never matches the decision engine's `denied` status.
  6. p00c always skips on a fresh run, because it runs in parallel with the p00 phase that produces `build_profile`.

---

## 2. Coverage table

Status tags:
- **REAL**: works end to end.
- **LLM**: LLM-driven.
- **TPL**: string or codegen templates only.
- **STUB**: placeholder or canned data.
- **DEAD**: never called at runtime, verified by grep across the repo excluding `__pycache__` and `vendor`.

| File | LOC | Purpose | Status |
|---|---|---|---|
| p00_research/__init__.py | 1 | docstring | n/a |
| p00_research/prompts.py | 58 | `STACK_CLASSIFIER_PROMPT` (12 profiles plus keyword rules) and `DESIGN_BRIEF_LLM_FALLBACK_PROMPT` | TPL (used) |
| p00_research/stack_selector.py | 68 | `classify_build()` maps spec to a StackProfile through `call_json`. `inject_into_brief()` | LLM, REAL |
| p00_research/domain_sites.py | 26 | `DOMAIN_COMPETITOR_MAP`: 19 domains → 5 competitor URLs each | TPL (data) |
| p00_research/vision_analyzer.py | 41 | `analyze_screenshot()` through `call_vision` (Bedrock) | LLM |
| p00_research/task_agent.py | 254 | Research orchestration: multimodal intake, classify, screenshots, vision, brief, Gate-1 human approval, business model | LLM, partly broken (§7) |
| p00_research/business_model_generator.py | 135 | `business_model.json` (TAM/SAM/SOM, pricing, GTM) through `call`, with `_FALLBACK_MODEL` | LLM plus STUB fallback |
| p00_research/multimodal_intake.py | 231 | Figma JSON (pure dict walk), diagram (`call_vision`), audio (OpenAI Whisper over httpx, then `call`) | REAL / LLM |
| p00_research/gate.py | 54 | Permissive design_brief gate | DEAD at runtime (tests only) |
| p00_research/supervisor_agent.py | 23 | `ResearchSupervisor` | DEAD (bypassed by s01) |
| p00b_data_archaeology/__init__.py | 0 | n/a | n/a |
| p00b_data_archaeology/task_agent.py | 446 | Existing-schema analysis (LLM call A), ETL script (LLM call B, checked with `ast.parse`), template validate/rollback/README files | LLM plus TPL; no-op without `existing_schema` |
| p00b_data_archaeology/gate.py | 25 | Always passes | DEAD |
| p00b_data_archaeology/supervisor_agent.py | 22 | `DataArchaeologySupervisor` | DEAD |
| p00c_architecture_planner/__init__.py | 0 | n/a | n/a |
| p00c_architecture_planner/prompts.py | 49 | `SERVICE_MAP_PROMPT` (3–7 microservices) | TPL |
| p00c_architecture_planner/helpers.py | 107 | `validate_service_map`, `build_fallback_service_map` (auth plus app), `normalise_service_map` | REAL (unit-tested) |
| p00c_architecture_planner/task_agent.py | 100 | Service map through `call_json`, only when `build_profile.architecture=="microservices"` | LLM; effectively always skipped (§7) |
| p00c_architecture_planner/supervisor_agent.py | 23 | Supervisor | DEAD |
| p01_intake_requirements/__init__.py | 3 | Re-exports the supervisor | n/a |
| p01_intake_requirements/task_agent.py | 350 | One combined `call_json` producing intake, contract and requirements; contract defaults; multi-tenancy and isolation detection; keyword integration flags; requirements.json and .md | LLM, REAL (critical) |
| p01_intake_requirements/gate_engine.py | 243 | `record_architectural_decisions`, `run_intent_verification` (broken), `run_entity_approval_gate` (human-in-the-loop) | LLM / REAL, partly broken |
| p01_intake_requirements/spec_critique.py | 173 | 2-pass LLM spec critique through `call(system=…)` | LLM; live through `orchestrator/spec_review_gate.py:35` |
| p01_intake_requirements/gate.py | 44 | Checks `intake/intake.json`, a file that is never written | DEAD at runtime; logic also stale |
| p01_intake_requirements/supervisor_agent.py | 23 | Supervisor | DEAD |
| p01b_integration_discovery/__init__.py | 0 | n/a | n/a |
| p01b_integration_discovery/task_agent.py | 140 | One `call` returning the `integrations[]` list → `integration_map.json` | LLM |
| p01b_integration_discovery/gate.py | 36 | Always passes | DEAD |
| p01b_integration_discovery/supervisor_agent.py | 22 | Supervisor | DEAD |
| p02_architecture/__init__.py | 3 | Re-exports the supervisor | n/a |
| p02_architecture/prompts.py | 71 | `build_arch_prompt`, `extract_spec_nouns` | TPL |
| p02_architecture/helpers.py | 441 | `ARCHITECTURE_SCHEMA`, keyword→table map, domain fallback schemas/endpoints (saas, healthcare, fintech, ecommerce), `build_fallback_architecture`, `fix_tech_stack` | TPL / REAL |
| p02_architecture/task_agent.py | 390 | spec_cache lookup, RAG (artifact_store), `call_structured(task_type="architecture")`, entity gap-fill, fallback merge, compatibility checks, 6 `record_decision`s, architecture.json and .md | LLM; failure detection broken (§7) |
| p02_architecture/agents.py | 35 | `ArchitectureAgent` (aether2 legacy) | DEAD |
| p02_architecture/onboarding.py | 580 | Repo onboarding analyzer (`analyse_repository`) | DEAD (Aether-One legacy) |
| p02_architecture/monorepo.py | 466 | Monorepo component and change-impact model | DEAD (Aether-One legacy) |
| p02_architecture/gate.py | 69 | `ArchitectureGate`: tech_stack has at least 3 keys, endpoints non-empty | DEAD at runtime (tests only) |
| p02_architecture/supervisor_agent.py | 18 | Supervisor | DEAD |
| p02b_domain_ir/__init__.py | 27 | `DomainIRSupervisor` (defined inline) | DEAD |
| p02b_domain_ir/task_agent.py | 197 | Orchestrates 4-pass extraction, stub IR, clarifying questions, dict validator, `core.ir_validator`, `ir.save` | LLM, REAL (critical) |
| p02b_domain_ir/ir_extractor.py | 593 | Garbage-entity filter, PASS1–4 prompts, `_extract_json`, `_seed_entities`, `_build_ir_from_passes`, `run_4pass_extraction` (4 sequential `call`s), `build_stub_ir`, unused `_COMBINED_PROMPT_TEMPLATE` | LLM (one dead constant) |
| p02b_domain_ir/validator.py | 354 | Rules D1–D7 on the raw IR dict; fatal on D1(0) and D2 | REAL |
| p02b_domain_ir/gate.py | 44 | File gate | DEAD |
| p02c_permission_modeling/__init__.py | 0 | n/a | n/a |
| p02c_permission_modeling/task_agent.py | 196 | ABAC model through `call`; `_build_default_model` | LLM call wasted: result always rejected (§7), so STUB output |
| p02c_permission_modeling/gate.py | 40 | Always passes | DEAD |
| p02c_permission_modeling/supervisor_agent.py | 31 | Supervisor | DEAD |
| p03_scaffolding/__init__.py | 3 | Re-exports the supervisor | n/a |
| p03_scaffolding/task_agent.py | 548 | Optional `git clone` of `github_url`; `create_minimal_scaffold` (FastAPI main, reqs, env files, compose, devcontainer, git init); Redis `cache_service.py`; ast check with LLM repair | TPL plus LLM repair (repair rarely fires) |
| p03_scaffolding/agents.py | 25 | `ScaffoldingAgent` | DEAD |
| p03_scaffolding/generators.py | 288 | Django/Next.js/ROS2/firmware plan builder | DEAD |
| p03_scaffolding/generators_helpers.py | 384 | Django/Next.js/ROS2/C file templates | DEAD (imported only by dead generators.py) |
| p03_scaffolding/prompts.py | 425 | `PromptBundle` registry (fintech/iot/healthcare/gaming/erp) | DEAD (imported only by dead generators.py) |
| p03_scaffolding/gate.py | 46 | Entry point, deps, at least 3 files | DEAD at runtime (tests only) |
| p03_scaffolding/supervisor_agent.py | 18 | Supervisor | DEAD |
| p04_uiux_design/__init__.py | 0 | n/a | DEAD |
| p04_uiux_design/task_agent.py | 118 | Design spec (tokens, pages, components) through `call_json` | DEAD (never invoked) |
| p04_uiux_design/gate.py | 38 | Design gate (buggy) | DEAD |

Roughly 2,950 LOC of the 8,145 are dead: legacy Aether-One modules, supervisors, gates and p04_uiux.

---

## 3. Per-phase breakdown

### p00_research (live, s01 parallel group)
- **Inputs** (`input_data`): `raw_input` / `project_description`, `domain`, `figma_export` / `diagram_image` (+`diagram_image_mime`) / `audio_memo` (+`audio_format`), `autonomous_mode`, `decision_mode`, `org_id`. Also env `AUTONOMOUS_MODE`, `SCREENSHOTONE_API_KEY`, `OPENAI_API_KEY`.
- **Flow** (`task_agent.py:76-253`):
  1. **Multimodal intake** (`:87-95`, `multimodal_intake.py:184-231`):
     - Figma: deterministic tree walk (`:19-71`).
     - Diagram: `call_vision` (`:97`).
     - Audio: Whisper `POST api.openai.com/v1/audio/transcriptions` (`:118-141`), then `call` to structure it (`:176`). If Whisper is unavailable, an LLM "stub" call simply returns a canned sentence (`:151-157`).
  2. **Stack classification** (`:105`, `stack_selector.py:25-62`): `STACK_CLASSIFIER_PROMPT` through `llm.call_json(task_type="analysis")`, mapped by `core.stack_profiles.get_profile`. Falls back to `DEFAULT_PROFILE` (web_saas).
  3. **Competitor sites** come from `DOMAIN_COMPETITOR_MAP` (`:107`). Unmapped domains skip screenshots (`:113-114`).
  4. **Screenshots for the top 3 sites** (`:130-142`): Screenshotone API (`:31-51`), else Playwright (`:54-72`, broken: `async_playwright` is never imported). Each screenshot goes to `analyze_screenshot` (`vision_analyzer.py:28-41`, `VISION_PROMPT` through `call_vision`).
  5. **Synthesis.** The first result's `layout_patterns` / `color_scheme` and the union of `must_have_features` (`:145-152`). `VISION_PROMPT` never asks for those keys, so the fields come out empty in practice. Otherwise the code tries the `DESIGN_BRIEF_LLM_FALLBACK_PROMPT` through `call_json` (`:156-168`), which fails on a missing `get_llm_client` import and ends at `{"navigation":"sticky"}`.
  6. **Injection.** `build_profile` (`profile_to_dict`) and `domain_knowledge` (`core.domain_knowledge.loader.load_pack(domain).to_dict()`) are added (`:171-175`). Writes `design_brief.json`.
  7. **Gate 1 (human-in-the-loop)** (`:181-234`). Runs if `ACTIVE_RUN_ID` is set and not autonomous. Calls `DecisionEngine.request_approval(Decision(decision_type="phase_approval"))`, publishes a `PhaseApprovalRequired` event, then `await_decision`.
     - `approved` + JSON → `user_overrides`; approved + text → `user_instructions`.
     - `denied` → `PipelineBlockedError`.
     - Other errors are swallowed (`:233-234`).
  8. **Business model** (`business_model_generator.py:86-135`): `_BUSINESS_MODEL_PROMPT` through `call(max_tokens=2000)`, then manual fence strip and `json.loads`. On any failure it uses `_FALLBACK_MODEL`. Writes `business_model.json`.
- **Outputs.** Files: `design_brief.json`, `business_model.json`, `screenshot_*.png`. TaskResult metadata: `{domain, build_profile: <profile NAME string>, business_model}` (`:249-253`).
  - s01 copies `build_profile` (a string) and `business_model` into context (`s01:234-263`).
  - The dict form of `build_profile` and `domain_knowledge` reach context only through the post-stage hook `hook_load_research` (`orchestrator/phase_hooks_helpers.py:43-75`), which re-reads `design_brief.json`. `design_brief` itself never reaches context: the metadata has no such key.
- **Gate.** `gate.py` is permissive (always passes unless the file is missing) and is not called at runtime.

### p00b_data_archaeology (live, s01 parallel group, usually a no-op)
- **Inputs:** `existing_schema` (str or dict), `sample_data`, `domain`, `project_name`, `entities`.
- **Without `existing_schema`:** writes `{"skipped":true}` and returns (`task_agent.py:193-203`). Most runs take this path.
- **With a schema:**
  - `_find_similar_past_runs` queries `core.models.Run` (status=completed, same domain, 10 newest) and pulls `checkpoint_data.accumulated_context.entities` (`:129-178`). The result is written into `data["similar_past_runs"]`, which mutates the shared context because the parallel phases share `phase_input`. So "past-run mining", as the s01 docstring advertises, happens only when a legacy schema is uploaded.
  - **Call A** (`:235-290`): inline schema-mapping prompt through `call(task_type="analysis", max_tokens=4000)`, returning `{analysis_md, field_mapping}`.
  - **Call B** (`:304-343`): ETL script prompt through `call(task_type="code_generation")`. Accepted only if it is longer than 300 chars and passes `ast.parse`. Otherwise `_FALLBACK_MIGRATE_PY`, a stub that migrates 0 rows.
  - `04_validate.py` is always the stub template (`:346`, `_FALLBACK_VALIDATE_PY`, no checks). The rollback SQL is a TRUNCATE template; README is a template.
- **Outputs:** `migration/01..05 + README.md`, `data_archaeology.json`. Metadata `tables_mapped` → context `migration_tables_mapped`.

### p00c_architecture_planner (live, s01 parallel group, effectively always skipped)
- **Input:** `build_profile` (dict) `.architecture/backend_lang/backend_framework/name/performance_tier`, plus `domain`, `raw_input`.
- **Skip rule.** Returns skipped unless `architecture == "microservices"` (`task_agent.py:38-49`).
- **When it runs:** `SERVICE_MAP_PROMPT` through `call_json` (`:72`), then `validate_service_map` (langs, comms, ports ≥1024 and unique, bus). Falls back to `build_fallback_service_map` (auth-service:8001, app-service:8002) with `confidence=0.0`.
- **Output:** `service_map.json`. The hook `hook_load_architecture_planner` (`phase_hooks_helpers.py:78-98`) loads it into `accumulated_context["service_map"]` when it has services. The docstring claims factory_pipeline reads it.

### p01_intake_requirements (live, s01 sequential, CRITICAL)
- **Runs on a deep-copied clone** (`s01:134`). Mutations merge back with `input_data.update` (`:160`).
- **Inputs:** `raw_input` / `requirements`, `domain`, `autonomous_mode` / `decision_mode`, `org_id`, `memory_ctx`.
- **Prompt context:**
  - `core.domain_knowledge.loader.build_prompt_prefix(domain)`
  - KG hints from `core.knowledge_graph_integration.get_similar_entity_patterns(domain, 3)` (`task_agent.py:28-36`)
  - `phases.utils.memory_hint`
- **The LLM call.** One combined `llm.call_json(task_type="analysis")` with a 90 s `asyncio.wait_for` (`:49-102`). It returns `{intake, contract, requirements}`:
  - intake: project_name, domain, summary, app_tagline, key_features, target_users, complexity, requires_landing_page, realtime_requirements
  - contract: user tier, sensitivity, SLA, needs_mobile, handles_money, geo, multi_tenancy, audit_log, tenant_isolation_model
  - requirements: functional/non-functional requirements, entities[], user_roles, user_personas[], api_endpoints[], tech_constraints
- **Deterministic post-processing:**
  - Contract defaults: `soft_deletes`, `rate_limiting`, `pagination_required` = True (`:150-169`).
  - Regulated data or money forces audit_log and multi_tenancy on (`:182-184`).
  - Multi-tenancy is also forced on for B2B domains, any customer persona, or B2B keywords (`:188-205`).
  - `tenant_isolation_model` comes from the LLM, else `org_id_filter` / `none` (`:209-218`).
  - `gate_engine.record_architectural_decisions` writes `decisions` entries through `core.context_helpers.record_decision` (`gate_engine.py:17-82`).
  - `integration_flags` from keyword matching (`:243-251`).
- **Intent verification** (`gate_engine.py:85-154`). Sets an ambiguity flag (<30 words or 0 entities), then makes a second LLM "YES/NO" check through `_llm_iv.complete(...)`. `LLMClient` has no `complete` method, so this raises `AttributeError` and the check never runs.
- **Confidence:** 0.4 on fallback, 0.92 for 4+ entities, 0.75 for 2+, otherwise 0.55 (`:313-328`).
- **Entity approval gate (human-in-the-loop)** (`gate_engine.py:157-243`). Triggers if not autonomous and (confidence < 0.65 or ambiguity) and a run_id exists. It publishes `PhaseApprovalRequired` (gate=entity_approval) and awaits the decision. Approved with text replaces entities with `{name, table}` stubs and sets confidence to 0.80. It checks `status == "rejected"`, but the engine only emits `approved` / `denied` / `timeout` (`core/decisions/decision_engine.py:40,121`). So a denial is silently ignored and the pipeline continues.
- **Fallback.** If the LLM fails: `intake={"project_name":"App",...}`, requirements = the first 500 chars of input, no entities. The s01 gate then fails on missing `entities` (`s01:208-216`) and the pipeline aborts, since s01 is in `CRITICAL_PHASES`.
- **Outputs:**
  - Files: `requirements.json` (summary plus `artifacts`), `requirements.md`, `project_contract.json`.
  - Context: `entities`, `api_endpoints`, `user_personas`, `user_roles`, `app_tagline`, `requires_landing_page`, `realtime_requirements`, `tenant_isolation_model`, `project_contract`, `integration_flags`, `intent_ambiguity`, `decisions[...]`, plus any intake keys not already set (`:107-110`).
- **Downstream:** `spec_critique.critique_spec` runs after s01 from `_hook_p01_intake` (`orchestrator/phase_hooks.py:193-208`) when not autonomous.

### p01b_integration_discovery (live, s01 sequential, non-critical)
- **Inputs:** `raw_input`, `domain`, `project_name`. Skips if `raw_input` is empty.
- **LLM call:** one inline prompt (with `_INTEGRATION_CATEGORIES`) through `call(max_tokens=1500)`, then regex fence strip and `json.loads` (`task_agent.py:75-123`). Returns `integrations[{name, type, auth_method, endpoints_needed, sync_direction, priority}]`.
- **Output:** `integration_map.json`. Metadata `integration_map` and `integrations_count` merge into context. The hook `hook_load_integration_discovery` reloads it.
- **Consumers:** p04c integration codegen, `phase_dag`.

### p02_architecture (live, s02 step 1, non-critical in s02)
- **Inputs:**
  - `raw_input`, `requirements_doc` / `structured_requirements`, `domain`
  - `tech_preferences`, `designer_spec`, `existing_schema`, `build_profile`, `domain_knowledge`
  - `run_id`, `org_id`, `memory_ctx`
- **Flow** (`task_agent.py:30-390`):
  1. **Cache.** `core.spec_cache._CACHE_DIR/{run_id}.json` hit → reuse (`:63-70`).
  2. **RAG.** `core.artifact_store.get_artifact_store().search(...)` returns two reference architectures (`:76-88`).
  3. **Stack hint.** Built from the user preferences, existing tables, `build_profile` fields, and `load_pack(domain).schema_hints()` (`:96-126`).
  4. **Prompt.** `build_arch_prompt` (`prompts.py:12-45`) with the `core.domain_engine.get_domain_profile` fields.
  5. **LLM call.** `llm.call_structured(prompt, schema_example, task_type="architecture")` with a 120 s timeout (`:157-164`).
  6. **Gap-fill.** If tables < 80% of `extract_spec_nouns`, the code appends `{noun}s` tables (`:170-186`).
  7. **Fallback merge.** `build_fallback_architecture` merges in on failure or when endpoints are empty (`:194-200`). It uses canonical schemas for saas, healthcare, fintech and ecommerce, otherwise keyword resources (`helpers.py:216-424`).
  8. **Tech stack.** `fix_tech_stack`, then the user overrides; the domain is preserved.
  9. **Compatibility checks** (`:220-268`): SQLite with multi-tenancy, SaaS without tenancy, SQLite in production. Results go to `architecture_warnings` plus a decision.
  10. **Writes** `architecture.json` / `.md` and records decisions: `database`, `backend_framework`, `frontend_framework`, `auth_method`, `multi_tenancy_strategy`, `api_style`, `deployment_target` (`:281-352`).
- **Outputs.** s02 sets `p02_architecture_path` and `architecture_json` (`s02:108-119`). `_hook_p02_architecture` reloads it and builds the knowledge graph.
- **Note.** The p02 failure-detection bug (§7.1) means the fallback path is effectively unreachable when the LLM fails.

### p02b_domain_ir (live, s02 step 2, CRITICAL)
- **Inputs:**
  - `raw_input` (else the file at `requirements_path`)
  - `architecture_output` (str or dict), else `p02_architecture_path`, else `../p02_architecture/architecture.json`
  - `app_name` / `project_name`, `phase_input.domain`
- **Seeds.** `_seed_entities` turns architecture tables (minus `users`) into PascalCase names, filtered by `_GARBAGE_ENTITY_NAMES` (`ir_extractor.py:263-277`).
- **Extraction.** `run_4pass_extraction` (`ir_extractor.py:435-566`) makes **4 sequential `llm.call(task_type="analysis")` calls**:
  - PASS1: entities and fields, plus KG/RAG context from `core.llm.retrieval_ranker.retrieve_for_phase` and `context_compressor.compress_context` (`:417-432`)
  - PASS2: relationships
  - PASS3: rules, permissions, workflows, KPIs, notifications
  - PASS4: consistency review, returning the full IR plus clarifying questions; falls back to the interim merge
  - `_extract_json` does a 3-stage parse.
  - The task_agent comments (`task_agent.py:94-100,109`) and the extractor's module docstring wrongly describe this as a single combined call. `_COMBINED_PROMPT_TEMPLATE` (`:392-414`) is unused.
- **Stub.** If there are no entities, `build_stub_ir(app_name)` creates one entity from the app name.
- **Assembly.** `_build_ir_from_passes` treats PASS4 as authoritative and fills from passes 1–3 (`:284-385`), producing a `core.domain_ir.DomainIR` with IREntity, IRField, IRRelationship, IRBusinessRule, IRPermission, IRWorkflow, IRDashboardMetric, IRNotification and IRClarifyingQuestion. Unknown field types are coerced to `string`.
- **Clarifying questions.** Any field with confidence < 0.6 adds one (`task_agent.py:122-136`). They are not surfaced to a human here.
- **Validation:**
  - `validator.apply_validation_to_run` runs D1–D7 (`validator.py:175-284`). Fatal on "0 entities" or "circular FK", which returns `success=False` and makes s02 abort the pipeline (`s02:136-147`). The other errors and warnings go to `generation_warnings`.
  - Then `core.ir_validator.validate(ir, fix=True)`.
  - Then a hard `ValueError` if no entities.
- **Outputs:** `domain_ir.json` (`ir.save`). Metadata includes `entity_count`, `field_count`, `relationship_count`, `metric_count`, `domain_validation` and `domain_ir_path`. s02 sets `domain_ir_path` and bubbles up the counts (`s02:149-156`); `hook_load_domain_ir` loads it for codegen.

### p02c_permission_modeling (live, s02 step 3, non-critical)
- **Inputs:** entities from `domain_ir_path`, else `architecture_json.database_schema`; also `domain`, `project_name`, `raw_input`.
- **Flow.**
  - Builds `_build_default_model(entities)` with roles SuperAdmin, Admin, Manager, Staff, ReadOnly; graded CRUD; and a Manager row filter on `created_by` (`task_agent.py:41-58`).
  - Sends the inline ABAC prompt through `call(max_tokens=2000)` (`:120-156`).
  - Runs the result through `_validate_permission_model` (`:61-70`). Because of the validator bug (§7.2) the default model is always used.
- **Output:** `permission_model.json` → `input_data["permission_model"]` (`s02:167-170`) and `hook_load_permission_model`. Consumed by `p04a_backend_codegen/helpers_permissions.py`.

### p03_scaffolding (live, s02 step 4, non-critical)
- **Inputs:** `architecture_json.tech_stack`, `project_name` (else `project_id`), `domain`, `github_url`.
- **Flow:**
  - If `github_url` is set: `git clone --depth=1` with no URL validation (`task_agent.py:438-462`).
  - Otherwise `create_minimal_scaffold` (`:241-418`), which writes:
    - the `src/{api,models,services}` package dirs and domain-specific dirs
    - a FastAPI `main.py` with lifespan, CORS `*` and `/health`, copied to both the root and `src/`
    - `requirements.txt`, `.env.example` / `.env.dev` / `.env.prod` with random `token_hex` secrets, `.gitignore`, README
    - `git init`, devcontainer, and a Postgres `docker-compose.yml`
  - `_write_scale_architecture` adds a Redis `cache_service.py` and a Redis compose service (`:116-238`).
  - Every `.py` file gets an `ast.parse` check. A failure triggers one LLM correction through `call(task_type="code_generation")` (`:19-73,480-496`). Since the files are fixed templates, this almost never fires.
  - Records the decision `scaffold_pattern` (monolith or microservices).
- **Output:** project dir → `input_data["project_scaffold"]`. A non-FastAPI backend gets only a comment-only `main.py`, which would still pass the dead gate.

### p04_uiux_design (DEAD)
- `task_agent.py:13-118` would ask `call_json` for a design spec with colors, typography, components, pages and quality requirements, and propagate `design_tokens`, `css_custom_properties` and `ui_pages`.
- Not invoked by any stage. The docstrings call it "P04b".

---

## 4. Control flow and data flow

```
factory_pipeline (DAG waves over PHASE_SEQUENCE = s01..s12)
 └─ s01_intake (CRITICAL)
     ├─ gather[ p00_research ‖ p00b_data_archaeology ‖ p00c_architecture_planner ]  (shared phase_input; p00c reads build_profile BEFORE p00 writes it)
     │    metadata merged by _METADATA_TO_CONTEXT_MAP (s01:234-263)
     ├─ p01_intake_requirements (clone → update back)   → entities, project_contract, personas, roles, decisions
     ├─ p01b_integration_discovery (clone)             → integration_map
     └─ stage gate: entities + project_contract present
   factory: merge stage metadata (=whole input_data) into accumulated_context (factory_pipeline.py:629-632)
   hooks (phase_hooks.py:56-65): _hook_p01_intake (spec_review_gate → spec_critique), hook_load_research
       (build_profile dict + domain_knowledge from design_brief.json), hook_load_architecture_planner (service_map),
       hook_load_integration_discovery
 └─ s02_architecture (CRITICAL)
     ├─ p02_architecture → architecture.json → input_data[architecture_json, p02_architecture_path, architecture_warnings, decisions]
     ├─ p02b_domain_ir (CRITICAL) → domain_ir.json → input_data[domain_ir_path, entity_count, …, generation_warnings]
     ├─ p02c_permission_modeling → permission_model
     ├─ p03_scaffolding → project_scaffold
     └─ stage gate: domain_ir.json non-empty with entities
   hooks: _hook_p02_architecture (architecture_json + KnowledgeGraph build), hook_load_permission_model, hook_load_domain_ir
 └─ s03_backend / s04_frontend … read domain_ir(.json), permission_model, integration_map, build_profile, decisions, project_scaffold
```

- **Into codegen:**
  - `domain_ir.json` is the contract for p04a/p04b/p05.
  - `build_profile` (dict) drives stage routing: s04 mobile/desktop/cli/serverless, s09, s10, s12.
  - `decisions` (backend_framework, database, auth_method, multi_tenancy_strategy, tenant_isolation…) are meant to keep the stack consistent across p04a→p04b→p06.
  - `permission_model` feeds `helpers_permissions.py`, and `integration_map` feeds p04c.
- **p04b recovery path.** It tries to import `_PASS1_PROMPT`, `_PASS4_PROMPT` and `_extract_json` from `p02b_domain_ir.task_agent` (`phases/p04b_business_logic/helpers.py:236-241`). Those names live in `ir_extractor.py` and are not re-exported, so this is an ImportError path.
- **`decisions` store:** `core.context_helpers.record_decision(input_data, key, value, reason, phase)` is used by p01, p02 and p03.

---

## 5. Plane mapping

| Plane | What this section contributes |
|---|---|
| **SDLC** | The full front half: research/classification (p00), legacy schema migration (p00b), service decomposition (p00c), requirements/PRD and project contract (p01), integration discovery (p01b), architecture and tech decisions (p02), canonical domain model (p02b), authorization model (p02c), repo scaffold (p03). The decision log provides architectural traceability. |
| **STLC** | Requirement-quality checks only: spec_critique (testable acceptance criteria, error cases), intent ambiguity flag, D1–D7 IR validation, ast checks in p00b and p03. Phase gates exist but are unused at runtime. p04_uiux would have required per-page test files (dead). |
| **SRE** | Tech hints only: `availability_sla`, `user_count_tier`, `geographic_scope` in the contract; `deployment_target` decision; Redis cache and pg healthcheck in the compose file; p00b rollback SQL. No runtime SRE logic. |
| **Compliance** | `domain_knowledge` packs (entities, compliance rules) injected into the brief and the p01/p02 prompts. `data_sensitivity=regulated` or money forces `audit_log=True`. Domain profile `security_requirements`. Business model `compliance_requirements`. Healthcare and fintech fallback schemas (audit_logs, kyc_status). No HIPAA/GDPR enforcement here. |
| **Security** | p02c ABAC model: roles, row_filters, field_masks for salary/ssn/password_hash (LLM output always discarded). Tenancy isolation model. Security considerations in architecture. Generated scaffold has CORS `*`, random env secrets, `.env*` gitignored. Unvalidated `git clone` of `github_url`. |
| **Deployment** | Build profile `deployment_target` (docker/kubernetes/serverless). Scaffold `docker-compose.yml` (Postgres 16 + Redis 7), devcontainer, `.env.prod` template. |
| **Admin control** | Human-in-the-loop decision gates: p00 Gate 1 (design brief approval with JSON overrides) and p01 entity-approval gate, both through `core.decisions.decision_engine` with a `PhaseApprovalRequired` event. Bypassed by `autonomous_mode` / `decision_mode=autonomous` (p00 also honours env `AUTONOMOUS_MODE`; p01 does not). After the stage, `spec_review_gate`. |
| **API management** | p01 `api_endpoints`, p02 `api_endpoints` (method, path, auth flag) and the `api_style` decision (rest/graphql). p01b external API contracts (auth_method, endpoints_needed). p00c API gateway (nginx) and per-service ports/protocols. |
| **Other (product/business)** | `business_model.json` (TAM/SAM/SOM, pricing tiers, GTM, unit economics). Competitor design research with screenshots plus vision. Multimodal intake (Figma, diagram, voice). |

---

## 6. Interfaces and dependencies

- **`core.llm.client.LLMClient` / `get_llm_client`.** Tiered providers: Anthropic → Gemini → Ollama (`client.py:101-121`).
  - `call` is used by p00 business model and audio, p00b, p01b, p02b, p02c, p03 repair and spec_critique.
  - `call_json` (3 attempts, raises `LLMCallError`) is used by stack_selector, p00 fallback, p00c, p01 and p04_uiux.
  - `call_structured` (single attempt, returns the schema on failure) is used by p02.
  - `call_vision` (Bedrock) is used by the vision analyzer and the diagram parser.
  - `safe_parse_json` is imported by `vision_analyzer.py:37` from `client` (re-exported at `client.py:49`).
- **`core.stack_profiles`:** `StackProfile` (build_type, architecture, backend_lang/framework, frontend_framework, db_primary, deployment_target, performance_tier…), `get_profile`, `profile_to_dict`, `DEFAULT_PROFILE`.
- **`core.domain_knowledge.loader`:** `load_pack(domain)` with `.to_dict()` / `.schema_hints()` / `.entities` / `.compliance`; `build_prompt_prefix(domain)`.
- **`core.domain_engine.get_domain_profile`:** name, preferred_db, suggested_tech_stack, required_patterns, security_requirements, example_entities. Note that `general`, `saas`, `crm` and `restaurant` suggest **SQLite** (verified).
- **`core.domain_ir`:** the DomainIR dataclasses and `AetherType` (12 canonical types → SQLAlchemy/TS/Zod/OpenAPI); `DomainIR.save` / `load`. **`core.ir_validator.validate(ir, fix=True)`.**
- **Knowledge graph and RAG:**
  - `core.knowledge_graph_integration.get_similar_entity_patterns` → `core.knowledge_graph.KnowledgeGraph.load_for_domain` (p01)
  - `core.llm.retrieval_ranker` and `core.llm.context_compressor` (p02b)
  - `core.artifact_store` `search` / `get_artifact` (p02)
  - `core.spec_cache._CACHE_DIR` (p02)
- **Decisions and events:** `core.decisions.decision_engine` (`Decision`, `get_decision_engine`, `request_approval`, `await_decision`; statuses pending, approved, denied, timeout), `core.pipeline_state.publish_event`, `orchestrator.events.ACTIVE_RUN_ID`, `core.errors.PipelineBlockedError`.
- **Context and memory:** `core.context_helpers.record_decision`, `phases.utils.memory_hint`, `core.projects.get_project_manager().get_output_dir`.
- **Database:** `core.db.get_session_factory` and `core.models.Run` (domain, checkpoint_data) in p00b.
- **External:** Screenshotone API, Playwright (optional), OpenAI Whisper, `git` CLI, httpx.

---

## 7. Reality check

**Verified defects**
1. **p02 cannot detect LLM failure** (`task_agent.py:146-166`).
   - On any failure, `call_structured` returns `schema_example` (`core/llm/client.py:371-374`).
   - The caller detects failure with `doc.get("tech_stack") == ARCHITECTURE_SCHEMA["tech_stack"]`. But `schema_example["tech_stack"]` is overwritten with `{**TECH_STACK_DEFAULTS, **profile.suggested_tech_stack}` (`:148`), which **never** equals the original for any domain profile. Verified for general, saas, ecommerce, healthcare, fintech, crm and restaurant: every comparison returned `False`.
   - So an LLM outage yields the generic `users` + `/items` CRUD schema with `used_fallback=False` and confidence 0.9. The domain-aware fallback (`helpers.py:216`) is never reached, because the endpoints are non-empty.
   - The gap-fill then adds noun tables with only `id`, `name`, `description` and `created_at`.
2. **p02c always discards the LLM model** (`task_agent.py:61-70`).
   - The validator requires `roles` to be dicts with `name` and `permissions` to be a **list**. The prompt (`:130-146`) asks for a list of role strings and a permissions **dict**.
   - Verified: prompt-conformant output gives 3 validation errors, so `_build_default_model` is always used. The LLM tokens are wasted, and row_filters and field_masks are never domain-specific.
3. **p02b can crash the critical stage.**
   - `IRWorkflowStep(**s)` (`ir_extractor.py:352`) raises `TypeError` if the LLM adds any extra key to a step (for example `description`). Likewise `float(f.get("confidence"))` on a null confidence (`:318`). Neither is caught, so p02b raises and s02 aborts the pipeline.
   - The D2 rule treats **any** FK cycle (for example `Department.head_id→Employee` plus `Employee.department_id→Department`, a very common pattern) as fatal (`validator.py:332`).
   - The validator also runs on `combined_result = p1`, the pass-1 dict (`task_agent.py:109,140`), not on the PASS4-corrected and garbage-filtered IR that is actually saved. Its D7/D1 errors may therefore describe a different IR.
4. **p00 missing imports:**
   - `async_playwright` is never imported (`task_agent.py:56`). The `NameError` is caught at `:71`, so the Playwright fallback never works.
   - `get_llm_client` is never imported (`:161`). The `NameError` is caught at `:166`, so the LLM design-brief fallback never runs.
   - Without `SCREENSHOTONE_API_KEY`, `design_brief` is therefore always `{"navigation":"sticky"}` with empty features.
   - Even with screenshots, `VISION_PROMPT` does not request the `layout_patterns`, `must_have_features` or `color_scheme` keys that synthesis reads (`:149-151`).
   - `raw_spec` is recomputed at `:104`. This is harmless only because multimodal intake writes `raw_input` into `data`.
5. **p01 gate_engine:**
   - `_llm_iv.complete(...)` (`gate_engine.py:139`): `LLMClient` has no `complete` method (verified with grep on `core/llm/client.py`), so intent verification is silently a no-op.
   - The entity gate checks `resolved.status == "rejected"` (`:235`), but the engine emits `denied`. A user rejection is ignored.
   - p01 ignores the `AUTONOMOUS_MODE` env var that p00 honours, so the gate can block in env-autonomous runs.
6. **p00c is always skipped on fresh runs.** It runs in the same `gather` as p00 and reads `build_profile` at start. p00 publishes `build_profile` only after it finishes, and then only as a **string** (`task_agent.py:252`). On a stage retry where `input_data` still holds that string, `build_profile.get(...)` raises `AttributeError`. The dict form arrives only through the post-stage hook.
7. **p04_uiux_design** is never invoked, so no design tokens or `ui_pages` reach p05. Its gate is also broken:
   - `any(k in issues for k in ["No pages", ...])` tests list membership of a prefix, so it is never true.
   - `Path("")` resolves to `.` and "exists", so a missing `json_path` falls into the "not JSON → pass 0.5" branch (verified).
8. **Phase gates and supervisors are dead at runtime.**
   - The p01 gate's `structured_requirements` promotion, documented in `ARCHITECTURE.md:83` and `README.md:57`, never runs.
   - It also targets `intake/intake.json`, which p01 never writes. So does `_hook_p01_intake` (`orchestrator/phase_hooks.py:172`), which makes that project_name update dead too.
9. **p04b broken import:** `from aether_os.phases.p02b_domain_ir.task_agent import _PASS1_PROMPT, _PASS4_PROMPT, _extract_json` (`phases/p04b_business_logic/helpers.py:236`). Those symbols live in `ir_extractor.py`.
10. **p02 `extract_resources` uses substring matching** (`helpers.py:179-182`). Verified: "Prevent bordering issues; leading accounts" gives `orders, events, leads, accounts`. `extract_spec_nouns` likewise turns arbitrary 4+ letter words from the first 40 lines into "entities" for gap-fill.
11. **p03 security and robustness:**
    - `github_url` is cloned without scheme or host validation (`task_agent.py:438-447`).
    - `project_name` is unsanitized in `output_dir / project_name` (`:252`), a path-traversal risk if it comes from LLM or user input. The `_join_safe` guard exists only in the dead `generators.py`.
    - The generated app uses `allow_origins=["*"]`.
12. **p00b quality:**
    - `04_validate.py` is always the empty stub.
    - The fallback `03_migrate.py` migrates 0 rows and reports `status: complete`.
    - `similar_past_runs` mining runs only when a schema is uploaded, despite the s01 docstring.

**Dead code** (verified with grep; no runtime importers):
- `p02_architecture/onboarding.py` (580), `monorepo.py` (466) and `agents.py`
- `p03_scaffolding/generators.py`, `generators_helpers.py`, `prompts.py` and `agents.py`
- `p02b ir_extractor._COMBINED_PROMPT_TEMPLATE`
- All 10 `supervisor_agent.py` files plus `p02b/__init__.DomainIRSupervisor`
- All `gate.py` files (p00, p01, p02 and p03 gates are reached only from `tests/test_phases.py`)
- All of `p04_uiux_design/`

The onboarding, monorepo, generators and prompts modules are Aether-One legacy (they reference `aetherone/`).

**File size.** Nothing in scope exceeds 600 lines. The largest are `ir_extractor.py` (593), `onboarding.py` (580), `p03 task_agent.py` (548) and `monorepo.py` (466). `p03 task_agent.py` (548) violates the CLAUDE.md target that `task_agent.py` should be orchestration only and under 300 lines, because it embeds templates.

**Doc vs code gaps:**
- `ARCHITECTURE.md:98` and `README.md:67` say p03 uses cookiecutter templates. No cookiecutter code exists: the metadata carries `used_cookiecutter: False`, and the docstring still claims it.
- `ARCHITECTURE.md:94` says the p02b gate checks a compliance profile. The code does not.
- `ARCHITECTURE.md:184` says SQLite is the default. The p03 compose file is Postgres, `.env.dev` is SQLite, and the domain profiles suggest SQLite for general and saas.
- `README.md:49` lists `p00a_intake` (multimodal). It is actually `p00_research/multimodal_intake.py`; p00a is listed as deleted in `phase_sequence.py:49`.
- The s02 docstring says roughly 3 LLM calls. In practice p02 makes 1, p02b makes 4, p02c makes 1 (wasted) and p03 makes 0–N repairs.
- `stack_selector.py:5` and `p00c task_agent.py:11` say "factory_pipeline.py propagates". It is actually `phase_hooks_helpers.py`.
- The p02b comments describe a single-call extraction. The code makes 4 calls.

---

## 8. Open questions

1. Is p04_uiux_design meant to be wired into s04_frontend? p05 currently gets no `ui_pages` or `design_tokens` from it. Whether s04 or p05 reads `designer_spec` directly is outside this section.
2. Should p00c run after p00 (sequentially) so that microservice builds actually get a `service_map`? Or is `build_profile` expected to arrive in `input_data` for resume runs only?
3. Is the p02 failure-detection bug masking LLM outages in production metrics? The `phase_confidence` trail would show 0.9.
4. Is D2 (any FK cycle is fatal) intentional, given that it blocks common bidirectional domains? Should cycles be downgraded to warnings with a nullable-FK auto-fix?
5. Which p02c schema is canonical: list-of-dict roles plus list permissions (validator), or string roles plus dict permissions (prompt and default model)? `p04a/helpers_permissions.py` should be checked to see which shape it consumes.
6. Are clarifying questions from p02b (`ir.clarifying_questions`) surfaced to any UI or decision gate downstream?
7. Does `spec_review_gate`'s improved spec feed back into p02, given that p02 runs in s02 after the hook? `_run_spec_critique` reads `p01_intake_requirements_output`, which the factory never sets because it keys on stage names.
