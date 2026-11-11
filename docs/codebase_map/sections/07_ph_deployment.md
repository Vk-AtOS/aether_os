# 07_ph_deployment — Delivery & deployment of the GENERATED app

Scope: `phases/p08_cicd`, `p08_cicd_deployment`, `p09_documentation`, `p09_observability`, `p10_docs_delivery`, `p11_deployment`, `p11e_enterprise_deployment`, `p15_handoff` · 78 files (excl. `__pycache__`) · ~10,371 LOC · git HEAD 052a101 · mapped 2026-11-08. All files read in full. Paths below are relative to `phases/` unless they start with another top-level dir.

Status tags: **REAL** (deterministic logic that does what it says) · **LLM-DRIVEN** (output comes from an LLM call) · **TEMPLATE** (f-string or file emitter) · **STUB/HOLLOW** (shape only, or broken so it cannot work) · **DEAD** (no live caller, checked with grep).

---

## 1. Summary

- **What runs.** These phases are not called by the orchestrator. `orchestrator/phase_sequence.py:46-71` lists all of them in `INACTIVE_PHASE_DIRS`. Three stage supervisors call their `task_agent` modules directly, and per-phase `supervisor_agent.py`/`gate.py` are **skipped**:
  - `stages/s08_observability` → `p09_observability`
  - `stages/s09_devops` → `p08_cicd_deployment` (wraps `p08_cicd.CICDAgent`) → `p11_deployment` → `p11e_enterprise_deployment` (only for kubernetes/microservices builds, `s09:57-77`)
  - `stages/s11_handoff` → `p10_docs_delivery` (sequential), then `p14_client_portal` and `p15_handoff` in parallel, then its own ZIP.
- **Deployment really happens in only one place.** `p11_deployment` runs `docker build` and `docker run -d` on the AetherOS host (`p11_deployment/helpers.py:324-415`), polls `/health` and returns `live_url=http://$PUBLIC_HOST:<port>` (`p11_deployment/task_agent.py:152-269`). Nothing else deploys:
  - Kubernetes, Helm and Terraform are files only. There is no `kubectl`, `helm` or `terraform` call anywhere in scope.
  - The AWS ECS, Cloud Run and Railway helpers (`p11_deployment/helpers.py:201-319`) are **DEAD**: never called. ECS only runs `sts.get_caller_identity()` and returns a "next_step" string; Cloud Run returns a string.
- **Generated CI.** GitHub Actions `ci.yml` is a hard-coded TEMPLATE (`p08_cicd/task_agent.py:128-265`). It is mirrored to `<project>/.github/workflows/ci.yml` and comes with a minimal root `Dockerfile` and `scripts/check_compliance.py`. Its `docker` smoke-test job probes port **8080**, but the generated Dockerfile listens on **8000**, so the job fails as written (see §7).
- **CI self-repair engine** (`p08_cicd` DFLE/DSEE/SLM, about 3.5K LOC): parse log → localize failing frame → fingerprint → reuse a stored patch or ask the LLM for a unified diff → boundary/impact/test checks. It is real code, but it is **broken end to end**:
  - The webhook calls `run_repair` with the wrong keyword arguments and `await`s a synchronous function.
  - `ast_index=None` crashes `simulate_impact`.
  - Tests run **without applying the patch**.
  - `logger` is undefined in `pipeline.py`.
  - The PR, patch-apply and git-clone modules exist but nothing calls them.
- **LLM calls in scope**, all through `core/llm/client.LLMClient.call()`:
  - p08 SLM patch generation (`slm/__init__.py:38`)
  - p09_documentation README (`p09_documentation/task_agent.py:319`, legacy shim)
  - p10 5-file docs JSON (`p10_docs_delivery/task_agent.py:123`)
  - p11e AWS `main.tf` (`p11e_enterprise_deployment/task_agent.py:119`)
  - p15: 4 calls for README/ARCH, DATABASE/API, RUNBOOK/PERMISSIONS/DEVELOPMENT and the Postman collection (`p15_handoff/task_agent.py:122,163,213,275`)

  Every one of them has a template fallback.
- **Observability** (`p09_observability`) patches the generated `main.py` and injects `monitoring.py`. The template refers to `CollectorRegistry` without importing it, and the `try` only catches `ImportError`. Result: `NameError` at app startup whenever `prometheus-fastapi-instrumentator` is installed, and p09 adds that package to `requirements.txt` itself.
- **Handoff paths:**
  1. s11 ZIP (`stages/s11_handoff/supervisor.py:228-262`). It zips only `backend_output_path` and `frontend_output_path`, so CI, k8s, Helm, Terraform and the p15 docs are **left out**.
  2. GitHub push (`gateway/routers/run_preview_router.py:40-117`): creates a repo and PUTs files. Capped at 50 files, and it stops at the first directory.
  3. ZIP download route (`gateway/routers/run_deploy_router.py:181+`).

  There is no repo fork, and p15 makes no ZIP despite its docstring.

---

## 2. Coverage table

LOC = `wc -l`. Status: R = REAL, L = LLM-DRIVEN, T = TEMPLATE, S = STUB/HOLLOW, D = DEAD.

