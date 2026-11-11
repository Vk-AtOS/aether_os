# 08 — Ops & Enterprise phases for the GENERATED app (p11a–p21)

Scope: `phases/p11a_monitoring`, `p11b_error_tracking`, `p11c_analytics`, `p11d_alerting`, `p12a_feature_flags`, `p12b_ab_testing`, `p13_app_memory`, `p14_client_portal`, `p16_iam`, `p17_control_plane`, `p18_billing_metering`, `p19_service_catalog`, `p20_multiregion`, `p21_sre_agent`.
61 files · 7,764 LOC · HEAD 052a101 · mapped 2026-11-08. All files read in full. Callers also read: `stages/s08_observability/supervisor.py`, `stages/s10_enterprise/supervisor.py`, `stages/s11_handoff/supervisor.py`, `stages/s12_specialist/supervisor.py`, `orchestrator/phase_sequence.py`, `phase_dag.py`, `phase_selector.py`.

---

## 1. Summary

- **All 14 phases are deterministic TEMPLATE generators. None of them calls an LLM.** A grep for llm/anthropic/complete( across all 14 dirs only matches docstrings: `p20_multiregion/multiregion_generator.py:10` says "no LLM calls", and `p21_sre_agent/sre_generators.py:7` says "LLM-powered remediation generator", which is false. `core/llm/phase_config.py:33-34` defines LLM configs for `p12a_feature_flags` and `p13_app_memory`, but nothing reads them in those phases.
- **What they produce is files only.** Nothing is deployed, applied, or started. The output is Prometheus/Grafana/OTEL/Alertmanager configs, Sentry/PostHog snippets, JSON-file-backed feature-flag, A/B and memory services, OPA Rego plus a Keycloak realm, a Go K8s operator, OpenMeter/Stripe scaffolding, a service-catalog API, multi-region Terraform, and an SRE CronJob/operator. **No phase in this scope touches the live AetherOS control plane.**
- **None of these phases is registered in the orchestrator directly.** `orchestrator/phase_sequence.py:46-71` lists all 14 in `INACTIVE_PHASE_DIRS` ("phase agent library"). The real pipeline is the 12 stages (`phase_sequence.py:90-103`). The phases run inside stage supervisors through `importlib` → `task_agent.run()`:
  - **s08_observability:** p11a, p11b, p11c in parallel, then p11d. Runs by default.
  - **s10_enterprise:** p12a, p12b, p13, p16, p18, p21 in parallel, then p17 only when architecture ∈ {microservices, event_driven} or deployment_target == kubernetes. Six run by default; p17 is conditional.
  - **s11_handoff:** p14, in parallel with p15. Runs by default.
  - **s12_specialist:** p19 when build_type == cloud_platform; p20 when deployment_target == kubernetes and architecture ∈ {microservices, event_driven}. Both opt-in.
- **Every phase's `supervisor_agent.py` and `gate.py` is DEAD.** Stage supervisors call `task_agent.run` directly (`s08/supervisor.py:391-393`, `s10/supervisor.py:376-385`, `s11/supervisor.py:165-176`, `s12/supervisor.py:216-225`), so per-phase gates never run. `phase_dag.py:90-117` still lists the p11a–p21 dependencies, but `factory_pipeline.py:396` only passes stage names to the DAG, so those entries are vestigial.
- **The generated artifacts probably never reach the customer's delivery ZIP or app.**
  - Each phase writes to `project_dir/<phase_name>/` (`core/projects.py:73-76`).
  - The s11 delivery ZIP only includes `backend_output_path` and `frontend_output_path` (`s11/supervisor.py:236-257`).
  - The s10 auto-wire only looks for router files under `backend_src` (`s10/supervisor.py:113-118`), which the phases never write to. It also imports `router` from `billing/billing_webhook.py`, but that file exports `billing_router` (`metering_generator.py:215`).
- **There are many runtime bugs**, both in the generators and in the code they generate (see §7). Highlights:
  - `NameError: logger` in p11a, p11b and p11c.
  - IAM Rego/Keycloak roles don't match.
  - The p17 operator cannot compile.
  - The p21 CronJob image has no `kubectl`.
  - The p19 router has a Python <3.12 SyntaxError.
  - Several JWT handlers decode tokens without verifying the signature.

---

## 2. Coverage table

Status tags: **REAL** = working deterministic logic. **TEMPLATE** = writes fixed strings or files. **STUB** = hollow or placeholder. **DEAD** = never called on the live path.

| File | LOC | Purpose | Status |
|---|---|---|---|
| p11a_monitoring/__init__.py | 3 | exports MonitoringSupervisor | DEAD (only the package import) |
| p11a_monitoring/gate.py | 22 | checks prometheus.yml, ≥3 dashboards, monitoring compose | DEAD (bypassed by s08) |
| p11a_monitoring/supervisor_agent.py | 16 | PhaseBase wrapper | DEAD |
| p11a_monitoring/task_agent.py | 386 | Prometheus, alert rules, 3+1 Grafana dashboards, provisioning, monitoring compose, OTEL config, instrumentation helper, MONITORING.md, main.py injection | TEMPLATE (+ REAL main.py patch; bug at :375) |
| p11a_monitoring/grafana_domain_dashboards.py | 130 | domain KPI dashboards (ecommerce, fintech, healthcare, marketplace, saas, erp/hrm/procurement) | TEMPLATE |
| p11a_monitoring/mimir_config.py | 479 | Mimir Helm values, compose, config, Cortex→Mimir migration guide | TEMPLATE; called by `s08/supervisor.py:244-264`, not by p11a |
| p11b_error_tracking/__init__.py | 3 | export | DEAD |
| p11b_error_tracking/gate.py | 15 | checks sentry_setup/error_middleware/test | DEAD; also checks the wrong dir (`output/sentry_setup.py`, but files go to `error_tracking/`) |
| p11b_error_tracking/supervisor_agent.py | 16 | wrapper | DEAD |
| p11b_error_tracking/task_agent.py | 118 | Sentry init, JSON logging, error middleware, env, test, main.py Sentry injection | TEMPLATE (bug :107) |
| p11c_analytics/__init__.py | 3 | export | DEAD |
| p11c_analytics/gate.py | 15 | checks service/events/migration | DEAD |
| p11c_analytics/supervisor_agent.py | 16 | wrapper | DEAD |
| p11c_analytics/task_agent.py | 328 | PostHog analytics service, events, middleware, HTML dashboard, analytics router, SQL migration, main.py timing middleware | TEMPLATE (bugs :34, :199, :319) |
| p11d_alerting/__init__.py | 3 | export | DEAD |
| p11d_alerting/gate.py | 13 | checks alertmanager.yml, ≥3 runbooks | DEAD |
| p11d_alerting/supervisor_agent.py | 16 | wrapper | DEAD |
| p11d_alerting/task_agent.py | 488 | alertmanager.yml (Slack/PagerDuty), 6 alert rules, 4 runbooks, alert test script, env, INTEGRATION.md | TEMPLATE |
| p12a_feature_flags/__init__.py | 3 | export ("Unleash" in docstring, which is false) | DEAD |
| p12a_feature_flags/gate.py | 15 | checks files | DEAD |
| p12a_feature_flags/supervisor_agent.py | 16 | wrapper | DEAD |
| p12a_feature_flags/task_agent.py | 152 | writes feature_flags/, migrations/, tests/ | TEMPLATE |
| p12a_feature_flags/templates.py | 299 | FEATURE_FLAGS_PY: JSON store, flock, RLock, MD5 % rollout, blue/green, rings, RolloutManager | TEMPLATE (generated logic is REAL) |
| p12a_feature_flags/templates_extras.py | 328 | admin router /flags, seed JSON, SQL, 20 pytest tests | TEMPLATE |
| p12b_ab_testing/__init__.py | 3 | export ("GrowthBook", false) | DEAD |
| p12b_ab_testing/gate.py | 15 | checks files | DEAD |
| p12b_ab_testing/supervisor_agent.py | 16 | wrapper | DEAD |
| p12b_ab_testing/task_agent.py | 226 | weighted hash assignment, /experiments router, z-test p-value calculator, SQL, tests | TEMPLATE |
| p13_app_memory/__init__.py | 3 | export ("mem0", false) | DEAD |
| p13_app_memory/gate.py | 15 | checks files | DEAD |
| p13_app_memory/supervisor_agent.py | 16 | wrapper | DEAD |
| p13_app_memory/task_agent.py | 435 | memory service (Chroma → pgvector → JSON), in-memory knowledge graph, 2 routers, SQL, tests | TEMPLATE |
| p14_client_portal/__init__.py | 3 | export | DEAD |
| p14_client_portal/gate.py | 15 | checks html/sql | DEAD (`stat()` would raise if the file were missing) |
| p14_client_portal/supervisor_agent.py | 16 | wrapper | DEAD |
| p14_client_portal/task_agent.py | 329 | reuses the p10 portal if present; else portal HTML, /portal ticket router (JSON file), zip download, SQL, placeholder test | TEMPLATE / partial STUB (test is `assert True`) |
| p16_iam/__init__.py | 0 | empty | — |
| p16_iam/supervisor_agent.py | 33 | wrapper + gate (policy.rego exists) | DEAD |
| p16_iam/task_agent.py | 43 | reads permission_model → generate_iam_package | TEMPLATE |
| p16_iam/iam_generator.py | 277 | OPA Rego, OPA Helm values, Keycloak realm JSON | TEMPLATE (semantic bugs) |
| p17_control_plane/__init__.py | 0 | empty | — |
| p17_control_plane/supervisor_agent.py | 32 | wrapper + gate (main.go) | DEAD |
| p17_control_plane/task_agent.py | 60 | trigger check, entities from domain_ir | TEMPLATE |
| p17_control_plane/operator_generator.py | 567 | CRD YAML, Go controllers, RBAC, main.go, go.mod, Dockerfile | TEMPLATE; generated code does not compile |
| p18_billing_metering/__init__.py | 0 | empty | — |
| p18_billing_metering/supervisor_agent.py | 30 | wrapper + gate (billing_webhook.py) | DEAD |
| p18_billing_metering/task_agent.py | 42 | entities → generate_billing_package | TEMPLATE |
| p18_billing_metering/metering_generator.py | 512 | OpenMeter config, CloudEvents schema, Stripe webhook router, metering middleware, OpenMeter Helm values | TEMPLATE (webhook signature check is REAL; tenant mapping and actions are STUB TODOs) |
| p19_service_catalog/__init__.py | 0 | empty | — |
| p19_service_catalog/supervisor_agent.py | 27 | wrapper + gate | DEAD |
| p19_service_catalog/task_agent.py | 73 | cloud_platform guard; catalog + `p05_frontend.cloud_console_generator.generate_cloud_console` | TEMPLATE |
| p19_service_catalog/catalog_generator.py | 396 | SQLAlchemy models, migration, catalog router (/api/platform, /api/services, /api/billing) | TEMPLATE (SyntaxError on Py<3.12) |
| p20_multiregion/__init__.py | 0 | empty | — |
| p20_multiregion/supervisor_agent.py | 35 | wrapper + gate (main.tf) | DEAD; checks `output/multiregion/main.tf`, which matches task output_path |
| p20_multiregion/task_agent.py | 97 | k8s + microservices guard; chaos (`core/chaos_engineering`), capacity (`core/capacity_planner`), multiregion | TEMPLATE |
| p20_multiregion/multiregion_generator.py | 513 | Global Accelerator, Route53 latency records, VPC peering mesh, variables, outputs, guide | TEMPLATE |
| p21_sre_agent/__init__.py | 0 | empty | — |
| p21_sre_agent/gate.py | 17 | `check()` prereq (deployment_config or architecture) | DEAD (no caller) |
| p21_sre_agent/supervisor_agent.py | 33 | wrapper + gate (k8s/sre-agent-cronjob.yaml) | DEAD |
| p21_sre_agent/task_agent.py | 427 | CronJob + SA + Role, Prometheus-polling classifier script with kubectl remediation and PagerDuty, playbook | TEMPLATE |
| p21_sre_agent/sre_generators.py | 575 | sre/operator.py (Alertmanager webhook HTTP server), failure_classifier, remediation_generator (kubectl map, no LLM), canary_runner, manifests (Deployment, RBAC, AlertmanagerConfig) | TEMPLATE |

No file in scope is over 600 lines. The largest are `sre_generators.py` (575) and `operator_generator.py` (567).

---

## 3. Per-phase breakdown

Common contract: `async run(phase_input, memory_ctx, output_dir) -> TaskResult`. `memory_ctx` is ignored by all 14 phases. `output_dir = project_dir/<phase>` comes from `pm.get_output_dir`. No prompts and no LLM client in any of them.

### p11a_monitoring — Prometheus / Grafana / OTEL (s08, default ON)
- **Inputs:** `project_dir`, `project_name`, `domain` (`task_agent.py:12-14`).
- **Generates** under `<out>/monitoring/`:
  - `prometheus.yml`: scrapes `app:8000/metrics` and node-exporter; `rule_files: alert_rules.yml`; no `alerting:` block (:22-40).
  - `alert_rules.yml`: HighErrorRate >5%, HighP95Latency >2s, ServiceDown (:43-79).
  - Grafana dashboards: `red_metrics.json`, `resources.json`, `business_kpis.json` (:82-162), plus `domain_<d>.json` from `grafana_domain_dashboards.get_domain_dashboard` (:165-174, map at `grafana_domain_dashboards.py:113-122`).
  - Grafana datasource and dashboard provisioning (:177-202).
  - `docker-compose.monitoring.yml`: Prometheus, Grafana on :3001 (admin pw default `admin`), node-exporter; all `:latest`; no Alertmanager (:205-254).
  - `otel_config.yaml`: traces go to the `logging` exporter only (:257-287).
  - `app_instrumentation.py` and `MONITORING.md` (:290-342).
- **Side effect:** patches `project_dir/src/main.py` (or `project_dir/main.py`) to add `prometheus_fastapi_instrumentator` after `app = FastAPI(...)`, found by paren-depth scan (:345-376).
- **Mimir:** `mimir_config.py` is used only by s08, when `estimated_users > 10000`, `scale_tier ∈ {enterprise, high_traffic}`, or k8s with high load (`s08/supervisor.py:232-276`). It writes into `Path(backend_output_path).parent/monitoring`.
- **Output:** `TaskResult(output_path=monitoring_dir, metadata.grafana_dashboards=3)`. The 3 is hardcoded even when a 4th domain dashboard is written (:383).

### p11b_error_tracking — Sentry + JSON logs (s08, default ON)
- **Writes:** `error_tracking/sentry_setup.py` (init only when a DSN is given, traces 0.1), `logging_config.py` (JSONFormatter), `error_middleware.py` (logs and re-raises), `.env.error_tracking`, `tests/test_error_tracking.py` (:17-70).
- **Side effect:** injects `sentry_sdk.init(dsn=SENTRY_DSN)` into main.py (:73-108). No structlog, despite the s08 docstring (`s08:28`).

### p11c_analytics — PostHog + event store (s08, default ON)
- **Writes** under `analytics/`:
  - `analytics_service.py`: PostHog lazy init (:17-54).
  - `analytics_events.py`: 6 constants.
  - `analytics_middleware.py`.
  - `analytics_dashboard.html`: polls `/analytics/events`.
  - `analytics_insights.json`: static text.
  - `analytics_router.py`: POST `/analytics/track`, GET `/analytics/events` with 24h stats, raw SQL via `src.database.get_db` (:165-268).
- **Also writes** `migrations/add_analytics_events.sql`.
- **Side effect:** injects a request-timing `@app.middleware('http')` into main.py (:282-320).

### p11d_alerting — Alertmanager + runbooks (s08, runs sequentially after p11a–c, default ON)
- **Writes** under `alerting/`:
  - `alertmanager.yml`: default → Slack, critical → PagerDuty, warning → Slack, inhibit critical over warning (:23-74).
  - `alert_rules.yml`: 6 rules (HighErrorRate, HighLatencyP95, DatabaseConnectionPoolExhausted on `db_pool_available_connections`, ServiceDown, HighMemoryUsage, HighCPUUsage) with `runbook` annotations (:77-150).
  - `alert_runbooks/{HighErrorRate,HighLatency,DBConnectionPoolExhausted,ServiceDown}.md` (:153-298).
  - `alert_test_script.py`: POSTs to `/api/v1/alerts` (:301-389).
  - `.env.alerting.example` and `INTEGRATION.md`.
- `domain` is read but unused.

### p12a_feature_flags — homegrown flag service (s10, default ON)
- **Writes:** `feature_flags/{__init__,feature_flags.py,flag_admin_router.py,initial_flags.json,INTEGRATION.md}`, `migrations/add_feature_flags.sql`, `tests/test_feature_flags.py` (`task_agent.py:61-122`).
- **Generated logic** (`templates.py:8-296`):
  - JSON store at `$FEATURE_FLAGS_PATH` (default `feature_flags.json`), guarded by `fcntl` flock and `threading.RLock`.
  - `FEATURE_<FLAG>` env-var override.
  - Rollout bucket: MD5 `flag:user` mod 100.
  - Blue/green variants and internal < beta < production rings.
- **Admin router** `/flags` (`templates_extras.py:10-132`) has no auth. The docs say "Unleash" (`__init__.py:1`, `s10:25`), but it is homegrown, and the generator logs a not-production-grade warning (`task_agent.py:48-51`).

### p12b_ab_testing — homegrown experiments (s10, default ON)
- **Writes** `ab_testing/`:
  - `ab_testing.py`: JSON store, weighted MD5 bucket % 1000.
  - `ab_router.py`: `/experiments`, no auth.
  - `ab_results_calculator.py`: two-proportion z-test via `erfc`, named "chi_square".
  - `experiment_hypothesis.json`, SQL (experiments, experiment_events), INTEGRATION, tests (`task_agent.py:20-218`).
- Not GrowthBook, despite `__init__.py:1` and `s10:26`. The SQL tables are never used by the JSON code.

### p13_app_memory — semantic memory (s10, default ON)
- **memory_service.py** (:41-309): picks a backend at import time — ChromaDB `PersistentClient` if importable, else pgvector if `PGVECTOR_ENABLED`, else JSON file.
  - The pgvector path creates `embedding vector(1536)` but never writes embeddings; search is `ILIKE` (:207-219).
- **knowledge_graph.py** is in-process dicts only (:312-330).
- **Routers:** `/memory` and `/knowledge-graph`, no auth.
- **SQL** uses `embedding JSONB`, which conflicts with the runtime `vector(1536)`.
- No mem0, despite `__init__.py:1` and `s10:27`.

### p14_client_portal — client ticket portal (s11, default ON)
- **Dedup path:** if p10's `consolidated.json` lists a `client_portal` output, p14 reuses it. When `quality_score`/`council_verdict` are present it string-replaces cards into that HTML, unescaped (:18-71).
- **Otherwise writes:**
  - `client_portal/client_portal.html`: fetches `/portal/tickets` and renders with `innerHTML`.
  - `portal_router.py`: `/portal` HTML, ticket CRUD stored in `portal_tickets.json`, `/portal/download` zip with sha256 provenance. No auth.
  - `migrations/add_portal.sql` and a placeholder test (:73-321).
- This is a portal inside the generated app; it is not the AetherOS platform client portal.

### p16_iam — OPA + Keycloak (s10, default ON)
- **Input:** `permission_model` (from s02/p02c), `project_name`.
- **Writes** `iam/policy.rego` (package `authz.<slug>`, `default allow := false`, one `allow` block per role/resource/actions), `iam/opa-values.yaml`, and `iam/keycloak-realm.json` (realm, roles, confidential `api-client` with secret `CHANGE_ME_IN_PRODUCTION`, 15-minute access token, brute-force protection) (`iam_generator.py:47-277`).
- **Role-source mismatch:**
  - Rego rules come from `permission_model["rules"]` (`iam_generator.py:35`).
  - p02c actually emits `permissions: {Role: {Resource: [actions]}}` with no `rules` key (`p02c_permission_modeling/task_agent.py:1-60`).
  - So the Rego always falls back to `admin/user/viewer` (:22-26), while Keycloak gets the real roles (SuperAdmin, Admin, Manager, Staff, ReadOnly) from `permission_model["roles"]` (:266).
  - Result: tokens from the generated realm carry role names the Rego policy doesn't recognise, so every request is denied.

### p17_control_plane — K8s operator + CRDs (s10, CONDITIONAL)
- **Triggered** by s10 (`s10:287-315`) and re-checked inside the phase (`task_agent.py:31-39`).
- **Entities** come from `data["domain_ir"]["entities"]`, with a fallback stub `resource` (:41-44).
- **Writes** `operator/main.go`, `go.mod`, `Dockerfile`, `controllers/<Kind>Controller.go`, `config/crd/<table>_crd.yaml`, `config/rbac/role.yaml` (`operator_generator.py:523-567`).
- The "control plane" here is a scaffold for the generated app's own CRDs. It is not AetherOS's admin control plane.

### p18_billing_metering — OpenMeter + Stripe (s10, default ON)
- **Writes** `billing/`:
  - `openmeter-config.yaml`: one meter per entity; COUNT, SUM, or UNIQUE_COUNT chosen by name keywords; Kafka sink (:42-110).
  - `event-schema.json`: CloudEvents (:116-183).
  - `billing_webhook.py`: `billing_router` POST `/billing/stripe/webhook` with real `stripe.Webhook.construct_event` signature verification; the three event handlers are logging-only TODOs (:189-274).
  - `metering_middleware.py`: `BaseHTTPMiddleware` that fire-and-forgets CloudEvents to `$OPENMETER_URL/ingest`; tenant comes from the `X-Tenant-Id` header (:280-391).
  - `helm/openmeter-values.yaml` (:397-466).

### p19_service_catalog — cloud console backend (s12, opt-in: build_type == cloud_platform)
- **Writes** `service_catalog/router.py`: `/api/platform/stats|events`, `/api/services`, `/api/services/{name}/launch` (inserts a row only, no provisioning), `/api/resources/{id}/status`, `/api/billing/current|invoice/current` at a flat $0.12 per resource. Also `models.py` (SQLAlchemy) and `migration.sql` (`catalog_generator.py:28-396`).
- **Also** calls `p05_frontend/cloud_console_generator.generate_cloud_console` (81 LOC, outside this scope) to write a React console (`task_agent.py:17,51`).
- Tenant is read from an unverified JWT `sub`, falling back to `"default"` (`catalog_generator.py:144-160`).

### p20_multiregion — chaos + capacity + multi-region (s12, opt-in: k8s + microservices/event_driven)
- **Chaos:** `core.chaos_engineering.chaos_generator.generate_chaos_package` (LitmusChaos).
- **Capacity:** `core.capacity_planner.planner.generate_capacity_package` (HPA, KEDA, PDB, quotas). Both are outside this scope (`task_agent.py:20-21, 64-76`).
- **Multi-region:** `multiregion/{main.tf, variables.tf, outputs.tf, DEPLOYMENT_GUIDE.md}` with Global Accelerator (primary weight 100, others 50), Route53 latency records with health checks, a full-mesh VPC peering with aliased per-region providers, and an SG rule on port 8000 (`multiregion_generator.py:24-513`). Default regions are us-east-1, eu-west-1, ap-southeast-1. Regions are not configurable from context.
- `success = bool(files_written)` (:96).

### p21_sre_agent — SRE agent scaffold (s10, default ON)
- **Inputs:** project_name, architecture, deployment_config (for app_name and namespace), domain.
- **Writes:**
  - `k8s/sre-agent-cronjob.yaml`: every 5 minutes, `python:3.12-slim`, pip-installs requests, runs `/scripts/sre_failure_classifier.py` from ConfigMap `<app>-sre-scripts`; plus SA, Role (deployments and scale) and RoleBinding (`task_agent.py:47-127`).
  - `scripts/sre_failure_classifier.py`: polls Prometheus for 3 base patterns plus a domain pattern (healthcare, fintech, ecommerce at :25-44), runs `kubectl` remediations through `subprocess`, pages PagerDuty Events v2 when a remediation fails (:130-259).
  - `docs/REMEDIATION_PLAYBOOK.md`.
  - `sre/`: `operator.py` (stdlib HTTPServer on :9876 receiving Alertmanager webhooks → classify → kubectl), `failure_classifier.py` (FAILURE_MATRIX plus regex fallback), `remediation_generator.py` (static category → kubectl map; "certificate" deletes the `<app>-tls` secret), `canary_runner.py` (`kubectl set image`, sleep, PromQL check, `rollout undo`), and `manifests/` (operator Deployment and Service, Role with pods/secrets delete, `AlertmanagerConfig` CR) (`sre_generators.py:33-575`).
- This is a rule-based "agent" with no LLM and no learning.

---

## 4. Control flow and data flow

```
factory_pipeline ─► stage loop (PHASE_SEQUENCE s01..s12; DAG waves on stage names)
  s08_observability.run_task
     p09_observability (out of scope) → main.py prometheus middleware
     _prometheus_already_in_main → input_data.prometheus_already_injected (never read by p11a)
     gather(p11a, p11b, p11c)   ← shared phase_input (not deep-copied)
     p11d
     if scale → mimir_config.* → <backend_output_path>.parent/monitoring/
     metadata: monitoring_path=p11a.output_path, grafana_dashboards, alert_rules_count,
               sentry_configured/analytics_events (scanned under p11a dir → always False/[])
  s10_enterprise.run_task
     gather(p12a,p12b,p13,p16,p18,p21, return_exceptions=True)  ← deepcopy input per phase
     input_data[feature_flags_path|ab_testing_path|memory_service_path|iam_policies_path|billing_path|sre_agent_path] = result.output_path
     if microservices/event_driven or kubernetes → p17 → input_data.k8s_operator_path
     _autowire_enterprise_extensions(backend_src, succeeded) → appends try/except include_router to backend_src/main.py
        (only if router file exists under backend_src — phases write elsewhere → no-op in practice)
     gate: always passed=True
  s11_handoff: p10 → gather(p14, p15) → project_delivery.zip (backend+frontend paths only) → quality report
  s12_specialist: build_profile triggers → gather(p19?, p20?, mobile/desktop/cli/serverless) → input_data[service_catalog_path|multiregion_path]
```

**Data sources and sinks:**
- **Reads from context:** `project_dir`, `project_name`, `domain` (factory_pipeline.py:278-291); `permission_model` (s02 :170); `build_profile` (phase_hooks_helpers.py:58); `domain_ir` (never set; s02 only sets `domain_ir_path`, s02:150); `architecture`, `deployment_config`, `estimated_users`, `scale_tier` (no producer found in stages/orchestrator).
- **Disk writes:** `project_dir/<phase>/…`. p11a, p11b and p11c also mutate `project_dir/src/main.py` or `project_dir/main.py`, if present. s10 auto-wire mutates `backend_src/main.py`.
- **Context writes:** only the stage supervisors write path keys. Phases do not write context.
- **Artifact embedding:** `orchestrator/artifact_collector.py:55-60` walks `project_dir/<name>` for names in `results`. Those names are stage names, so `project_dir/p12a_feature_flags` etc. are probably not embedded (see open questions).

---

## 5. Plane mapping (all generate-only, for the GENERATED app)

| Plane | Components |
|---|---|
| **SRE / observability** | p11a (Prometheus, Grafana RED/resources/business/domain dashboards, OTEL, node-exporter, Mimir for scale), p11b (Sentry, JSON logs), p11c (request timing, event analytics), p11d (Alertmanager routing, 6 rules, 4 runbooks, test script), p21 (CronJob remediator, webhook operator, canary runner, playbook), p20 (LitmusChaos, HPA/KEDA/PDB capacity) |
| **Security / IAM** | p16 (OPA Rego, OPA Helm, Keycloak realm with brute-force protection and 15-minute tokens), p18 Stripe signature verification. Negatives: unauthenticated generated routers (/flags, /experiments, /memory, /knowledge-graph, /portal, /analytics); unverified JWT decode in the p16 Rego and the p19 tenant extraction; p21 Role can delete secrets; Grafana admin/admin; Keycloak placeholder secret |
| **Compliance** | Weak. Healthcare dashboard panels named "HIPAA Audit Events" and data-export (`grafana_domain_dashboards.py:57-69`); fintech "Compliance Checks Passed" panel (:51); p14 zip provenance with sha256 (`p14 task_agent.py:263-282`); p19 `platform_events` audit table. No policy-as-code beyond p16 |
| **Deployment / infra** | p17 (operator, CRDs, RBAC, Dockerfile), p20 (Global Accelerator, Route53, VPC peering Terraform), p11a monitoring compose, p18 OpenMeter Helm, p16 OPA Helm, p21 K8s manifests, Mimir Helm (`mimir_config.py`) |
| **Release management** | p12a (percentage canary, blue/green, rings), p12b (experiments, significance), p21 `canary_runner.py` |
| **Admin control (generated app)** | p12a `/flags` admin API, p19 cloud console API, p14 ticket portal, p17 CRD control loop. **No AetherOS-platform admin control is in this scope** |
| **API management / monetization** | p18 (OpenMeter per-entity meters, CloudEvents schema, Stripe webhooks, metering middleware), p19 (service catalog, per-tenant billing estimate, JSON invoice) |
| **Data / AI** | p13 (vector memory, knowledge graph), p11c (event store) |
| **Customer success** | p14 (client portal tickets) |

---

## 6. Interfaces and dependencies

- **Base types:** `aether_os.phases.base.TaskResult` (output_path, confidence, metadata, issues, success…) and `GateOutcome`, `PhaseBase` (`phases/base.py:24-31`).
- **Callers:**
  - `stages/s08_observability/supervisor.py:186-223, 244` (p11a–d, mimir_config)
  - `stages/s10_enterprise/supervisor.py:228-315` (p12a, p12b, p13, p16, p18, p21, p17)
  - `stages/s11_handoff/supervisor.py:113-124` (p14)
  - `stages/s12_specialist/supervisor.py:116-124` (p19, p20)
- **Cross-scope imports:**
  - p19 → `phases/p05_frontend/cloud_console_generator.generate_cloud_console`
  - p20 → `core/chaos_engineering/chaos_generator.generate_chaos_package`, `core/capacity_planner/planner.generate_capacity_package`
  - p14 → reads p10's `consolidated.json`
  - p16 → p02c `permission_model` (shape mismatch)
  - p17, p18, p19, p20 → `domain_ir` (p02b shape: `{"name", "table", "fields":[{"name","type"}]}`, `p02b_domain_ir/ir_extractor.py:125-131`)
- **Registries that mention these phases but do not run them:**
  - `orchestrator/phase_sequence.py:46-71` (INACTIVE_PHASE_DIRS)
  - `orchestrator/phase_dag.py:90-117` (legacy deps)
  - `orchestrator/state_machine.py:105-113` (p11a–p14 → PipelineState)
  - `core/llm/context_compressor.py:188-195` (p11a, p14 keys)
  - `core/llm/phase_config.py:33-34` (p12a, p13)
  - `phase_selector.AREA_TO_PHASE` maps "observability/monitoring" → s08 and "enterprise" → s10 (`phase_selector.py:37-43`) for change requests
- **External dependencies the generated code assumes:**
  - Python: prometheus_fastapi_instrumentator, sentry_sdk, posthog, chromadb, psycopg2, stripe, httpx, requests, sqlalchemy
  - Infrastructure: OPA, Keycloak, OpenMeter, Kafka, Grafana Mimir/MinIO, Alertmanager, prometheus-operator (AlertmanagerConfig CRD), LitmusChaos, KEDA
  - Go: controller-runtime v0.17, AWS provider ~> 5.0

---

## 7. Reality check

**Generate-only versus live.** Every output is a file on disk. Nothing is applied, deployed, scraped, or exercised by AetherOS. Nothing in scope calls kubectl, terraform, helm, or docker. The only "live" effect is source-patching the generated `main.py` (p11a :345-376, p11b :73-108, p11c :282-320, s10 auto-wire).

**Dead code:**
- All 14 `supervisor_agent.py` classes and all `gate.py` modules (stage supervisors bypass them).
- `p21_sre_agent/gate.check` has no caller.
- `phase_dag.py` p-phase entries.
- `input_data["prometheus_already_injected"]` (set at s08:175, never read).
- `s08._ALERT_RULE_NAMES` (:54-61, unused).
- `phase_config` entries for p12a and p13.
- In the generated p11c router, `_get_db` is unused.

**Generator bugs (AetherOS side):**
1. **`logger` is undefined** in `p11a_monitoring/task_agent.py` (no `logging` import; used at :375), `p11b_error_tracking/task_agent.py:107`, and `p11c_analytics/task_agent.py:319`. Any exception while patching main.py turns into a `NameError`. s08 catches it (`s08:399-407`) and the whole sub-phase becomes `success=False`, even though all its files were already written.
2. **s08 metadata is wrong.** `_sentry_configured` and `_analytics_events` scan only p11a's monitoring dir (`s08:302-303`), so `sentry_configured` is always False and `analytics_events` always []. `alert_rules_count` double-counts p11a's 3 rules plus p11d's 6.
3. **s08 shares `phase_input` across parallel phases without copying** (`s08:186-209`). s10, s11 and s12 deep-copy.
4. **The s10 auto-wire is a no-op in practice:** router files live in `project_dir/<phase>/…`, not under `backend_src` (`s10:113-122`). The billing candidate would fail anyway, because it imports `router` but the file exports `billing_router` (`metering_generator.py:215`). p13 memory, p21 and p14 routers are not in the candidate list at all (`s10:58-83`). Note the suffix match `feature_key in f` (`s10:109`).
5. **Delivered ZIP leaves these out:** `s11._build_project_zip` packs only backend and frontend paths (`s11:236-257`), so none of p11a–p21's output is in `project_delivery.zip`.
6. **`domain_ir` is never put in context** (s02 sets only `domain_ir_path`, `s02:150`; no `["domain_ir"] =` assignment anywhere), so p17, p18, p19 and p20 probably always generate for a single stub entity (`resource` or `item`).
7. **p16 role mismatch** (see §3): the Rego falls back to admin/user/viewer while Keycloak gets the p02c roles.
8. **p11a `metadata.grafana_dashboards` is hardcoded to 3** (:383). **p11c `files_written` is hardcoded to 7** (:325).
9. **p14:** `gate.py:11` calls `stat()` without checking the file exists (dead anyway). The quality_score/verdict injection is unescaped HTML (:52-58).

**Bugs in the generated code (the customer's app):**
- **p11c `analytics_service.py`:** `_ph` is never imported (:34). With `POSTHOG_API_KEY` set, `track()` raises `NameError`, which `except ImportError` does not catch.
- **p11c router:** same missing `_ph` (:209, swallowed). The `:d::jsonb` bind is not parsed as a parameter by SQLAlchemy's `text()` (the colon lookahead), so inserts fail silently (:199). It also uses `get_db()` as an async context manager (:197), which conflicts with the usual FastAPI generator dependency.
- **p14 `portal_router.py`:** uses `logger` without defining it (:180, :190). Ticket titles are rendered through `innerHTML` (XSS, :134-141). No auth anywhere, including `/portal/download`.
- **p12a, p12b, p13, p14 routers have no authentication.** The p12b router imports `_EXPERIMENTS` by name, so after `_load()` rebinds the module global its list goes stale (`p12b task_agent.py:109,125`). The p12a seed file `initial_flags.json` is never loaded, because the runtime reads `feature_flags.json`. `is_enabled`'s docstring says it requires rollout==100, but the code doesn't check that (`templates.py:127-140`).
- **p13:** Chroma ids use the per-process salted `hash()`, so ids aren't stable across restarts (:129). A two-key Chroma `where` without `$and` fails on current chromadb, and the error is swallowed (:139-143). pgvector "semantic" search is actually `ILIKE`. The `vector(1536)` and `JSONB` schemas conflict.
- **p16 Rego:**
  - JWT is base64-decoded with no signature check (`iam_generator.py:98-103`), so anyone can forge a role.
  - `package authz.<slug>` is invalid when the slug contains `-`.
  - Bare `allow {` blocks mixed with `if` syntax are rejected by OPA ≥1.0.
  - A dead `allow if { … false }` rule.
- **p17 operator does not compile:**
  - No `api/v1alpha1` package (types, AddToScheme, DeepCopy) is generated.
  - No `go.sum`, but the Dockerfile copies it (:504).
  - `MetricsBindAddress`/`Port` were removed from controller-runtime ≥0.16 (:432-439).
  - An anonymous struct is appended to Conditions (:260-266).
  - The RBAC status block uses `.replace("s","s/status")` on every "s" character, mangling resource names (:331).
  - Plural `kind.lower()+"s"` on already-plural table names gives `employeess` (:61).
- **p18 metering:** prefixes are `/{table}s` (e.g. `/employeess`, :286), so they never match the real `/api/...` routes and metering never fires. `rstrip("s")` strips repeated trailing s's (:326). `create_task` is used without keeping a reference. Stripe actions are TODOs.
- **p19 router:** the nested same-quote f-string (`catalog_generator.py:373`) is a SyntaxError on Python <3.12. Tenant comes from an unverified JWT, with a "default" fallback (cross-tenant risk). `CREATE TYPE` is not idempotent. `backend_lang` is ignored.
- **p20 Terraform:**
  - Global Accelerator and Route53 resources have no provider, while only aliased providers are declared (:201-208, :60-145), so they need a default `aws` provider. Global Accelerator also requires us-west-2.
  - The guide claims a TTL of 60s, but no TTL is set (:410-417).
  - Secondary traffic dial 50% contradicts "failover only".
  - The `hosted_zone_id` parameter is unused.
- **p21:**
  - `python:3.12-slim` has no `kubectl`, so every remediation fails with FileNotFoundError and goes to PagerDuty (`task_agent.py:71-76`, `sre_generators.py:405`).
  - ConfigMaps `<app>-sre-scripts` and `<app>-sre-code` are never generated.
  - PromQL uses a non-standard `http_request_duration_seconds_p95` metric and an `app` label.
  - The "certificate" remediation deletes the TLS secret.
  - The claimed "LLM fallback" does not exist (`sre_generators.py:7, 195`).
- **p11d:** the test script uses Alertmanager `/api/v1/alerts`, removed in AM ≥0.27 (:331). Alertmanager does not expand `${SLACK_WEBHOOK_URL}` (:26). p11a's compose and `prometheus.yml` don't include Alertmanager or an `alerting:` block, so p11d's rules and routing aren't connected to the p11a stack. Duplicate `alert_rules.yml` files exist in p11a and p11d with different rule names (HighP95Latency vs HighLatencyP95).
- **Doc and claim drift:** "Unleash" (p12a), "GrowthBook" (p12b), "mem0" (p13), "structlog" (p11b), "chi_square" (p12b) are all false. The s08 docstring says p11a skips the main.py patch because of p09; the actual guard is the string "Instrumentator", which p09's `add_prometheus_middleware` does not contain, so both can inject (`s08:33-37`).

**Files over 600 lines:** none in scope.

---

## 8. Open questions

1. Does generated backend source ever live at `project_dir/src/main.py` or `project_dir/main.py`? If not, the p11a, p11b and p11c main.py injections never fire (p03 writes `project_dir/src/services`, `p03_scaffolding/task_agent.py:123`, but the p04 backend goes to `project_dir/p04_backend/.../backend`).
2. Does `phase_hooks` merge stage `TaskResult.metadata` into `accumulated_context`, which could supply `domain_ir`, `architecture`, `deployment_config`, `estimated_users`, `scale_tier`? I found no producer for these keys in `stages/` or `orchestrator/`.
3. Are the `project_dir/p1x_*` dirs surfaced to users anywhere (artifact embedding via `artifact_collector.py:55-60` keyed on `results` names, a download API, the gateway file browser)? If not, the whole ops/enterprise plane is invisible to customers.
4. Should `build_profile.architecture` vs `architecture_decisions` be reconciled? p17's internal guard reads only `build_profile` (`p17 task_agent.py:27-31`), while s10 also accepts `architecture_decisions`, so p17 can self-skip after s10 has triggered it.
5. Is anything planned to apply the generated artifacts (deploy the monitoring stack, run the SRE agent) in s09 or p11_deployment? Section 07 should confirm.
6. `generate_cloud_console`, `generate_chaos_package` and `generate_capacity_package` are outside this scope; their status should be confirmed by the section owners.
