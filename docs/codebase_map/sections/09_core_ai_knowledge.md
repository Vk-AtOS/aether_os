# 09_core_ai_knowledge — Core AI, knowledge, memory, learning, council, and quality plane
Scope: core/llm/, core/model_router*.py, core/prompt_compiler.py, core/domain_engine.py, core/domain_ir.py, core/ir_validator.py, core/domain_knowledge/, core/domain_packs/, core/knowledge_graph*.py, core/knowledge_graph/, core/memory/, core/project_memory.py, core/learning/, core/repair_learning.py, core/intelligence/, core/vector_store.py, core/spec_cache.py, core/stack_profiles.py, core/council/, core/decisions/, core/quality/, core/quality_monitor.py, core/questionnaire/, core/constraint_engine.py, core/architecture_governor.py, core/stage_feedback.py, core/schema_importer.py
About 16.3K Python LOC in 96 .py files, plus about 33K lines of golden-example JSON · Commit 052a101 · Mapped 2026-11-08 · Read-only pass: every .py file read in full. The JSON corpora were summarised by parsing them. Every DEAD verdict was checked by grepping callers (the .venv is excluded).

Status tags: **REAL** = deterministic logic that does what it says · **LLM-DRIVEN** = the output comes from an LLM call · **TEMPLATE** = static data or string templates · **STUB/HOLLOW** = a thin wrapper or fail-open placeholder · **DEAD** = nothing in production imports it.

---

## 1. Summary

- **One LLM entry point.** `LLMClient.call(prompt, task_type, context, system, max_tokens, org_id, plan, run_id, phase, attempt, temperature) -> str` (core/llm/client.py:123-136). It delegates to `ModelRouter.call()` (core/model_router.py:75), which runs a semantic cache → token budget gate → env-built fallback chain → org DB overrides → reorder by AHM health → filter by trial plan → per-model retry or fallback loop with a LangSmith span around each attempt.
- **Providers in code:** AWS Bedrock (Converse API; Nova Pro or Llama 3.3 70B by default), Anthropic (direct, or an Anthropic-compatible base URL), Google Gemini (google-genai), OpenRouter (an OpenAI-compatible REST endpoint; free `:free` models), and Ollama (local HTTP). There is **no direct OpenAI SDK**; OpenAI models are reachable only through OpenRouter slugs. AirLLM is mentioned in a docstring (client.py:12) but is not implemented.
- **Default production chain** (`PRIMARY_LLM` defaults to `bedrock`): `bedrock/us.amazon.nova-pro-v1:0` → `bedrock/us.meta.llama3-3-70b-instruct-v1:0` → anthropic and gemini (only if keys exist) → OpenRouter models (only if configured) → `ollama/qwen2.5-coder:3b` (model_router_providers.py:87-163). Each provider gets 1 attempt and a 60 s timeout. `OFFLINE_MODE=true` limits the chain to Ollama.
- **Critical bug: the router's Anthropic tier is broken.** `_call_provider` passes `client` as an extra positional argument to `_call_anthropic(prompt, task_type, system, max_tokens)` (model_router.py:465-468 vs providers.py:72-77). Every call raises `TypeError: multiple values for argument 'system'` (verified with inspect), gets classified as "fallback", and AHM degrades the anthropic provider. Tests hide this because they patch `_call_anthropic` with an AsyncMock (tests/test_model_router.py:185, tests/test_llm.py:82).
- **`temperature` is never applied.** The client forwards it only if the router's signature has that parameter, and it does not (verified). No provider adapter accepts temperature either. `core/llm/phase_config.py` (per-phase temperatures) has no importers: **DEAD**.
- **Cost tracking is spread across 5 places and uses inconsistent price tables.** (1) The client's per-call `_BEDROCK_PRICING` → `pipeline_runs.cost` + `org_llm_usage` (client.py:184-289). (2) The router's `_COST_PER_1M` per provider → billing ledger (model_router.py:299-321). (3) `TokenBudgetManager.record_usage` → `token_budget_records`, called up to twice per call (model_router.py:278-352). (4) `_call_bedrock` sends a second billing record with `cost_usd=0.0` (providers.py:398-407). (5) The in-process `_cost_registry` (token_counter.py:19). Tokens are estimated as `len/4` everywhere except the Bedrock and Anthropic provider counters. Each call also writes an `LLMTrace` row (token_counter.py:41-78).
- **There are 4 separate "council" mechanisms, all LLM-driven with static extras.**
  - PreFlightCouncil and DeliveryCouncil each make one JSON verdict call through LLMClient (council.py:142, 503).
  - BackendAuditCouncil runs 4 narrow PASS/FAIL prompts that rotate across 6 OpenRouter free models, with Bedrock as the last fallback, plus regex static security checks (council.py:182-373).
  - `run_council` sends 3 parallel persona reviews (Claude security, Gemini architecture, Ollama performance). Each falls back to Bedrock. A word-overlap heuristic builds consensus, and static checks are merged in (council_reviewer.py:454-512).
  - FrontendAuditCouncil is **DEAD** (no callers).
  - The default mode is advisory. `COUNCIL_STRICT_MODE` defaults to true only when `ENVIRONMENT=production` (council.py:106-116).
- **Memory uses five unconnected stores, none of them pgvector-backed in practice.**
  - The SQLite+FTS5 `MemoryStore` (~/.aether_os/memory.db).
  - Per-"org" ChromaDB collections (~/.aether_os/chroma_memory, built-in MiniLM embeddings).
  - A SQLite project fingerprint DB.
  - A NetworkX per-run graph.
  - A JSON-file KnowledgeGraph.
  - `core/vector_store.py` (pgvector adapter) is **DEAD**. `LLMClient.embed()` (Bedrock Titan → Ollama → zero vector) has one caller, core/artifact_store.py.
  - Bug: `BasePhase.memory_before` reads `r.confidence`, which `MemoryRecord` does not have, so the AttributeError is swallowed and the method always returns `[]` (phases/base.py:59-62 vs memory/store.py:30-42).
  - Bug: Chroma is written with `org_id=domain` (phases/base.py:118-125), which breaks the tenant partitioning model.