| File | LOC | Purpose | Status |
|---|---:|---|---|
| p08_cicd/__init__.py | 1 | package marker | — |
| p08_cicd/supervisor_agent.py | 19 | PhaseBase wrapper → task_agent.run, gate | D (phase inactive; s09 bypasses) |
| p08_cicd/gate.py | 51 | pass if cicd_patch.diff / scan_report.json / ci.yml exists | D (not invoked by s09) |
| p08_cicd/task_agent.py | 598 | CICDAgent: repair mode (pipeline.run_repair) or scan mode (bandit + CI yml + Dockerfile + compliance checker + prometheus compose) | R+T (repair path broken) |
| p08_cicd/pipeline.py | 441 | end-to-end repair orchestrator (memory → parse → localize → match/SLM → boundary → impact → tests → verify → sandbox) | R, broken (undefined `logger`, patch never applied) |
| p08_cicd/webhook.py | 151 | FastAPI `POST /ci/webhook`, `GET /ci/jobs/{id}`; call-graph init | R, broken (wrong run_repair kwargs; `CallGraph.build_call_graph` does not exist) |
| p08_cicd/temporal_prediction.py | 357 | risk trend forecast from telemetry spine | D (imports nonexistent `.telemetry_spine`; no callers) |
| p08_cicd/temporal_risk.py | 374 | per-file risk from FixLogDB | D (imports nonexistent `.db`, `.models`; no callers) |
| p08_cicd/adapters/base.py | 41 | CIFailureEvent + CIAdapter ABC | D |
| p08_cicd/adapters/detector.py | 28 | pick first adapter that parses payload | D (no external callers) |
| p08_cicd/adapters/github.py | 47 | parse workflow_run/check_run payload | D |
| p08_cicd/adapters/gitlab.py | 41 | parse GitLab pipeline payload | D |
| p08_cicd/adapters/jenkins.py | 49 | parse Jenkins build payload | D |
| p08_cicd/adapters/__init__.py | 0 | — | — |
| p08_cicd/sandbox/docker.py | 220 | docker-py container run of patched file (no net, ro, 128m) | R (import-time docker ping); `_apply_simple_patch` wrong |
| p08_cicd/repo/git_manager.py | 82 | clone/pull with token-embedded URL | D |
| p08_cicd/repo/patch_applier.py | 87 | `git apply`/branch/commit/push | D |
| p08_cicd/repo/pr_creator.py | 89 | GitHub PR / GitLab MR via REST | D |
| p08_cicd/dfle/log_parser.py | 258 | Python traceback / pytest / unittest parser | R |
| p08_cicd/dfle/ast_index.py | 169 | AST function/class index | R (never called in the repair path → index None) |
| p08_cicd/dfle/call_graph.py | 176 | caller/callee graph from AST | R (module function, not classmethod) |
| p08_cicd/dfle/localizer.py | 145 | score frames (AST proximity, depth, radius, tests) | R |
| p08_cicd/intelligence/predictor.py | 341 | FailurePredictor (decay) + PipelinePredictor (DB z-score) | D (no importers; `PipelinePredictor()` at import needs nonexistent `src.database`) |
| p08_cicd/dsee/boundary.py | 163 | single-file, ≤40 lines, no manifest/CI/infra paths | R |
| p08_cicd/dsee/impact.py | 195 | static diff impact + transitive ripple | R (crashes on `ast_index=None`) |
| p08_cicd/dsee/test_runner.py | 108 | pytest tier1/2/3 subprocess | R (runs unpatched tree) |
| p08_cicd/dsee/verifier.py | 71 | 4 stability conditions | R |
| p08_cicd/slm/__init__.py | 51 | `OllamaClient` shim → `LLMClient.call(task_type="code_generation")` | L |
| p08_cicd/slm/prompts.py | 90 | 7 error-type strategies + unified-diff system prompt | T (prompt) |
| p08_cicd/slm/validator.py | 59 | extract/validate diff | R |
| p08_cicd/slm/context_builder.py | 186 | RAG context from index/KG | D (imports nonexistent `src.repo.indexer` at call time; unused) |
| p08_cicd/feedback/__init__.py | 7 | re-export fingerprint + memory | R |
| p08_cicd/feedback/repair_memory.py | 84 | JSON memory at `~/.aether_os/repair_memory.json` | R |
| p08_cicd/patch_reuse/fingerprint.py | 101 | SHA-256 failure fingerprint | R |
| p08_cicd/patch_reuse/matcher.py | 6 | re-export `core.memory.matcher.match` | R |
| p08_cicd/patch_reuse/__init__.py, dfle/__init__.py, dsee/__init__.py, repo/__init__.py, sandbox/__init__.py, intelligence/__init__.py | 0 | — | — |
| p08_cicd/lang/__init__.py | 15 | export detector | R |
| p08_cicd/lang/base.py | 47 | LanguageAdapter ABC | R |
| p08_cicd/lang/detector.py | 28 | try python → js → java | R |
| p08_cicd/lang/python.py | 82 | Python traceback adapter | R |
| p08_cicd/lang/javascript.py | 75 | Node/Jest adapter | R |
| p08_cicd/lang/java.py | 77 | Java/JUnit adapter | R |
| p08_cicd_deployment/__init__.py | 3 | export supervisor | — |
| p08_cicd_deployment/task_agent.py | 78 | wraps `CICDAgent.run` (150s timeout), writes consolidated.json | R (thin) |
| p08_cicd_deployment/gate.py | 43 | checks a `files` key that is never written | D (s09 bypasses; logic mismatched) |
| p08_cicd_deployment/supervisor_agent.py | 18 | PhaseBase wrapper | D |
| p09_documentation/__init__.py | 7 | "compat alias" docstring | — |
| p09_documentation/task_agent.py | 341 | legacy README (LLM + 500-word template) | L+T; D in pipeline (tests only: tests/test_phases_later.py:358-396) |
| p09_documentation/gate.py | 6 | re-export p10 gate | D |
| p09_observability/__init__.py | 3 | export supervisor | — |
| p09_observability/task_agent.py | 447 | inject monitoring.py, patch main.py/requirements, write prometheus/grafana/alerts/otel files | T+R (generated monitoring.py crashes the app) |
| p09_observability/gate.py | 38 | expects keys logging/metrics/tracing/alerts that are never written | D (s08 bypasses) |
| p09_observability/supervisor_agent.py | 18 | wrapper | D |
| p10_docs_delivery/__init__.py | 3 | export | — |
| p10_docs_delivery/task_agent.py | 471 | LLM 5-doc JSON + templates; calls p14 portal and p15_change_requests (missing); quality_report.json | L+T |
| p10_docs_delivery/gate.py | 52 | checks `files` key in consolidated.json (absent) | D |
| p10_docs_delivery/supervisor_agent.py | 18 | wrapper | D |
| p11_deployment/__init__.py | 3 | export | — |
| p11_deployment/task_agent.py | 270 | write VPS/nginx/k8s/compose/Dockerfile; docker build+run; health poll; deployment.json | **R (executes)** |
| p11_deployment/helpers.py | 437 | app detection, fallback app via p04a, port locking, docker build/run/network, health wait, cloud helpers | R; cloud helpers D |
| p11_deployment/writers.py | 483 | Dockerfile, docker-compose(+dev), k8s (hpa/deploy/svc/ingress/secret tmpl), deploy/backup/restore/update.sh, nginx, DEPLOYMENT.md | T |
| p11_deployment/smoke_test.py | 272 | aiohttp CRUD smoke vs live container | R but effectively D (only gate calls it; gate never runs; returns "skipped" when a loop is running) |
| p11_deployment/prompts.py | 7 | "no LLM prompts" | — |
| p11_deployment/gate.py | 77 | gate + smoke | D (s09 bypasses) |
| p11_deployment/supervisor_agent.py | 31 | wrapper | D |
| p11e_enterprise_deployment/__init__.py | 0 | — | — |
| p11e_enterprise_deployment/task_agent.py | 178 | Helm + Azure TF + scripts + LLM AWS main.tf + Kafka/EKS/GHA | T+L |
| p11e_enterprise_deployment/prompts.py | 228 | AWS TF LLM prompt + fallback HCL | T (fallback HCL invalid) |
| p11e_enterprise_deployment/helpers.py | 586 | Helm chart, Azure TF, backup/restore/upgrade/healthcheck/bundle.sh | T (Helm deployment.yaml invalid) |
| p11e_enterprise_deployment/infra_helpers.py | 568 | Kafka Helm values, GHA ci/deploy/security, EKS TF | T |
| p11e_enterprise_deployment/gate.py | 40 | Chart.yaml/.tf/.sh presence | D |
| p11e_enterprise_deployment/supervisor_agent.py | 27 | wrapper (output_dir from project_dir) | D |
| p15_handoff/__init__.py | 0 | — | — |
| p15_handoff/task_agent.py | 334 | 4 LLM calls → 7 docs + Postman; business_model.json; manifest | L+T |
| p15_handoff/gate.py | 43 | required docs + postman | D |
| p15_handoff/supervisor_agent.py | 31 | wrapper | D |

DEAD verification (grep over `*.py`, excluding tests/node_modules):
- `temporal_prediction`, `temporal_risk`, `intelligence.predictor`, `PIPELINE_PREDICTOR`, `p08_cicd.repo`, `deploy_to_aws_ecs|cloud_run|railway`: only self-references.
- `p08_cicd.adapters`: only internal imports.
- `run_smoke_sync`: only `p11_deployment/gate.py:50`.

The stage supervisors call `mod.run`/`TaskAgent.run`, never the phase gates:
- `stages/s09_devops/supervisor.py:349-395`
- `stages/s11_handoff/supervisor.py:171-193`
- `stages/s08_observability/supervisor.py:383+`

---

## 3. Per-phase breakdown

### 3.1 p08_cicd — scan mode (the default)
- **Entry:** `CICDAgent.run` (`task_agent.py:17-41`). If `input_data.ci_failure` or `test_failures` is set → repair mode. Otherwise → `_run_scan`.
- **Inputs:**
  - `input_data.project_dir` and `project_name`
  - Code dir guessed in order: `project_dir/src`, `p04_backend/backend_codegen/src`, `p04a_backend_codegen/src` (`:28-32`).
- **Steps:**
  1. **Bandit.** `python3 -m bandit -r <src> -f json` via asyncio subprocess, 60s timeout (`:103-123`). The HIGH-severity issue texts become `results.issues`, which makes `success=False` (`:590`). In other words, a bandit HIGH fails p08.
  2. **ci.yml TEMPLATE** (`:128-265`). Jobs:
     - `backend`: postgres:15 service; ruff; `pytest tests/`; bandit `--exit-zero`
     - `frontend`: `npm install`, `npm run typecheck`, lint, build, in `frontend/`
     - `docker`: buildx with `push:false`, smoke test on :8080
     - `compliance-drift`: `python3 scripts/check_compliance.py`

     Written to `<project_dir>/p08_cicd_deployment/cicd/ci.yml` and mirrored to `<project_dir>/.github/workflows/ci.yml` (`:279-285`).
  3. **Root Dockerfile** if missing: `python:3.11-slim`, `uvicorn src.main:app` on 8000, and `pip install ... || true`, which hides install failures (`:287-306`).
  4. **`scripts/check_compliance.py`** (`_generate_compliance_checker`, `:332-461`): a standalone SHA-256 fingerprint of route-bearing `.py` files, compared with `compliance_manifest.json` (expected from p06). It optionally re-scans via `aether_os.core.compliance.code_scanner` when `aether_os` is installed.
  5. **`_wire_prometheus_monitoring`** (`:464-577`). When requirements mention prometheus it writes `docker-compose.yml` (app + `prom/prometheus:latest` + grafana, `GF_SECURITY_ADMIN_PASSWORD=admin`) and `prometheus.yml` into the p08 output dir (**not** the project root). It also injects `Instrumentator().instrument(app).expose(app)` after `app = FastAPI(...)` (paren-depth scan).
  6. Writes `scan_report.json`.
- **LLM:** none. `get_llm_client` is imported but unused (`:12`).
- **Targets supported:** GitHub Actions only.

### 3.2 p08_cicd — repair mode and the CI self-repair engine
- **Pipeline-side callers:**
  - `task_agent._run_repair` (`:43-78`) → `pipeline.run_repair(log_content, root_dir, historical_records=[], ast_index=None)`
  - `orchestrator/pipeline_helpers.py:24,287` (same arguments)
- **Webhook-side callers:**
  - `webhook.py` router is mounted at `gateway/api.py:280` (`POST /ci/webhook`, `GET /ci/jobs/{job_id}` → `core.audit.ledger.get_run_detail`).
  - `gateway/lifespan.py:38,154-157` calls `initialise_call_graph($AETHER_REPO_ROOT)`.