- **The learning loop is mostly template-driven and partly hollow.**
  - (a) `repair_learning.learn_from_repair` writes a **templated** validator .py file for 8 fixed bug classes, one new file per repair event, into the source tree.
  - (b) `load_validators()` wraps those validators so `check(source)` returns `[]` (repair_learning.py:520-526). p04a's "learned validators" pass (codegen_orchestrator.py:271-283) therefore can never flag anything.
  - (c) `golden_retriever` promotes runs with an average user rating ≥ 4.0 to the `GoldenBuild` table and injects excerpts into p04a and p05 prompts (REAL).
  - (d) `stage_feedback` is an append-only JSONL log inside the source tree.
  - (e) The KnowledgeGraph saves the domain IR per domain to ~/.aether_os/knowledge_graphs.
- **Domain knowledge lives in 5 overlapping, partly contradictory systems:**
  - `domain_engine.DOMAIN_PROFILES` (9 profiles)
  - `domain_knowledge/packs` (12 rich packs: entities, workflows, compliance, BPM pipelines)
  - `domain_packs` (10 packs: constraints, integrations, seed patterns)
  - `ConstraintEngine` verticals and compliance rules
  - `council_reviewer._DOMAIN_RULES`
  - Example conflict: domain_knowledge fintech stores `balance_cents int`, while domain_packs fintech and ConstraintEngine say "never store balance" and require `Numeric(18,6)`.
  - Example conflict: the KG seed rule says "routers/__init__.py with `from .X import router`" (relative import, knowledge_graph_seeds.py:54), while ConstraintEngine says absolute imports only and `all_routers` belongs in crud.py.
- **The quality critics are REAL static analysis** (AST and regex), with two notable bugs.
  - Frontend dimensions (`typescript_types`, `frontend_a11y`, `frontend_correctness`) are missing from `DIMENSION_WEIGHTS`. Every .ts/.tsx/.js/.jsx file therefore scores overall=0.0 and fails (verified).
  - `metrics.score_project` computes `test_score` but leaves it out of `total`. It also counts *any* `Depends()` (including `get_db`) as auth.

---

## 2. Coverage table