- **Flow** (`pipeline.py:88-441`):
  1. `core.memory.fingerprinter.fingerprint(log)`. If `GLOBAL_REPAIR_MEMORY` has `success_count ≥ 2`, the stored diff is returned immediately (`:113-132`).
  2. `dfle.log_parser.parse_log` (Python tracebacks, pytest FAILED, unittest FAIL) and `lang.detect_language_adapter` (py/js/java). Language is used only as a label.
  3. `dfle.localizer.localize`. Scores: 0.35 AST proximity (0.5 if the graph is empty), 0.35 stack depth, 0.15 caller radius, 0.15 test refs.
  4. `patch_reuse.fingerprint.build_fingerprint`, then `core.memory.matcher.match(fp, historical_records)`. `historical_records` is always `[]` from every caller, so matching never hits.
  5. **LLM path** (`:192-245`). `PromptTemplates.build_prompt(error_type, log[:2000], file_content, filename)` (`slm/prompts.py:68-90`) has 7 strategies (ConnectionTimeout, NullPointer, AttributeError, ImportError, ModuleNotFound, MemoryError, AuthenticationError). The system prompt says "output ONLY a unified diff". The call goes through `OllamaClient.generate_patch` → `LLMClient.call(system+user, task_type="code_generation")` (`slm/__init__.py:27-48`), run in a thread with its own event loop. `PatchValidator.extract_diff`/`is_valid_diff` only checks for the `---`, `+++` and `@@` markers.
  6. **DSEE:**
     - `check_boundary`: single file, matches target, ≤40 changed lines, no requirements/pyproject/.github/Jenkinsfile/Dockerfile/.env/docker-compose.
     - `simulate_impact(diff, ast_index, call_graph)`.
     - `TieredTestRunner.run_tier1(test_name)` then `run_tier2(target_file)` (pytest subprocess in `root_dir`).
     - `verify_stability` (tests pass, impact safe, no Pytest/DeprecationWarning, ripple < 10).
  7. **Score** (`score_confidence`, `:53-85`): 0.35·match + 0.25·candidate + 0.15·boundary + 0.15·impact + 0.10·tiers.
  8. **Optional sandbox** (`sandbox/docker.py`): docker-py runs the "patched" file as a script in `python:3.11-slim`/`node:18-slim` with network disabled, read-only, 128m memory, 0.5 CPU.
  9. `record_success` writes to the JSON memory.
- **Output:** `cicd_patch.diff` in the phase output dir (`task_agent.py:67-70`). The diff is **never applied, committed or opened as a PR**. `repo/patch_applier.py`, `repo/pr_creator.py` and `repo/git_manager.py` exist (real `git apply`/`push`, GitHub `POST /repos/{r}/pulls`, GitLab MR) but have no callers.

### 3.3 p08_cicd_deployment
- `task_agent.run` (`:23-78`) imports `p08_cicd.task_agent`, runs `CICDAgent().run(phase_input)` under a 150s timeout, wraps the result as a TaskResult with confidence 0.8 and writes `consolidated.json`.
- The "deployment" branch (`:41-50`) is unreachable. `_SUB_PHASES` holds only `cicd` (`:14-18`) to avoid running p11 twice (PIPELINE-008 comment).
- Returns `success = any_success or bool(results)`, i.e. true whenever the sub-task returned at all.
- This is what s09 Step 1 actually calls (`stages/s09_devops/supervisor.py:159-168`). Note it **discards** p08's own `run()` gating (`p08_cicd/task_agent.py:580-598`), which checks for the Dockerfile and bandit issues.

### 3.4 p09_documentation (legacy shim)
- `run()` writes `output_dir/docs/README.md`. It uses `LLMClient.call(prompt, task_type="documentation", max_tokens=4000)` (`:319`) and falls back to `_build_fallback_readme` (500+ word template with curl per `architecture_json.api_endpoints`, `:21-274`) when the output has fewer than 100 words.
- Marked dead in `phase_sequence.py:49`. Only tests use it.

### 3.5 p09_observability (called by s08 Step 1)
- **Inputs:** `canonical_src_dir` | `backend_src_dir` | `project_dir/p04_backend/backend_codegen/src` | `p04a_backend_codegen/src` | `main_py` | deepest `main.py` found by rglob outside `p03_scaffolding` (`_find_backend_src`, `:152-206`).
- **Writes into the generated backend (mutates the app):**
  - `monitoring.py` (`_MONITORING_PY`, `:14-79`): JSON log formatter, `add_prometheus_middleware`, `timing_middleware`.
  - `main.py` patch (`_patch_main_py`, `:209-246`): absolute import `from monitoring import ...`, `setup_logging()` injected inside `lifespan` (regex) or at module end, and `add_prometheus_middleware(app)` plus `app.middleware('http')(timing_middleware)` appended at EOF.
  - `requirements.txt`: adds `prometheus-fastapi-instrumentator>=0.9.1` (`:273-282`).
- **Writes into the phase output dir** (`<project>/p09_observability/monitoring/`):
  - `prometheus.yml` (target `host.docker.internal:8000`)
  - `docker-compose.monitoring.yml` (prom v2.51.0, grafana 10.4.1, admin/admin)
  - grafana datasource and dashboard provisioning (no dashboard JSON)
  - `prometheus_alerts.yml` (HighErrorRate, HighLatency p95>2s, ServiceDown)
  - `otel_setup.py` (OTLP HTTP exporter, FastAPI and SQLAlchemy instrumentors). It is **not** copied into src and **not** wired into `main.py`, so it is HOLLOW.
- **Outputs:** `observability.json`; `success` only if monitoring.py and main.py checks pass (`:305-446`).
- **LLM:** none.

### 3.6 p10_docs_delivery (called by s11, sequential)
- **Inputs:** `backend_src_dir`/`main_py`/deepest `main.py`; `main.py`, `models.py` and `schemas.py` truncated; routes regex `@(app|router).(get|post|...)`; class names; `architecture.entities`.
- **LLM:** one `LLMClient().call(prompt, task_type="documentation", max_tokens=8000)` (`:92-127`). The prompt asks for a JSON object with keys `README.md`, `docs/API_REFERENCE.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md` and `docs/SCHEMA.md`. Fences are stripped before `json.loads`. Any missing key is filled from a template (`_template_readme`/`_api_ref`/`_architecture`/`_deployment`/`_schema`, `:173-358`).
- **Outputs:** `<project>/p10_docs_delivery/docs/{README.md, docs/*.md, docs_summary.json}`, `quality_report.json` (from `core.error_registry.get_registry().get_summary()`) and `consolidated.json`.
- **Sub-tasks:**
  - `p14_client_portal.task_agent.run` (`:389-398`).
  - `p15_change_requests` (`:401-412`): the package **does not exist**; the `ImportError` is silently passed.
- s11 then runs `p14_client_portal` again in parallel (`stages/s11_handoff/supervisor.py:56`), so p14 runs twice.
- **Template inconsistencies:**
  - `_template_deployment` says "no Prometheus scraper or Grafana dashboard is pre-configured" and refers to a nonexistent `grafana_dashboard.json` (`:331-339`), which contradicts p09.
  - `_template_schema` says the admin password is logged to stdout.

### 3.7 p11_deployment (called by s09 Step 2, and by `POST /factory/runs/{run_id}/deploy`)
- **Inputs:** `phase_input.run_id`. The project dir is **hard-coded** to `~/.aether_os/projects/{run_id}` (`task_agent.py:55-57,96-99`), whereas `ProjectManager.get_output_dir` uses `project_id` (`core/projects.py:73-76`). Also `input_data.canonical_src_dir`, `raw_input` and `phase_outputs[*].metadata.frontend_build_failed`.
- **Always writes (TEMPLATE, `writers.py`):**
  - `deploy.sh`: installs Docker via `get.docker.com`, `docker-compose build/up`, alembic, seed, and prints "Admin password: admin_password_change_me".
  - `backup.sh` / `restore.sh`: `pg_dump` against a `db` service that the generated compose file does not define.
  - `update.sh` (git pull + rebuild)
  - `deployment/nginx/{nginx.conf, ssl.conf (commented)}`
  - `k8s/{hpa, deployment, service, ingress}.yaml` and `secrets.yaml.template`. Notes: `runAsUser 1000` while the image user is 1001; the readiness probe uses `/ready`; host is `app.yourdomain.com`.
  - `docker-compose.yml` (app + redis:7, healthcheck, resource limits; SQLite default) plus `docker-compose.dev.yml`
  - `DEPLOYMENT.md` (10 sections)
- **If Docker is available it executes:**
  1. `find_main_py` (canonical → priority list → rglob). If the result is a stub, `generate_fallback_app` loads `p04a_backend_codegen/task_agent.py` with `builtins.__import__` monkey-patched to stub `aether_os.*`, then calls `_generate_from_requirement(raw_input)` (`helpers.py:91-146`).
  2. `write_dockerfile`: python:3.11-slim, non-root uid 1001, HEALTHCHECK, `uvicorn <module>:app --workers 2`.
  3. `docker stop/rm` the same name and prune crash-looping containers with `RestartCount > 10` (`task_agent.py:156-190`).
  4. `ensure_network`: `docker network create --driver bridge --internal aetheros-isolated`.
  5. `docker build -t aetheros-<run8> <app_dir>` (600s).
  6. `docker run -d -p 127.0.0.1:<port>:8000 --restart unless-stopped --network aetheros-isolated --user 1001:1001 --read-only --tmpfs /tmp --tmpfs /app/data -e DATABASE_URL=sqlite+aiosqlite:////app/data/app.db --memory 512m --cpus 0.5 --cap-drop ALL --security-opt no-new-privileges --label aetheros.run=<id>` (`helpers.py:370-415`).
  7. `wait_for_ready`: aiohttp polls `http://localhost:<port>/health` for 30s and accepts any status < 500 (`:418-437`).
- **Outputs:** `deployment.json` (`live_url`, port, image, container, `docker_valid` 100/0, container log tail on failure).
- **Port allocation:** PID-file locks under `/tmp/aetheros_port_locks` for random ports 8200-8899, falling back to 8100-8199 (`helpers.py:151-196`). Lock files are never released.
- **Targets supported:**
  - Executed: local Docker only.
  - Files only: docker-compose, k8s, VPS scripts, nginx.
  - Cloud: dead helpers (ECS/Cloud Run return CLI strings; Railway would run `railway up --detach`).
- **LLM:** none (`prompts.py:1-7`).

### 3.8 p11e_enterprise_deployment (called by s09 Step 3, conditional)
- **Condition:** `build_profile.deployment_target=="kubernetes"`, or architecture is microservices/event_driven, or `architecture_decisions.deployment_strategy` contains k8s (`stages/s09_devops/supervisor.py:57-77`).
- **Writes into `<project>/p11e_enterprise_deployment/`:**
  - `helm/<slug>/`: Chart, values (postgresql/redis subchart keys but **no dependencies** declared), values.prod, and templates deployment/service/ingress/hpa/configmap/secret/pvc/_helpers. `templates/deployment.yaml:119` reads `name {{ include ... }}` with no colon, which is **invalid YAML**, so `helm template` fails. The configmap and pvc are never referenced.
  - `terraform/azure/`: AKS, PostgreSQL flexible server, Redis (template).
  - `terraform/aws/{variables,outputs}.tf` (template).
  - `terraform/aws/main.tf`. **LLM-DRIVEN:** `build_aws_terraform_prompt` (`prompts.py:11-35`) asks for VPC/ECS Fargate×3/ALB 443+ACM/RDS PG15 Multi-AZ/ElastiCache/SGs/IAM/CloudWatch. Called via `get_llm_client().call(prompt, task_type="code_generation", max_tokens=4000)` and accepted if longer than 500 chars, with no validation (`task_agent.py:113-128`). The fallback `aws_terraform_template` (`prompts.py:38-228`):
    - writes one-line SG blocks with two attributes (`resource "aws_security_group" "alb" { vpc_id = ... name = ... }`), which is invalid HCL
    - has no listener, no SG rules, no route tables/NAT and no secret versions
    - has an `outputs.tf` that references resources that may not exist when the LLM writes its own `main.tf`
  - `scripts/{backup (pg_dump→S3, retention), restore, upgrade (kubectl run migrations, set image, rollout), healthcheck (JSON), bundle (docker save + helm air-gap tar)}.sh`.
  - `helm/kafka/` (Bitnami kafka 26.x dependency, topics), if `message_queue` is kafka/rabbitmq.
  - `terraform/aws-eks/` (terraform-aws-modules vpc 5 / eks 20 / rds 6, ElastiCache replication group, S3 backend). Written if kubernetes or microservices. `module.vpc.database_subnet_group` is referenced, but `database_subnets` are not defined.
  - `.github/workflows/{ci.yml (test+lint, build-push to ghcr), deploy.yml (workflow_run → kubeconfig secret → helm upgrade --install → rollout → curl smoke), security.yml (Trivy fs → SARIF)}`. These sit in the phase subdirectory, so GitHub will not pick them up unless they are moved to the repo root.
  - `enterprise_deployment.json`.
- Always `success=True`, confidence 0.9.