| File | LOC | Purpose | Status |
|---|---|---|---|
| core/llm/__init__.py | 19 | Re-exports LLMClient, get_llm_client, safe_parse_json, json helpers | REAL |
| core/llm/_org_context.py | 21 | ContextVars `_current_org_id`, `_active_provider` | REAL |
| core/llm/client.py | 555 | LLMClient: call/call_structured/call_json/call_vision/embed, cost persistence, trace | REAL (orchestrates LLM) |
| core/llm/providers.py | 493 | Adapters: Anthropic (prompt caching), Gemini, Ollama (streams to Redis), Bedrock Converse, Bedrock vision | REAL |
| core/llm/model_registry.py | 70 | task_type → heavy/light tiers; per-provider model selection | REAL |
| core/llm/token_counter.py | 78 | `_cost_registry`, `safe_parse_json` (buggy), `_write_llm_trace` → llm_traces | REAL |
| core/llm/phase_config.py | 50 | Per-phase temperature, max_tokens, and tier table | DEAD (no importers; temperature not plumbed) |
| core/llm/ahm.py | 167 | Adaptive Hybrid Mesh: provider health scores with exponential decay (600 s half-life), chain reorder | REAL |
| core/llm/budget.py | 178 | TokenBudgetManager: monthly plan budgets in PG (`token_budget_records`), Haiku downgrade signal | REAL (downgrade signal unused) |
| core/llm/cache.py | 137 | PG exact-match cache keyed by SHA-256(org, task, system, prompt) (`llm_cache_entries`) | REAL ("semantic" is a misnomer) |
| core/llm/compressor.py | 140 | Compresses prompts over 6K tokens with Haiku or an OpenRouter 3B model (heavy tasks only) | LLM-DRIVEN |
| core/llm/context_compressor.py | 313 | Per-phase interest-key filter and truncation of accumulated_context | REAL |
| core/llm/json_enforcer.py | 148 | extract_json / parse_llm_json / enforce_json_keys | REAL |
| core/llm/openrouter_client.py | 150 | httpx OpenRouter chat/completions; COUNCIL_MODELS list | REAL |
| core/llm/retrieval_ranker.py | 506 | Ranks knowledge from error registry, domain pack, KG, golden JSON, run graph, and warnings | REAL (partly unreachable branches) |
| core/model_router.py | 521 | ModelRouter: cache, budget, chain, AHM, trial filter, retry/fallback, placeholder guard, billing | REAL |
| core/model_router_providers.py | 306 | ModelSpec, get_fallback_chain, error classification, circuit breakers, org DB overrides | REAL |
| core/prompt_compiler.py | 413 | PromptCompiler: sections for constraints, decisions, DO-NOT rules, knowledge, few-shot, task, entities | TEMPLATE (public compile_* methods unused; p04a calls private helpers) |
| core/constraint_engine.py | 251 | Hard-coded rule lists for backend, seed, frontend, verticals, compliance | TEMPLATE |
| core/domain_engine.py | 232 | 9 DomainProfile dataclasses + get_domain_profile | TEMPLATE |
| core/domain_ir.py | 307 | DomainIR dataclasses, AetherType system, SA/TS/Zod/OpenAPI type maps, load/save | REAL |
| core/ir_validator.py | 177 | Rules V1–V9 with auto-fix | REAL (V2 is a self-reference check only; V1 casing-fix branch unreachable) |
| core/architecture_governor.py | 382 | AST and regex check of generated models, routes, and components against the IR | REAL (field check is not scoped to a class) |
| core/stage_feedback.py | 98 | JSONL append log of stage outputs and fixes, failure rate, top issues | REAL |
| core/schema_importer.py | 145 | Reflects a live DB with SQLAlchemy into p02 db_schema; SQLite LFI guard | REAL |
| core/spec_cache.py | 84 | File cache (~/.aether_os/spec_cache, 24 h TTL, max 200) of architecture.json | REAL |
| core/stack_profiles.py | 278 | 17 StackProfile entries (web_saas, go_api, java_enterprise, …) | TEMPLATE |
| core/vector_store.py | 63 | pgvector / JSON embedding adapter (sync; docstring says async) | DEAD |
| core/project_memory.py | 169 | .aetheros/project_memory.json in each generated project; enhance-mode context | REAL |
| core/repair_learning.py | 566 | BugClass → templated validator source → file + JSON metadata; load_validators | TEMPLATE / HOLLOW (check() returns []) |
| core/knowledge_graph.py | 494 | JSON dict graph (node and edge types), singleton seeded from core/knowledge_graph.json; per-domain persistence | REAL |
| core/knowledge_graph_graph.py | 123 | BFS, neighbours, subsystem connection helpers | REAL (the latter two are unused) |
| core/knowledge_graph_integration.py | 67 | save_ir_to_knowledge_graph / get_similar_entity_patterns | REAL |
| core/knowledge_graph_seeds.py | 133 | 10 seed nodes, 8 edges (5 fix→constraint pairs) | TEMPLATE |
| core/knowledge_graph.json | 148 | Persisted seed graph: 10 nodes, 8 edges (same as the seeds) | TEMPLATE (data) |
| core/knowledge_graph/golden_examples/*.json | 32,925 | 13 corpora (counts below) | TEMPLATE (data) |
| core/memory/__init__.py | 1 | package marker | — |
| core/memory/memory_manager.py | 37 | Older duplicate of project_memory (no logging, raises) | REAL (duplicate) |
| core/memory/store.py | 262 | SQLite + FTS5 MemoryStore with org scoping | REAL |
| core/memory/vector_store.py | 141 | ChromaProjectMemory: one collection per org, cosine similarity | REAL (optional dependency) |
| core/memory/fingerprinter.py | 170 | CI log fingerprint; ProjectFingerprinter SQLite (exact hash match, else most-recent fallback) | REAL |
| core/memory/matcher.py | 164 | FailureFingerprint exact/fuzzy patch match; ProjectMatcher | REAL |
| core/memory/graph_rag.py | 266 | Offline repo import and symbol graph (AST) | REAL (rebuilt on every query) |
| core/memory/knowledge_graph.py | 124 | NetworkX DiGraph per run (node-link JSON) | REAL |
| core/learning/__init__.py | 0 | — | — |
| core/learning/golden_retriever.py | 287 | Feedback → GoldenBuild promotion; few-shot hint formatters | REAL |
| core/intelligence/__init__.py | 21 | Exports 6 engines | — |
| core/intelligence/arch_governor.py | 81 | LLM architecture review + audit ledger | LLM-DRIVEN (fail-open "compliant") |
| core/intelligence/truth_engine.py | 89 | LLM requirements-to-code traceability | LLM-DRIVEN |
| core/intelligence/conflict_resolver.py | 75 | LLM requirement conflict detection | LLM-DRIVEN |
| core/intelligence/tradeoff_engine.py | 70 | LLM A-vs-B scoring; `evaluate_run_choices` is a stub | LLM-DRIVEN / STUB |
| core/intelligence/improvement_loop.py | 90 | Run signals → LLM suggestions | LLM-DRIVEN |
| core/intelligence/maintenance_engine.py | 115 | LLM dependency "CVE" scan and tech-debt review; run health check | LLM-DRIVEN (hallucination-prone CVE scan) |
| core/council/__init__.py | 3 | Exports PreFlightCouncil, DeliveryCouncil | — |
| core/council/council.py | 552 | Pre-flight, backend audit, frontend audit (dead), and delivery councils | LLM-DRIVEN + REAL static |
| core/council/council_reviewer.py | 512 | 3-persona parallel review, consensus, static secret/limit/validation checks | LLM-DRIVEN + REAL static |
| core/decisions/__init__.py | 0 | — | — |
| core/decisions/db.py | 3 | Re-exports Base | DEAD |
| core/decisions/decision_engine.py | 297 | Human-approval decisions: DB + Redis pub/sub wait | REAL (timeout bug) |
| core/quality/__init__.py | 6 | Re-exports critic API | — |
| core/quality/dimension_critic_types.py | 42 | Thresholds, weights, dataclasses | REAL |
| core/quality/dimension_critic.py | 239 | critique_artifact / critique_directory | REAL (frontend weighting bug) |
| core/quality/dimension_scorer.py | 504 | 8 Python dimension scorers (AST and regex) | REAL |
| core/quality/dimension_scorer_frontend.py | 181 | 3 TS/TSX scorers (regex) | REAL |
| core/quality/metrics.py | 447 | score_project: auth, validation, tests, seed, frontend build (`npx vite`), bandit | REAL |
| core/quality_monitor.py | 383 | L1–L4 live HTTP probes of the generated app | REAL |
| core/questionnaire/__init__.py | 0 | — | — |
| core/questionnaire/stage_questions.py | 557 | Question definitions for 12 stages (s01–s12) | TEMPLATE |
| core/questionnaire/renderer.py | 393 | Self-contained white-label HTML form + fetch submit | REAL |
| core/domain_knowledge/__init__.py, packs/__init__.py | 0 | — | — |
| core/domain_knowledge/base.py | 254 | FieldDef, EntityTemplate, WorkflowTemplate, ComplianceRule, ProcessStep, BusinessProcessPipeline, DomainKnowledgePack | REAL (ProcessStep and BusinessProcessPipeline each defined twice; the first copy is dead) |
| core/domain_knowledge/loader.py | 102 | Alias map (27 keys → 12 packs), cached importlib loader, prompt helpers | REAL |
| core/domain_knowledge/packs/{ecommerce,edtech,erp,fintech,govtech,healthcare,legaltech,logistics,manufacturing,real_estate,saas,trading}.py | 3,007 | 12 DomainKnowledgePack instances: 5–8 entities, 1–2 workflows, 3–6 compliance rules, 0–2 BPM pipelines each (all import cleanly, verified) | TEMPLATE |
| core/domain_packs/__init__.py | 223 | DomainPack, EntitySpec, IntegrationSpec, 60-key alias map, lazy loader | REAL |
| core/domain_packs/*_pack.py (10) | 2,697 | ecommerce, healthcare, ai_integrated, erp (= traditional_erp), marketplace, saas, fintech, government, social, iot: 6–12 entities, 12–23 constraints, integrations, seed patterns | TEMPLATE |

Golden corpora (`examples` count, type): saas 432, ai_integrated 69, bug_fixes 60 (bug_to_fix), so_bugfix_examples 60, ecommerce 55, government 54, github_entity_patterns 50 (entity_to_sqlalchemy), erp 38, fintech 34, marketplace 30, healthcare 25, traditional_erp 11, sqlalchemy_models 10. Schema: `{id, type, input, output, tags, quality_score}`. Most are `app_description_to_domain_ir`.

---

## 3. Components and how they work

### 3.1 LLM client (core/llm/client.py)
- **`call()`** (123-321):
  1. If `org_id` is set, it looks up `Organisation.data_region`. When the region is `local-only`, it sets `enforce_local` (153-167).
  2. It prepends `Context:\n<json>` when a context is given (169-173).
  3. Unless `enforce_local` is set, it calls `compressor.compress_context`, which compresses with Haiku or OpenRouter when the prompt exceeds 6K tokens and the task is heavy (176-181).
  4. It reads the `_active_provider` ContextVar to pin a provider (204), then calls `router.call(...)` and records `last_provider` and `last_model` (230-234).
  5. It computes cost from `_BEDROCK_PRICING` with suffix matching (default $0.001/1K tokens for OpenRouter) and fires off an async UPDATE of `pipeline_runs.cost` plus an UPSERT into `org_llm_usage` (238-291).
  6. A `finally` block fires off `_write_llm_trace` (302-321).
- **`call_structured(prompt, schema_example, task_type, context)`** makes one attempt. On a parse failure or a failed architecture validation (requires `tech_stack`, `database_schema`, `api_endpoints`, and `tech_stack.{backend, frontend, database}`), it **returns `schema_example`** so the caller's deterministic fallback runs (323-373). Used by p02_architecture.
- **`call_json`** makes 3 attempts with sleeps of 2 s and 4 s, then raises `LLMCallError` (375-402). Used by the intelligence engines and p01. Because each attempt reruns the whole router chain, the worst case is 3× chain latency.
- **`call_vision`** always goes to `_call_bedrock_vision` (404-413).
- **`embed`** tries Bedrock Titan v2 (1024 dimensions), then Ollama `nomic-embed-text`, then returns a zero vector (415-495).
- **`get_llm_client(provider)`** returns either the process singleton or a fresh client whose `call` is wrapped to set and reset the `_active_provider` ContextVar (524-555).
- **`init_org_llm_context`** pre-warms org keys for anthropic, google, and openrouter from `core.api_key_store` (73-81).
- The `is_local_llm()` default is `"ollama"` (86-87), while the router's default is `"bedrock"` (model_router_providers.py:111). The constructor therefore logs an "Ollama fallback" warning whenever `PRIMARY_LLM` is unset, even though the router actually uses Bedrock.

### 3.2 Router (core/model_router.py + model_router_providers.py)
- **Steps:**
  1. Cache GET, for cacheable tasks only. The cache skips `code_generation`, `security_scan`, `testing`, and `architecture` (cache.py:25-27). A hit returns `(text, "cache")` (96-118).
  2. Budget check when both `org_id` and `plan` are present. For trial plans at ≥100% it raises `LLMUnavailable`. At ≥85% it returns `"haiku"`, but **only a log line follows**; no model is actually downgraded (121-136).
  3. `get_fallback_chain()` is rebuilt from env on every call (157). `enforce_local` filters the chain to Ollama only.
  4. A pinned provider is sorted first (162-163). `_apply_org_chain_overrides` drops Bedrock if `LlmConfig.bedrock_enabled=False`, swaps in the org's Bedrock heavy model, and injects Gemini or OpenRouter from org DB keys (model_router_providers.py:247-306).
  5. AHM reorder runs only when no provider is pinned (173-179).
  6. The trial plan keeps only `:free` OpenRouter models, Gemini Flash, Anthropic Haiku, and Ollama (182-204).
  7. The loop skips providers that are unconfigured, `_DEAD_PROVIDERS`, or `_DEAD_MODELS` (207-216). Moving between providers waits 5 s (OpenRouter) or 10 s; there is no wait after a hard failure (219-232). Each attempt is wrapped in `trace_call(...)` (LangSmith; a no-op without a key) and `asyncio.wait_for(timeout)` (240-253).
- **On success:** a background cache SET, budget record, and billing-ledger record (`_COST_PER_1M`: anthropic $3/$15, gemini $0.35/$1.05, openrouter $0.5/$1.5) (264-354).
- **Placeholder guard:** empty output, or output such as "...", "todo", "null", rejects the response and retries with a self-critique prefix, but only if the retry count is above 1, which it never is (`retry_count` = 1 everywhere) (362-390).
- **Errors:**
  - A timeout always counts as fallback (401-413).
  - `_classify_error` returns retry for 429, 503, 502, or overloaded, and fallback for everything else (model_router_providers.py:181-195).
  - Fallback-class errors call `_mark_provider_dead`. A model is marked dead for payment, marketplace, or not-available errors. A provider is marked dead only for an invalid key (219-244).
  - AHM records every outcome.
  - When the chain is exhausted it raises `LLMUnavailable` with the last 3 errors (443-446).
- **Retries are layered:** the router makes 1 attempt per spec. Inside that, `_call_anthropic` and `_call_gemini` retry `llm.retry_attempts` (3) times, with a backoff of ≥60 s on rate limits (providers.py:84-151, 189-230). That inner retry can exceed the router's 45–60 s `wait_for`, at which point it is cancelled. `_call_bedrock` uses `retries=1` and a botocore read timeout of 50 s (providers.py:341-421).
- **task_type routing:** `_HEAVY_TASKS` = {code_generation, security_scan, testing, architecture, review} and `_LIGHT_TASKS` = {requirements, documentation, summarize, classify, intake, portal} (model_registry.py:14-15).
  - Bedrock: heavy → `BEDROCK_MODEL_HEAVY` (Nova Pro), anything else → Nova Lite (60-70). However, the router passes `model_id=spec.model` explicitly (model_router.py:470-473), so the **chain spec model overrides the task tier**. Under the router, Bedrock always uses the heavy or fallback spec model, whatever the task type.
  - Anthropic: light → `ANTHROPIC_DEFAULT_HAIKU_MODEL`, else sonnet or opus env, else the `models.primary` config default `minimax/minimax-m2.5:free` (31-50). The default assumes an OpenRouter-proxied Anthropic endpoint. The router's `ModelSpec.model` for anthropic is ignored.
  - Gemini: heavy → 2.5-pro, else 2.0-flash. The chain spec says `gemini-2.5-flash`, but the adapter ignores it.
  - OpenRouter: uses the spec model.
- **Real task_type usage across the repo:** code_generation 39, analysis 22, documentation 7, requirements 5, classify 3, plus one-off values such as ui_critique, code_fix, code_review. `analysis` is in neither set, so it is treated as light, cacheable, and uncompressed.

### 3.3 Prompt assembly and knowledge retrieval
- **PromptCompiler** (prompt_compiler.py) puts sections in this order: CONSTRAINTS (from ConstraintEngine) → ARCHITECTURAL DECISIONS (`ctx["decisions"]`) → DO NOT REPEAT (live `error_registry` summary mapped through `_ERROR_CATEGORY_RULES`) → RANKED KNOWLEDGE → GOOD example → WRONG patterns → TASK → ENTITIES (first 12 as JSON). The `compile_*` methods (54-179) have **no callers**. phases/p04a_backend_codegen/prompts.py:135-149 and 209-218 call the private helpers (`_get_backend_constraints`, `_format_constraints`, …) directly, so ranked knowledge never reaches p04a through the compiler.
- **context_compressor.compress_context(phase, ctx)** keeps `_ALWAYS_KEPT_KEYS` plus `PHASE_INTEREST_KEYS[phase]`. It truncates strings over 2,000 chars to 500 and lists over 20 items, then drops phase keys until the result fits in 40K chars (255-313).
- **retrieval_ranker.retrieve_for_phase** collects:
  - error-registry items (run-scoped, then global; weight 0.95)
  - the domain_packs constraint block (0.90)
  - KG FIXES nodes for 5 seed categories (0.80)
  - KG per-domain patterns (0.75×0.85)
  - golden JSON entity examples (0.75×0.90)
  - bug fixes, only for `phase_name ∈ {"p04a","p04b","backend_codegen","crud","p04"}`
  - GitHub entity patterns, only for `{"p01","p02","p03","p04a","domain_ir","entity_extraction"}`
  - architecture warnings (0.50)
  - the per-run NetworkX graph BFS from `domain` (0.70)
  It sorts the items and `format_for_prompt` keeps the top 5 (463-506). The only callers are p02b (`"p02b_domain_ir"`) and p05 (`"p05_frontend"`), so **the bug-fix and GitHub-pattern branches never fire**: the exact-match phase sets use short names. Also, phase_hooks writes the run graph as **JSON** to a file named `knowledge_graph.gpickle` (orchestrator/phase_hooks.py:265); the misleading extension is harmless.

### 3.4 Domain knowledge and IR
- **`domain_ir.DomainIR`** is the contract between the p02b planner and the deterministic p04a and p05 generators. `AetherType` (12 types) maps to SQLAlchemy, TypeScript, Zod, and OpenAPI types (31-109). The fields include a per-field `confidence` and `clarifying_questions`.
- **ir_validator.validate(ir, fix=True)** checks unique names and tables, canonical types (unknown → string), FK resolution, cardinality and aggregation enums, and workflow step completeness. It sets `ir.validated` but does **not save**, although the docstring says it re-saves (15 vs 172-177).
- **domain_knowledge** is the rich pack system. `loader.load_pack` feeds `build_prompt_prefix`, `build_schema_hints` (p02), `build_workflow_summary` (p04), and `build_compliance_summary` (p06). Callers: p00, p01, p02, p04a, p04b, p06.
- **domain_packs** is the constraint and integration pack system. Its only consumer is `retrieval_ranker._get_domain_pack_knowledge`.
- **`domain_engine.get_domain_profile`** is used by p02 and p03.
- **ConstraintEngine** is reached only through PromptCompiler. `get_vertical_constraints`, `get_compliance_constraints`, `get_domain_constraints`, and `format_for_prompt` have no callers outside the file.

### 3.5 Knowledge graph(s)
- **core/knowledge_graph.py** is a JSON dict graph. `get_singleton()` loads core/knowledge_graph.json or seeds and saves it (465-494). `record_from_ir` and `save_for_domain` append entity patterns (rolling 50) and edges (cap 200) to `~/.aether_os/knowledge_graphs/{domain}.json` (290-412).
  - FK detection expects `type == "foreign_key"` with a `references` key (317-322), but the IR uses `type == "fk"` with `ref_entity`. **REQUIRES edges are therefore never created** from a real DomainIR.
  - Called from p01 and orchestrator/phase_hooks_helpers.py through knowledge_graph_integration.
- **core/memory/knowledge_graph.py** is NetworkX. It is built after p02 from architecture.json in orchestrator/phase_hooks.py:241-267 and read by the ranker.

### 3.6 Memory
- **MemoryStore** (memory/store.py): an SQLite table plus FTS5 external-content triggers. An upsert increments `success_count`. `retrieve` tries an exact hash match, then FTS `MATCH input_hash`. That fallback is effectively useless because it searches with a hash, not text. Callers: phases/base.py memory_before/after, agents/implementations.py, gateway/routers/memory_router.py, main.py, orchestrator/pipeline_helpers.py.
- **ChromaProjectMemory**: a PersistentClient with one collection per org. Callers: phases/base.py and core/services/memory_service.py.
- **ProjectFingerprinter / ProjectMatcher**: the fingerprint is a SHA-256 of `domain::raw_input`, so only exact text matches score 1.0. Every other recent org run is returned with a similarity of 0.5 (fingerprinter.py:111-170).
- **graph_rag**: an offline AST import graph, rebuilt from scratch on each query (220-265). Used by memory_service.
- **project_memory** (used by orchestrator/factory_pipeline.py) and **memory_manager** (used by orchestrator/pipeline.py and factory_run_files_router.py) are duplicate writers of the same `.aetheros/project_memory.json`. `memory_manager` overwrites keys with no deep merge and raises on errors.

### 3.7 Learning
- **golden_retriever.record_feedback** clamps the rating to 1–5, stores `BuildFeedback`, and promotes a run to `GoldenBuild` when its average is ≥ 4.0. The record holds the models.py and Dashboard.tsx snapshot excerpts and an IR summary from `phases["p02_architect"]`, a phase key that probably does not match the real `p02_architecture`. `get_golden_examples` feeds `format_golden_hint_p04` and `format_golden_hint_p05`. The p05 hint shows colour classes only. Callers: p04a crud_generator, p05 helpers, gateway learning_router.
- **repair_learning**: `learn_from_repair(RepairEvent)` is called by p07b quality_helpers:51 and s05 gate_functions:302. `load_validators()` runs at gateway lifespan:143 and in p04a codegen_orchestrator:273. Generated validators expose only `validate(output_dir)`, and the wrapper's `check` returns `[]`, so the loop never closes. Files accumulate without dedup (one per event) in core/validators/auto_generated/, which currently holds only `__init__.py`.
- **stage_feedback**: written by stage supervisors s03, s04, s05, s07. It writes to core/knowledge_graph/stage_feedback.jsonl inside the package directory; that file is not present on disk.

### 3.8 Councils (core/council/)
- **PreFlightCouncil.run(raw_input, domain, org_id)**: one call with `task_type="classify"`, `max_tokens=512`, asking for clarity, feasibility, safety, and scope as JSON. Because `classify` is a **cached** task, an identical request gets the cached verdict. A parse failure returns `_ERROR_RESULT` (passed=False). Callers: core/queue/pipeline_consumer.py, gateway/routers/factory_run_background.py.
- **BackendAuditCouncil.audit(code, domain)**:
  - It first runs `_static_security_checks`: regexes for AWS keys, generic secrets, PEM blocks, and creds in URLs, plus checks for missing rate-limit or timeout markers and missing validation markers.
  - It then runs 4 checks (auth_enforcement, schema_consistency, org_isolation, no_stubs) on the first 8 KB of code. Each check goes directly to `call_openrouter` (bypassing the router, cache, budget, and tracing), rotating through COUNCIL_MODELS, then falls back to `_call_bedrock`. A substring match on "FAIL" in the first line counts as a failure.
  - It returns correction strings that feed regeneration.
  - `schema_consistency` asks about `CREATE TABLE` SQL, which does not match the SQLAlchemy ORM output that p04a generates.
  - Callers: p07b task_agent, orchestrator/phase_hooks, factory_pipeline.
- **run_council** (council_reviewer.py): 3 parallel persona calls using direct SDKs (anthropic, google-genai sync in an executor, Ollama HTTP), each falling back to Bedrock Converse.
  - The Bedrock default model IDs are Claude 3.5 Sonnet and Haiku (council_reviewer.py:218-222), which conflict with the Nova defaults elsewhere.
  - When only Bedrock is configured, the Gemini and Ollama personas use the same LIGHT model.
  - Consensus requires an issue mentioned by 2 or more distinct models with at least 2 overlapping significant words (the docstring says 3).
  - Callers: orchestrator/phase_hooks.py:358 (labelled "BackendAuditCouncil" in logs), artifact_collector, run_spec_router.
- **DeliveryCouncil.run**: summarises phase statuses and makes one classify call. Callers: artifact_collector, factory_pipeline.

### 3.9 Intelligence engines (core/intelligence/)
- All six are LLM-DRIVEN through `call_json`. All fail open with "pass" defaults: arch_governor returns `compliant: True` with `compliance_score: 0.5` on a 0–100 scale (arch_governor.py:48-54), and truth_engine defaults `coverage_percent` to 80 when the key is missing.
- They are exposed only through gateway/routers/intelligence_router.py and are not part of the pipeline.
- The maintenance "CVE scan" asks the LLM for CVEs from memory.
- truth_engine reads `~/.aether_os/projects/{run_id}/…main.py` candidates.
- `tradeoff_engine.evaluate_run_choices` is a stub (61-63).

### 3.10 Governance and quality
- **ArchitectureGovernor** checks whether model classes inheriting Base map to IR entities (phantom check), whether columns are in the IR fields, whether router prefixes map to tables, and whether frontend component bases map to entities. Every violation is `severity="warning"`. Callers: p04_backend task_agent, stages/s03_backend supervisor, p05 governor_integration. `_check_model_fields` regex-scans the **whole file** for every class (211-236), so fields of other classes are reported as unknown.
- **dimension_critic**: 8 weighted Python dimensions. Pass = overall ≥ 0.65 and no dimension < 0.40. Used by s05_quality supervisor and p06 critique_integration.
- **metrics.score_project**: scored out of 75 for auth (0.25), validation (0.25), test-file presence (0.10), domain, seed, docker, bandit, plus 25 bonus points for file presence. The frontend check may run `npx vite build` synchronously with a 120 s timeout inside an async hook (metrics.py:297-305). Callers: phase_hooks, analytics/runs/cleanup routers, scripts/backfill_quality.py.
- **QualityMonitor**: live probes. L1 `/health`, L2 `/auth/login` with admin@example.com / Admin1234!, L3 `GET /{entity.lower()}s/`, L4 non-empty. L2 logs in twice (`_fetch_token`). Naive pluralisation produces paths like `/categorys/`. Used by p07b and s07.

### 3.11 Decisions and questionnaire
- **DecisionEngine**: `request_approval` → DB row. `await_decision` uses Redis pub/sub on `aether:decisions:{id}`, or polls every 2 s. `resolve` checks the org, then saves and publishes.
  - Bug: `_wait_redis` checks the deadline only when a message arrives (146-148). With no message it **blocks forever**; the timeout is not enforced.
  - Race: a resolve that lands between `_db_get` and `subscribe` is missed.
  - Callers: p00, p01 gate_engine, p05 domain_assembler, factory_pipeline, 3 routers.
- **Questionnaire**: `STAGE_QUESTIONS` (s01–s12, 50+ questions) and `extract_stage_answers` serve autonomous mode. The renderer outputs inline CSS and JS that POSTs to `/api/questionnaire/{token}/submit`. Used by factory_pipeline and questionnaire_router.

---

## 4. Control flow and data flow

```
Request → [PreFlightCouncil classify] (pipeline_consumer / factory_run_background)
  p00_research: stack_selector → stack_profiles; domain_knowledge.load_pack; decision_engine
  p01: domain_knowledge prefix; knowledge_graph_integration.get_similar_entity_patterns; call_json; gate_engine decisions
  p02_architecture: domain_engine profile + build_schema_hints; spec_cache.get/put; LLMClient.call_structured(task=architecture)
     → phase_hooks: build NetworkX run graph → ctx.knowledge_graph_path
  p02b_domain_ir: context_compressor + retrieval_ranker (top-5 knowledge) → LLM 4-pass → ir_validator.validate → DomainIR json
     → knowledge_graph_integration.save_ir_to_knowledge_graph → ~/.aether_os/knowledge_graphs/{domain}.json
  p04a: DomainIR → deterministic ir_generators; LLM CRUD and seed prompts with PromptCompiler preamble (constraints, decisions, error registry)
        + golden_retriever hint; load_validators (no-op check)
  p04/s03: ArchitectureGovernor warnings; stage_feedback; after s03 → run_council / BackendAuditCouncil corrections → regen
  p05: retrieval_ranker + golden p05 hint + DomainIR generators; governor_integration
  p06: build_compliance_summary; json_enforcer; dimension_critic (critique_integration)
  s05: dimension_critic; gate_functions.regenerate_file → learn_from_repair
  p07b/s07: QualityMonitor L1–L4 → BackendAuditCouncil → learn_from_repair
  phase_hooks: metrics.score_project → quality_score
  end: DeliveryCouncil; project_memory.update; decisions resolved via routers
Every LLM call: LLMClient → compressor → ModelRouter (cache/budget/chain/AHM/LangSmith) → provider → cost → llm_traces
Every BasePhase: memory_before (always [] because of the bug) / memory_after → SQLite MemoryStore + Chroma (org_id = domain)
```

---

## 5. Plane mapping

| Plane | Components |
|---|---|
| AI / LLM plane | client, providers, model_router(+providers), model_registry, ahm, openrouter_client, compressor, json_enforcer, token_counter |
| Knowledge / RAG | retrieval_ranker, context_compressor, prompt_compiler, knowledge_graph*, golden_examples corpora, domain_knowledge, domain_packs, domain_engine, stack_profiles, memory/graph_rag |
| Memory | memory/store (SQLite FTS), memory/vector_store (Chroma), fingerprinter, matcher, memory/knowledge_graph, project_memory, memory_manager, spec_cache, cache.py |
| Learning loop | golden_retriever (REAL), repair_learning (hollow), stage_feedback, KG save_for_domain, improvement_loop (LLM, on demand) |
| SDLC (design → codegen) | domain_ir, ir_validator, constraint_engine, schema_importer (brownfield intake), questionnaire, decisions |
| Governance | architecture_governor, intelligence/arch_governor, truth_engine, conflict_resolver, tradeoff_engine, councils, decision_engine (human-in-the-loop) |
| STLC / quality | dimension_critic + scorers, metrics.score_project, quality_monitor, BackendAuditCouncil, DeliveryCouncil |
| Security / compliance | ConstraintEngine compliance (HIPAA, PCI-DSS, GDPR, SOC2), domain_knowledge ComplianceRule (PII/PHI/PCI flags), council static secret scan, scorer security, schema_importer LFI guard, cache org scoping (B8), `data_region=local-only` → Ollama only |
| SRE / cost | AHM health, circuit breakers, fallback counter (`get_status` for /health), TokenBudgetManager, billing ledger, org_llm_usage, LangSmith, llm_traces, maintenance_engine |
| Admin / API management | per-org LlmConfig and API keys (`_apply_org_chain_overrides`), `reinitialize()` for hot reload, system_info_router (budget and cache stats), intelligence_router, learning_router, memory_router, questionnaire_router |

---

## 6. Interfaces and dependencies

- **Public LLM API:**
  - `get_llm_client(provider=None).call(prompt, task_type="code_generation", context=None, system=None, max_tokens=8192, org_id=None, plan=None, run_id=None, phase=None, attempt=1, temperature=0.4) -> str`
  - `call_structured(prompt, schema_example, task_type, context) -> dict`
  - `call_json(...) -> dict`
  - `call_vision(prompt, image_bytes, ...)`
  - `embed(text) -> list[float]`
  - `ModelRouter.call(...) -> (text, provider)`
  - `get_router().get_status()`
- **External SDKs:** anthropic, google-genai, boto3/botocore (bedrock-runtime Converse and invoke_model), httpx (OpenRouter, Ollama, QualityMonitor), chromadb (optional), networkx, sqlite3, SQLAlchemy (async PG plus sync reflection), redis (through pipeline_state.get_redis), langsmith (through core/telemetry/langsmith_tracer.trace_call), bandit and npx (subprocess).
- **PG tables touched:** llm_traces, llm_cache_entries, token_budget_records, pipeline_runs.cost, org_llm_usage (raw SQL; existence unverified here), billing ledger (core.billing), organisations.data_region, llm_config, decisions, build_feedback, golden_builds, snapshots, runs, artifact_embeddings (dead adapter).
- **Filesystem state:**
  - ~/.aether_os/{memory.db, chroma_memory/, project_fingerprints.db, spec_cache/, knowledge_graphs/}
  - In-package: core/knowledge_graph.json, core/knowledge_graph/{stage_feedback.jsonl, auto_validators.json}, core/validators/auto_generated/*.py. These in-package writes are not shared across containers or replicas.
- **Env vars:** PRIMARY_LLM, OFFLINE_MODE, ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL / ANTHROPIC_DEFAULT_{HAIKU,SONNET,OPUS}_MODEL, GOOGLE_API_KEY, OPENROUTER_API_KEY / _HEAVY_MODEL / _LIGHT_MODEL / _FALLBACK_MODELS / _TIMEOUT, AWS_ACCESS_KEY_ID / SECRET / REGION, BEDROCK_ENABLED / BEDROCK_MODEL / _HEAVY / _LIGHT / _FALLBACK / _TIMEOUT / BEDROCK_EMBED_MODEL, OLLAMA_MODEL / _TIMEOUT / _BASE_URL, EMBEDDING_MODEL, COUNCIL_ENABLED, COUNCIL_STRICT_MODE, ENVIRONMENT, AETHER_KG_DIR.
- **Context propagation:** `orchestrator.events.ACTIVE_PHASE / ACTIVE_RUN_ID / ACTIVE_ORG_ID` ContextVars, imported by model_router at module load. This couples core to the orchestrator.

---

## 7. Reality check

**Confirmed bugs (verified by execution or line-level reading):**
1. **Anthropic tier is unusable through the router.** The extra positional `client` argument causes a TypeError (model_router.py:465-468 vs providers.py:72), verified with `inspect.signature().bind`. It is classified as fallback, so the run silently drops to the next provider. Mocked tests hide it.
2. **`temperature` is dropped** (the router has no such parameter, verified), and `phase_config.py` is dead.
3. **`safe_parse_json` returns the first innermost flat `{...}`** when JSON is wrapped in prose. For example, `'Here: {"a": {"b": 1}, "c": 2}'` yields `{'b': 1}` (verified; token_counter.py:30). Every `call_json` and `call_structured` caller (6 intelligence engines, p01, p02) is affected. `json_enforcer.extract_json` does this correctly but is not used there.
4. **Frontend critique always fails.** Frontend dimension names are absent from `DIMENSION_WEIGHTS` (dimension_critic_types.py:15-24), so overall = 0.0 (verified with a trivial .tsx file).
5. **`BasePhase.memory_before` always returns `[]`.** `r.confidence` is not a MemoryRecord field (phases/base.py:61). Cross-run memory injection is therefore non-functional. Chroma is also written with `org_id=domain` (phases/base.py:124).
6. **Learned validators are no-ops.** The `_Wrapper.check` returns `[]` (repair_learning.py:523-526), and the docstring promises registration in `validators/registry.py`, which never happens.
7. **DecisionEngine `_wait_redis` ignores the timeout when no message arrives** (decision_engine.py:146-148), so a pipeline can hang forever. There is also a subscribe-after-check race.
8. **Retrieval ranker phase gates never match** the real phase names (retrieval_ranker.py:269, 308), so bug-fix and GitHub-pattern knowledge is never injected.
9. **KG `record_from_ir` FK detection uses the wrong schema keys** (knowledge_graph.py:317-322), so no REQUIRES edges are created.
10. **Budget "haiku" downgrade is logged but not applied** (model_router.py:131-132).
11. **Placeholder self-critique retry is unreachable**, because `retry_count` is always 1 (model_router_providers.py:133-137).
12. **The router overrides task-tier selection for Bedrock** (it passes `model_id=spec.model`), and the Anthropic and Gemini adapters ignore `spec.model`. The chain status and logs therefore report a model that the request did not actually use.
13. **An org-injected OpenRouter key fails.** `call_openrouter` reads only `OPENROUTER_API_KEY` from env (openrouter_client.py:104), while `_is_provider_configured` and `_apply_org_chain_overrides` treat a DB key as configured.
14. **Cost is double-counted.** Up to 2 `record_usage` calls per LLM call (model_router.py:278-292 and 340-352 when `org_id` is set → `_ct2` and `_ct4`) plus a second billing record from `_call_bedrock` with cost 0. There are also 4 inconsistent price tables (client.py:184, model_router.py:299, budget.py:36, and implicitly Bedrock at $0).
15. **PreFlight and Delivery verdicts are cached** (`classify` is cacheable), so they are not re-evaluated.
16. **`is_local_llm()` defaults to "ollama"** while the router defaults to "bedrock", which produces a misleading warning and makes `get_prompt_style()` return "minimal" on Bedrock deployments (client.py:86-91, 117-121).
17. **ArchitectureGovernor field check is not scoped to a class** (architecture_governor.py:211-236). It is warnings-only and never blocks.
18. **metrics:** `test_score` is not in `total`, any `Depends()` counts as auth, and a synchronous `npx vite build` runs inside async hooks.
19. **ir_validator** does not save despite its docstring, V2 is not cycle detection, and the V1 casing-fix branch is unreachable (ir_validator.py:103-116).
20. **domain_knowledge/base.py redefines `ProcessStep` and `BusinessProcessPipeline`** (lines 49-67 and 79-138); the first definitions are dead.
21. **Contradictory guidance is injected into prompts:** the KG relative-import router rule vs ConstraintEngine absolute imports, and the fintech `balance_cents` vs "never store balance".

**DEAD (no production importers):** core/vector_store.py, core/llm/phase_config.py, core/decisions/db.py, `FrontendAuditCouncil`, `PromptCompiler.compile_{backend,frontend,seed}_prompt`, `ConstraintEngine.get_vertical_constraints / get_compliance_constraints / get_domain_constraints / get_hipaa_constraints / get_pci_constraints / format_for_prompt`, `ContextCompressor` class, `KnowledgeGraph.get_subsystem_connections / find_related_patterns / load_edges_for_domain / get_fixes_for` (outside the file), `tradeoff_engine.evaluate_run_choices` (stub), `_call_ollama`, and `LLMCache.get_stats` daily breakdown (returns `[]`).

**Pipeline-detached (API only):** all of core/intelligence/*, golden_retriever stats, graph_rag.

**Files over 600 lines:** none. The largest are model_router.py at 521 (it was split once already), repair_learning.py 566, stage_questions.py 557, client.py 555, and council.py 552, which are all close to the limit.

**Design debt:**
- 5 domain-knowledge systems.
- 2 knowledge-graph classes both named `KnowledgeGraph`.
- 2 project-memory writers.
- 3 cost ledgers.
- The council bypasses the router: no cache, budget, tracing, or cost for OpenRouter audit calls.
- State is written into the package directory, which breaks multi-replica and read-only images.
- core imports orchestrator ContextVars.

---

## 8. Open questions
1. Is the `org_llm_usage` table created by any Alembic migration? The raw SQL UPSERT in client.py:277-285 fails silently at debug level if it is not.
2. Which provider actually serves production? If `ANTHROPIC_API_KEY` is set and `PRIMARY_LLM=anthropic`, bug #1 means every call falls through to Gemini, Ollama, or Bedrock. The VPS env needs checking.
3. Is `COUNCIL_STRICT_MODE` / `ENVIRONMENT=production` set on the VPS? It decides whether council FAIL verdicts block runs.
4. Is LangSmith configured (`trace_call` is a no-op without it)? Is anything consuming `llm_traces`?
5. Is the `phases["p02_architect"]` key used in golden_retriever.py:104 ever populated, or are GoldenBuild IR summaries always empty?
6. Are the ChromaDB and SQLite memory stores mounted on persistent volumes in Docker? (All of them live under `~/.aether_os`.)
7. Which domain system is canonical, domain_knowledge or domain_packs? The alias maps differ: "erp" maps to the erp pack in one and to traditional_erp in the other, and "manufacturing" maps to the manufacturing pack vs ERP.
8. Do the s03/s04 supervisor calls to ArchitectureGovernor and stage_feedback run in the default pipeline, or only in the "stages" execution mode?