### 3.9 p15_handoff (called by s11, in parallel with p14)
- **Inputs:** `project_name`, `domain`, `raw_input[:2000]`, entities from `domain_ir_path` or `architecture_json.database_schema`, `permission_model.roles`, `integration_map.integrations`, `tech_stack` (`_ctx_summary`, `:34-66`).
- **LLM calls** (`get_llm_client().call`):
  - **A** (`task_type="analysis"`, 3000 tokens): JSON `{readme, architecture}` with a Mermaid graph.
  - **B** (analysis, 4000): `{database (Mermaid erDiagram), api (CRUD tables, error codes)}`.
  - **C** (analysis, 4000): `{runbook, permissions, development}`.
  - **D** (`code_generation`, 4000): Postman v2.1 collection from `architecture_json.api_endpoints[:20]`, with login/register/health always included. Runs only if endpoints exist; otherwise an empty `item` list is written.

  Each call falls back to short stub markdown.
- **Outputs:** `<project>/p15_handoff/docs/{README, ARCHITECTURE, DATABASE, API, RUNBOOK, PERMISSIONS, DEVELOPMENT}.md`, `postman/collection.json`, `business_model.json` (if present) and `handoff_manifest.json`. **No ZIP.** The s11 docstring (`stages/s11_handoff/supervisor.py:32`) attributes the ZIP to p15, but s11 builds it itself.

---

## 4. Control flow and data flow

```
FactoryPipeline (12 stages, orchestrator/phase_sequence.py:87-100)
 ├─ s08_observability ─► p09_observability.task_agent.run
 │     mutates <src>/main.py, adds <src>/monitoring.py, requirements.txt
 │     writes <proj>/p09_observability/{monitoring/*, observability.json}
 ├─ s09_devops (stages/s09_devops/supervisor.py:150-310)
 │   1 ► p08_cicd_deployment.task_agent.run ─► p08_cicd.CICDAgent.run
 │         scan: bandit → <proj>/.github/workflows/ci.yml, <proj>/Dockerfile (if absent),
 │               <proj>/scripts/check_compliance.py, <proj>/p08_cicd_deployment/cicd/{ci.yml,scan_report.json,
 │               docker-compose.yml?,prometheus.yml?}; may patch <src>/main.py (Instrumentator)
 │         repair (if ci_failure set): pipeline.run_repair → cicd_patch.diff (never applied)
 │   2 ► p11_deployment.TaskAgent.run  (project_dir = ~/.aether_os/projects/{run_id})
 │         writes deploy/backup/restore/update.sh, deployment/nginx/*, k8s/*, docker-compose*.yml,
 │         DEPLOYMENT.md, <app_dir>/Dockerfile  → docker build → docker run → /health poll
 │         → live_url, port → s09 metadata (supervisor.py:184-195)
 │   3 ► p11e_enterprise_deployment.task_agent.run   [only kubernetes / microservices]
 │         writes <proj>/p11e_enterprise_deployment/{helm,terraform,scripts,.github}/...
 │   gate (s09:312-345): warn-only on Dockerfile / CI path; always passed=True
 ├─ s11_handoff (stages/s11_handoff/supervisor.py:80-167)
 │   1 ► p10_docs_delivery.run (LLM docs + p14 portal + missing p15_change_requests + quality_report.json)
 │   2 ► asyncio.gather(p14_client_portal.run, p15_handoff.run)
 │   3 ► _build_project_zip → <s11 out>/project_delivery.zip
 │         (only backend_output_path + frontend_output_path; s11:228-262)
 │   gate: always passes (s11:290+)
 └─ Out-of-pipeline handoff / ops (gateway, outside this scope):
     POST /factory/runs/{id}/deploy   → p11 TaskAgent (gateway/routers/run_deploy_router.py:43-80)
                                        Docker absent → in-process preview /app-preview/
     DELETE /factory/runs/{id}/deploy → stop container
     GET  .../zip                      → on-the-fly ZIP (run_deploy_router.py:181+)
     POST push-to-github              → create repo via api.github.com/user/repos, PUT contents
                                        per file (run_preview_router.py:40-117)
     POST /ci/webhook                  → background p08 repair (p08_cicd/webhook.py:96-140)
```

Data handoffs:
- **Context keys read:** `project_dir`, `project_name`, `canonical_src_dir`, `backend_src_dir`, `main_py`, `raw_input`, `architecture_json`/`architecture`, `domain_ir_path`, `permission_model`, `integration_map`, `build_profile`, `architecture_decisions`, `business_model`, `phase_confidence`, `governor_report`.
- **Context keys written:**
  - p10: `docs_path` (`p10_docs_delivery/task_agent.py:381`)
  - s09: `live_url`, `backend_port`
  - s11: `handoff_zip_path`
- **P72 coupling:** p09 patches `canonical_src_dir`, and p11 deploys from the same `canonical_src_dir` (`p11_deployment/task_agent.py:100-104`). Both p08 and p09 inject Prometheus into the same `main.py`. p08 skips if `Instrumentator` or `/metrics` is already present. s08 runs before s09, so p09's import is already there, but p08 checks only for the literal string `Instrumentator`, which `monitoring.py` contains but `main.py` does not. Double instrumentation is therefore possible. Note s08's docstring comment "FIX FOR DUPLICATE INJECTION" (`stages/s08_observability/supervisor.py:33`).

---

## 5. Plane mapping

| Plane | Components |
|---|---|
| **Deployment** | p11 Docker build/run with hardened flags (only real deploy); p11 compose/k8s/nginx/VPS scripts (files); p11e Helm/Terraform AWS/EKS/Azure, deploy.yml GitOps-style Helm CD (files); dead cloud helpers (ECS/Cloud Run/Railway); manual redeploy route (`run_deploy_router`) |
| **SDLC / CI** | p08 GitHub Actions `ci.yml` (backend/frontend/docker/compliance-drift); p11e `ci.yml` (build-push ghcr), `deploy.yml`; p08 CI self-repair engine (log→patch, broken); git/PR modules (dead) |
| **STLC (testing)** | p08 DSEE tiered pytest runner + stability verifier; p11 `smoke_test.py` CRUD smoke (never reached); CI pytest/ruff/typecheck jobs; p11e deploy.yml curl smoke; p11 `/health` readiness poll |
| **SRE / observability** | p09 JSON logging, Prometheus middleware, alert rules, Grafana provisioning, OTel file (unwired); p08 prometheus/grafana compose; p11 container HEALTHCHECK, restart policy, crash-loop pruning, resource limits; k8s HPA/probes; p11e backup/restore/upgrade/healthcheck/bundle scripts; p15 RUNBOOK; `intelligence/predictor.py`, `temporal_*` failure forecasting (dead) |
| **Security** | p08 bandit scan (HIGH → p08 fail); p11 docker run hardening (`--read-only`, `--cap-drop ALL`, non-root, `no-new-privileges`, internal network, loopback bind); DSEE boundary forbids patches to manifests/CI/infra/.env; p08 sandbox (no network, read-only); p11e Trivy workflow; k8s securityContext. Negatives: hard-coded `admin_password_change_me` (`writers.py:340`), Grafana admin/admin, `SECRET_KEY` default in compose, GitHub token embedded in clone URL (`repo/git_manager.py:36-39`, dead) |
| **Compliance** | p08 `scripts/check_compliance.py` drift gate + CI job (depends on p06 `compliance_manifest.json`) |
| **Docs / handoff** | p10 LLM 5-doc set; p15 LLM 7 docs + Postman; p11 DEPLOYMENT.md; p09_documentation legacy README; s11 ZIP; GitHub push route |
| **API management** | Postman collection (p15); API_REFERENCE.md (p10); webhook API `/ci/webhook`, `/ci/jobs/{id}` |
| **Admin control** | none in scope (manual deploy/stop routes live in the gateway) |

---

## 6. Interfaces and dependencies

- **Base types:** `aether_os.phases.base` (`PhaseBase`, `TaskResult`, `GateOutcome`) in every supervisor and gate.
- **LLM:** `aether_os.core.llm.client` (`get_llm_client()`, `LLMClient().call(prompt, task_type, max_tokens)`, `client.py:101-129`). `task_type` values used: `code_generation` (p08 SLM, p11e, p15-D), `documentation` (p09doc, p10), `analysis` (p15 A–C).
- **Core modules:**
  - `aether_os.core.projects.get_project_manager().get_output_dir(project_id, phase)` → `~/.aether_os/projects/<project_id>/<phase>` (`core/projects.py:16,73`)
  - `core.memory.fingerprinter.fingerprint` and `core.memory.matcher.match` (p08)
  - `core.audit.ledger.get_ledger().get_run_detail` (webhook status)
  - `core.error_registry.get_registry` (p10)
  - `core.compliance.code_scanner.scan_file` (optional, inside the generated checker)
- **Cross-phase dependencies:**
  - p11 `generate_fallback_app` loads `p04a_backend_codegen/task_agent.py::_generate_from_requirement`.
  - p10 → `p14_client_portal.task_agent.run`.
  - p10 → `p15_change_requests` (absent).
  - p11 smoke → `p02b_domain_ir/domain_ir.json`, `p11_deployment/preview_credentials.json`.
  - p08 checker → p06 `compliance_manifest.json`.
- **External tools and services:**
  - Docker CLI (p11), docker-py (p08 sandbox; pings at import)
  - bandit (p08), pytest (DSEE), aiohttp (p11 health/smoke), PyYAML (p11 compose validation)
  - boto3 (dead ECS), `railway` CLI (dead), git CLI (dead)
  - GitHub and GitLab REST (dead `pr_creator`)
- **Environment variables:**
  - `PUBLIC_HOST` (p11 live_url)
  - `AETHER_REPO_ROOT` (webhook call graph)
  - `SANDBOX_IMAGE|TIMEOUT|MEMORY|CPU`
  - `GITHUB_TOKEN`, `GITLAB_TOKEN`
  - `AWS_*`, `GOOGLE_CLOUD_*`, `RAILWAY_TOKEN` (dead helpers)
- **Persistent state:**
  - `~/.aether_os/repair_memory.json` (p08)
  - `/tmp/aetheros_port_locks/*.pid` (p11)
  - `/tmp/aether_repos` (dead git manager)
  - Docker network `aetheros-isolated`; containers labelled `aetheros.run=<id>`

---

## 7. Reality check

**What is actually executed versus generated**
- **Executed:** `docker build` and `docker run` on the AetherOS host (p11); bandit (p08); pytest and the docker-py sandbox (only on the broken repair path).
- **Generated only:** GitHub Actions, k8s manifests, Helm, Terraform (AWS ECS / EKS / Azure), compose files, nginx, VPS/ops scripts, docs, Postman.
- **Never done in scope:** `kubectl`, `helm` or `terraform` calls; registry pushes; cloud API calls (apart from the dead ECS STS call).
- **"Live URL"** means a container on the AetherOS host bound to `127.0.0.1:<port>`, with `PUBLIC_HOST` substituted. A reverse proxy is assumed to exist elsewhere.

**Bugs, by severity**
1. **p11 container probably unreachable.** `docker run` attaches only to `aetheros-isolated`, which was created with `--internal` (`helpers.py:357-364,381`). Docker does not publish ports for containers on internal-only networks, so `wait_for_ready` against `localhost:<port>` would likely time out and give `success=False`. Needs runtime confirmation (Q1).
2. **p09 makes the generated app crash at startup.** `_MONITORING_PY` uses `CollectorRegistry()` without importing it (`p09_observability/task_agent.py:58`), and the except clause catches only `ImportError`. p09 adds the instrumentator to `requirements.txt` (`:280`), so the import succeeds and a `NameError` follows when `add_prometheus_middleware(app)` runs at module import (`:242`).
3. **p08 generated CI fails on its docker smoke job.** The job runs `-p 8080:8080` and curls `localhost:8080/health`, but the generated Dockerfile serves on 8000 (`p08_cicd/task_agent.py:230-237` vs `:297-298`; `p11_deployment/writers.py:48-52`). `DATABASE_URL` points to a postgres that exists only in the `backend` job. `npm run typecheck` assumes p05 added that script (it does: `p05_frontend/code_writer.py:50`). The compliance-drift job fails if `compliance_manifest.json` is not committed.
4. **The CI repair engine cannot work end to end:**
   - `webhook._run_repair_async` calls `run_repair(ci_log=, repo_name=, branch=, job_id=, call_graph=)` and `await`s it. The real signature is synchronous `(log_content, root_dir, historical_records, ast_index, call_graph)` (`webhook.py:84-90` vs `pipeline.py:88-94`), so it raises `TypeError`, which is caught and logged.
   - `webhook._build_call_graph_for_repo` calls `CallGraph.build_call_graph(str(root))`. That is a module-level function taking `(index, root)`, so it raises `AttributeError`, is caught, and the graph is always None (`webhook.py:37`).
   - `pipeline.py` uses `logger` (`:424,431`) without importing logging. This is a `NameError`, partly masked by the surrounding `except` that itself calls `logger`.
   - All callers pass `ast_index=None`, so `simulate_impact` crashes on `ast_index.get` / `.items()` (`dsee/impact.py:114,123`) once the boundary check passes.
   - The tier-1/2 tests run against the **unpatched** tree, because the patch is never applied before `TieredTestRunner` (`pipeline.py:285-320`).
   - `sandbox._apply_simple_patch` rebuilds the file from diff hunks only, dropping everything outside them (`sandbox/docker.py:192-220`). The "validation" just executes the file as a script.
   - `historical_records=[]` everywhere, so patch reuse only works through the JSON memory.
   - The repair output (`cicd_patch.diff`) is never applied, committed or opened as a PR.
5. **p11 failure paths can be reported as passes.** "Frontend build failed" and "No main.py" return `skipped:True, success:False` (`task_agent.py:113-117,146-150`). `supervisor_agent.py:26` maps that to success, and `gate.py:14-19` passes on `skipped`. Under s09, `_run_sub_phase` uses `success` (False) but s09's gate passes anyway.
6. **p11 live smoke test never runs.** Only `gate.py` calls it, and s09 skips gates. When it is called from async code, `run_smoke_sync` returns "skipped — already in async context" (`smoke_test.py:258-262`).
7. **Gates disagree with what their task agents write:**
   - p08_cicd_deployment, p10 and p15 gates look for `files` or specific structures that are never written.
   - The p09 gate expects keys `logging/metrics/tracing/alerts`, but `observability.json` has `features`.
   - All of these are moot, because the stages bypass gates.
8. **Generated IaC that fails validation:** p11e Helm `deployment.yaml` is missing a colon (`helpers.py:119`); the fallback AWS HCL has invalid one-line multi-attribute blocks (`prompts.py:220-223`); EKS references an undefined `database_subnet_group`; LLM Terraform output is accepted unvalidated. Nothing runs `helm lint` or `terraform validate`.
9. **Handoff gaps:**
   - The s11 ZIP excludes `.github/`, `k8s/`, `helm/`, `terraform/`, `deploy.sh`, `DEPLOYMENT.md` and the p10/p15 docs. It covers only backend/frontend output paths.
   - The GitHub push loop runs `break` on the first non-file path; sorted `rglob` yields directories, so it stops early. It is also capped at 50 files and creates a **public** repo (`run_preview_router.py:79,96`).
   - p14 runs twice (inside p10 and again in s11).
10. **Path inconsistency.** p11 uses `~/.aether_os/projects/{run_id}`; the other phases use `pm.get_output_dir(project_id, …)` / `input_data.project_dir`. p11e's and p15's own supervisors default `project_dir` to `/tmp`.
11. **Import-time side effects:**
    - `sandbox/docker.py:12-20` calls `docker.from_env().ping()` at import. It is imported by `pipeline.py`, which is imported at module level by `orchestrator/pipeline_helpers.py:24`.
    - `feedback/repair_memory.py:84` creates `~/.aether_os` at import.
    - `intelligence/predictor.py:341` would raise `ModuleNotFoundError: src.database` if anything imported it.
12. **Smaller issues:**
    - p08's Dockerfile `pip install ... || true` hides dependency failures.
    - Port lock files are never released.
    - `wait_for_ready` accepts any status below 500.
    - Templates hard-code `admin@example.com` / `admin_password_change_me` and Grafana admin/admin.
    - p08 imports `get_llm_client` without using it.
    - p11 `task_agent.py` recomputes `run_id`/`project_dir` (`:96-99`).
    - `p10_docs_delivery` uses the deprecated `datetime.utcnow`.

**Files over 600 lines:** none. Largest: `p08_cicd/task_agent.py` 598 (at the limit), `p11e/helpers.py` 586, `p11e/infra_helpers.py` 568, `p11/writers.py` 483.

**Size of dead code:** temporal_prediction + temporal_risk + intelligence/predictor + adapters (5 files) + repo (3 files) + slm/context_builder + cloud helpers ≈ **1,960 LOC** (~38% of p08_cicd). All per-phase `gate.py`/`supervisor_agent.py` in scope are bypassed by the stage supervisors (≈ 600 LOC).

---

## 8. Open questions

1. Does `docker run --network aetheros-isolated` (an `--internal` network) still publish `127.0.0.1:<port>` on the deployment hosts that are actually used? If not, has every pipeline run hit the `/health` timeout? Check `deployment.json` `docker_valid` values in `~/.aether_os/projects/*`.
2. Is `project_id == run_id` guaranteed? If not, p11 (keyed on `run_id`) and pm-based phases (keyed on `project_id`) write to different trees, and the GitHub push (`run_id`) would miss pm outputs.
3. Who sets `input_data.ci_failure` / `test_failures` to trigger p08 repair mode, and is the `/ci/webhook` route used in production (`gateway/api.py:280` mounts it)? If not, should the self-repair engine be removed or finished (apply patch → test → PR via the dead `repo/*`)?
4. Should p11e artifacts (`.github/workflows` in the phase subdir) be promoted to the project root? Should the s11 ZIP include the whole project dir instead of backend/frontend only?
5. Is `p15_change_requests` planned? p10 silently skips it.
6. Is the cloud deploy (ECS / Cloud Run / Railway) a roadmap item or abandoned? Nothing in the pipeline or gateway calls those helpers.
7. Should the per-phase gates in scope be wired into the s08/s09/s11 supervisors? The stage gates are all warn-only and always pass.
8. Has a generated app with the p09 `monitoring.py` ever booted? The `CollectorRegistry` `NameError` suggests the instrumentator path is never exercised, perhaps because the dependency is not installed in the image or p11 fails before startup.
