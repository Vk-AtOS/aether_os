# AetherOS Pipeline Specification

Checked against the code at commit `e5c23fd`. Where a statement could not be confirmed in code it says
"not verified" or "not measured".

## 1. Overview

A run goes through 12 stages in a fixed order. The order is `PHASE_SEQUENCE` in
`orchestrator/phase_sequence.py:90-103`: `s01_intake`, `s02_architecture`, `s03_backend`, `s04_frontend`,
`s05_quality`, `s06_testing`, `s07_healing`, `s08_observability`, `s09_devops`, `s10_enterprise`, `s11_handoff`,
`s12_specialist`. A stage supervisor (`stages/sNN_*/supervisor.py`, mapped in `PHASE_SUPERVISORS`,
`phase_sequence.py:108-121`) calls the phase agents that live in `phases/`. Earlier versions of this file said the
pipeline was phases P00 to P20; that is no longer the structure.

The orchestrator is `orchestrator/factory_pipeline.py`. After each stage it stores
`accumulated_context["{stage}_output"]` and `accumulated_context["{stage}_path"]`
(`factory_pipeline.py:629-630`) and saves a checkpoint. Stages can run in parallel waves
(`orchestrator/parallel_runner.py`, `phase_dag.py`); the wave plan itself was not reviewed here.

Other code locations: base dataclasses `core/domain_knowledge/base.py`; domain packs
`core/domain_knowledge/packs/`; stage rules `orchestrator/stage_gate.py`.

## 2. Phase interface

`PhaseInput` and `PhaseResult` are Pydantic models in `orchestrator/messages.py:8-31`. The JSON Schema blocks
that used to be here matched them field for field and are replaced by this list.

PhaseInput: `run_id`, `project_id`, `phase`, `input_data` (dict), `output_dir`, `client_id` (all required except
`input_data`), `domain` (default `general`), `is_change_request` (default false), `change_context` (optional dict),
`memory_context` (list of dicts).

PhaseResult: `run_id`, `phase`, `status` (`passed`, `failed`, `escalated` or `upstream`), `output_path`,
`confidence` (0.0 to 1.0 by convention; not range-checked), `issues`, `next_phase`, `upstream_route`,
`failure_context`, `artifacts` (dict).

Phase agents themselves extend `PhaseBase` (`phases/base.py`) and return a `TaskResult` with `success`,
`escalated`, `output_path`, `confidence`, `issues`, `metadata`. Retry policy: `max_retries = 3` by default
(`phases/base.py:46`). A gate that still fails after the retries gives `escalated`.

### Which stages abort the run

`CRITICAL_PHASES` is `s01_intake`, `s02_architecture`, `s03_backend` (`phase_sequence.py:22-26`). For every
stage an `escalated` result (gate failed after retries) ends the run (`orchestrator/stage_gate.py:
gate_block_reason`). A `failed` or timed-out non-critical stage does not end the run.

## 3. Phase catalogue

`phases/` holds 49 directories named `pNN_*`, a `patterns/` directory (shared code) and `utils.py`. None of the `pNN_*` directories is in `PHASE_SEQUENCE`. They are all listed in `INACTIVE_PHASE_DIRS`
(`phase_sequence.py:46-71`), which is a reference list for the stage supervisors, not a list of unused phases.
Inputs and outputs below are the ones the stage supervisor's docstring gives for the stage; per-phase inputs and
outputs were not read in every phase's code, so the columns are by stage. Which sub-steps ran in a real run:
not measured.

### Stage inputs and outputs (from `stages/*/supervisor.py` docstrings)

| Stage | Phases called | Reads | Writes |
|-------|---------------|-------|--------|
| s01_intake | p00_research, p00b_data_archaeology, p00c_architecture_planner (parallel); p01_intake_requirements, p01b_integration_discovery | `raw_input`, `domain`, `autonomous_mode`, `build_profile` | `requirements`, `entities`, `api_endpoints`, `integration_map`, `design_brief`, `similar_past_runs`, `project_contract`, `service_map`, `user_personas`, `user_roles` |
| s02_architecture | p02_architecture, p02b_domain_ir, p02c_permission_modeling, p03_scaffolding (sequential) | `requirements`, `entities`, `domain`, `project_contract`, `service_map` | `architecture_json`, `architecture_warnings`, `domain_ir`, `domain_ir_path`, `permission_model`, `project_scaffold` |
| s03_backend | p04_backend (calls p04a_backend_codegen and p04_uiux_design), p04b_business_logic, p04c_integration_codegen, architecture governor | `domain_ir`, `permission_model`, `integration_map`, `architecture_decisions`, `project_contract`, `domain`, `stack_profile` | `backend_output_path`, `api_routes`, `seed_entities`, `integration_clients`, `design_tokens`, `governor_report` |
| s04_frontend | p05_frontend; conditional p05b_mobile, p05c_desktop, p05d_cli, p05e_serverless | `domain_ir`, `design_tokens`, `backend_output_path`, `user_personas`, `build_profile`, `api_endpoints` | `frontend_output_path`, `frontend_framework`, `component_count` |
| s05_quality | p06_review_security and p06b_formal_verification (parallel), then dimension scorer | `backend_output_path`, `frontend_output_path`, `domain_ir`, `permission_model` | `compliance_score`, `compliance_pdf_path`, `verification_report`, `dimension_critique`, `security_findings`, `quality_gate_passed` |
| s06_testing | p07a_unit_testing now; p07b_performance_testing, p07c_accessibility_testing, p07d_e2e_testing are deferred to s07 | `backend_output_path`, `frontend_output_path`, `backend_port`, `frontend_url` | `test_results`, `perf_results`, `a11y_results`, `e2e_results`, `test_quality_flag`, `consolidated_report` |
| s07_healing | p07b_self_healing, plus the deferred live tests | `backend_output_path`, `test_results`, `dimension_critique`, `security_findings`, `domain_ir` | `self_healing_report`, `healing_passed`, `repairs_applied`, `error_patterns`, `auto_validators` |
| s08_observability | p09_observability, then p11a_monitoring, p11b_error_tracking, p11c_analytics (parallel), then p11d_alerting | `backend_output_path`, `healing_passed`, `domain`, `project_name` | `monitoring_path`, `prometheus_config`, `grafana_dashboards`, `sentry_configured`, `analytics_events`, `alert_rules_count` |
| s09_devops | p08_cicd_deployment, p11_deployment, p11e_enterprise_deployment (conditional) | `backend_output_path`, `frontend_output_path`, `healing_passed`, `architecture_decisions`, `project_name`, `build_profile` | `dockerfile_path`, `ci_workflow_path`, `helm_chart_path`, `terraform_path`, `live_url`, `backend_port`, `k8s_manifests` |
| s10_enterprise | p12a_feature_flags, p12b_ab_testing, p13_app_memory, p16_iam, p18_billing_metering, p21_sre_agent (parallel); p17_control_plane (conditional) | `backend_output_path`, `permission_model`, `architecture_decisions`, `healing_passed` | `feature_flags_path`, `ab_testing_path`, `memory_service_path`, `iam_policies_path`, `billing_path`, `k8s_operator_path`, `sre_agent_path` |
| s11_handoff | p10_docs_delivery; then p14_client_portal and p15_handoff (parallel) | `backend_output_path`, `frontend_output_path`, `project_name`, `domain`, `healing_passed`, `test_results`, `compliance_score`, `dimension_critique`, `governor_report` | `readme_path`, `api_reference_path`, `architecture_doc_path`, `deployment_guide_path`, `postman_collection_path`, `client_portal_path`, `export_manifest_path`, `quality_report_path` |
| s12_specialist | p05b_mobile, p05c_desktop, p05d_cli, p05e_serverless, p19_service_catalog, p20_multiregion (all conditional, parallel) | `build_profile`, `backend_output_path`, `domain_ir` | `mobile_output_path`, `desktop_output_path`, `cli_output_path`, `serverless_path`, `service_catalog_path`, `multiregion_path`, `specialist_outputs` |

Conditions for the conditional phases are in the supervisor docstrings (for example p05b runs only when
`build_profile.frontend_framework == "react_native"`; p17 only for kubernetes or microservice or event-driven
builds). Note that p05b to p05e are listed under both s04 and s12.

### Phase directories (`ls phases/`)

| Directory | Called by |
|-----------|-----------|
| p00_research, p00b_data_archaeology, p00c_architecture_planner, p01_intake_requirements, p01b_integration_discovery | s01 |
| p02_architecture, p02b_domain_ir, p02c_permission_modeling, p03_scaffolding | s02 |
| p04_backend, p04a_backend_codegen, p04b_business_logic, p04c_integration_codegen | s03 |
| p04_uiux_design | `phases/p04_backend/task_agent.py:396` (inside p04), not by a stage supervisor |
| p05_frontend, p05b_mobile, p05c_desktop, p05d_cli, p05e_serverless | s04 and s12 |
| p06_review_security, p06b_formal_verification | s05 |
| p07a_unit_testing | s06 |
| p07b_performance_testing, p07c_accessibility_testing, p07d_e2e_testing | s06 docstring says deferred; run from s07 |
| p07b_self_healing | s07 |
| p07_testing | not called by a stage supervisor; it delegates to p07a to p07d (`phases/p07_testing/task_agent.py:15-18`) and is referenced by `orchestrator/phase_hooks.py` |
| p08_cicd_deployment | s09; it wraps p08_cicd |
| p08_cicd | called through p08_cicd_deployment (`phases/p08_cicd_deployment/task_agent.py:17`) |
| p09_observability, p11a_monitoring, p11b_error_tracking, p11c_analytics, p11d_alerting | s08 |
| p09_documentation | alias directory: its `gate.py` re-exports `p10_docs_delivery.gate`; not called by a stage |
| p10_docs_delivery, p14_client_portal, p15_handoff | s11 |
| p11_deployment, p11e_enterprise_deployment | s09 |
| p12a_feature_flags, p12b_ab_testing, p13_app_memory, p16_iam, p17_control_plane, p18_billing_metering, p21_sre_agent | s10 |
| p19_service_catalog, p20_multiregion | s12 |

Directories that exist but are not in the sequence and not called by a stage supervisor: p04_uiux_design (called
inside p04), p07_testing, p09_documentation, and p08_cicd (reached only through its wrapper).

### p06b_formal_verification report

p06b writes `formal_verification_report.json` (not `verification_report.json`) to its output directory and to the
project root (`phases/p06b_formal_verification/task_agent.py:279`, `:170-172`). Schema version `1.0`
(`task_agent.py:33`). Fields (`task_agent.py:136-153`): `schema_version`, `verified_at`, `z3_version`,
`z3_available`, `project_name`, `domain`, `files_scanned`, `overall_verdict` (`PASS`, `FAIL` or `PARTIAL`),
`confidence_score` (verified count divided by total), `z3_solver_time_ms`, `invariants_verified`,
`invariants_failed`, `invariants_unverifiable` (lists of entries with `invariant_id`, `invariant_name`, `route`,
`status`, `proof_method`, `solver_time_ms`, `confidence`, and `violation_detail` when present), and
`partial_reason` when set. The gate blocks only on `FAIL`; `PARTIAL` passes with a warning
(`phases/p06b_formal_verification/gate.py:1-12`). The `verification_report` dict in the s05 context is a
shorter summary built by `stages/s05_quality/supervisor.py:362-380`, not this file.

---

## 4. Domain Pack Plugin Standard

A domain pack is a Python module in `core/domain_knowledge/packs/` that exports a module-level
`PACK` variable of type `DomainKnowledgePack` (`core/domain_knowledge/base.py:121`). `load_pack(domain)` looks the
domain name up in `_DOMAIN_PACK_MAP` and imports that module. Existing packs: ecommerce, edtech, erp, fintech,
govtech, healthcare, legaltech, logistics, manufacturing, real_estate, saas, trading.

The rules in 4.1 to 4.6 are conventions written by the pack authors. The dataclasses do not validate them, and
the review of `phases/p06_review_security` and `stages/s05_quality` found no code that enforces
`encrypted_at_rest`, `never_store` or `audit_trail`. Treat them as guidance, not as checks.

### 4.1 Required fields

| Field | Type | Rule |
|---|---|---|
| `domain` | `str` | Lowercase slug matching the domain classifier output (e.g. `"healthcare"`, `"fintech"`) |
| `display_name` | `str` | Human-readable name for UI and logs |
| `entities` | `List[EntityTemplate]` | At least one entity required |
| `prompt_injection` | `str` | Non-empty string; injected verbatim into every LLM call for this domain |

### 4.2 Optional fields

| Field | Type | Default | Purpose |
|---|---|---|---|
| `workflows` | `List[WorkflowTemplate]` | `[]` | State machines for the backend prompt (consumer not verified) |
| `compliance` | `List[ComplianceRule]` | `[]` | Compliance rule text; `compliance_summary()` lists it for the p06 prompt |
| `api_patterns` | `List[str]` | `[]` | REST endpoint examples (consumer not verified) |
| `pipelines` | `List[BusinessProcessPipeline]` | `[]` | Process flows (consumer not verified) |

### 4.3 EntityTemplate validation rules

- `name`: PascalCase, unique within the pack
- `table`: snake_case, must be a valid SQL identifier
- `fields`: at least one field; first field should be the primary business key
- `audit_trail = True`: required if the entity contains any `phi=True`, `pci=True`, or `pii=True` field
- `soft_delete = True`: recommended for any entity that has foreign-key dependents

### 4.4 FieldDef validation rules

- `type` must be one of: `string | int | float | bool | datetime | fk | text`
- `phi=True` implies `encrypted_at_rest=True` (convention; no enforcing code found)
- `pci=True` implies `encrypted_at_rest=True`
- `never_store=True` - field is documented but must not appear in any INSERT/SELECT; use for
  raw card data, CVV, or other data that must stay out of the database entirely

### 4.5 WorkflowTemplate validation rules

- `states`: all values referenced in `transitions` keys and values must appear here
- `terminal_states`: must be a subset of `states`; must have no outbound transitions
- `transitions`: every non-terminal state must have at least one allowed target

### 4.6 ComplianceRule enforcement values

| Value | Meaning |
|---|---|
| `mandatory` | default value of `ComplianceRule.enforcement` (`base.py:50-56`) |
| `recommended` | the other documented value |

How p06 uses `enforcement`: not verified. `compliance_summary()` only lists `[standard] rule` text in the p06 prompt (`base.py:212`).

### 4.7 Minimal conforming pack example

```python
# core/domain_knowledge/packs/logistics.py
from aether_os.core.domain_knowledge.base import (
    DomainKnowledgePack, EntityTemplate, FieldDef
)

PACK = DomainKnowledgePack(
    domain="logistics",
    display_name="Logistics / Supply Chain",
    entities=[
        EntityTemplate(
            name="Shipment", table="shipments",
            description="A physical package in transit",
            fields=[
                FieldDef("tracking_number", "string"),
                FieldDef("origin", "string"),
                FieldDef("destination", "string"),
                FieldDef("status", "string"),
            ],
            indexes=["tracking_number", "status"],
            audit_trail=False, soft_delete=True,
        ),
    ],
    prompt_injection="""LOGISTICS DOMAIN RULES:
1. Tracking numbers are globally unique - enforce a UNIQUE constraint.
2. Shipment status transitions are append-only; use an event log, not status updates.
""",
)
```

### 4.8 Pack registration

Drop the file in `core/domain_knowledge/packs/` and add the domain name (and any aliases) to
`_DOMAIN_PACK_MAP` in `core/domain_knowledge/loader.py:20-45`. There is no auto-discovery: a pack file that is
not in that map is never loaded. `load_pack` returns `None` for a domain with no entry (for example `general`).

---

## 5. BusinessProcessPipeline Standard

A `BusinessProcessPipeline` describes an ordered, orchestrated sequence of service calls,
state transitions, and notifications that implement a business workflow. Pipelines are attached
to a `DomainKnowledgePack` and described in the dataclass docstring (`base.py:76-91`) as input to the backend generator. Which phase consumes `pipelines`: not verified.

### 5.1 Pipeline fields

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | Yes | PascalCase, unique within the pack |
| `trigger` | `str` | Yes | `user_action \| event \| schedule \| webhook \| state_transition` |
| `trigger_entity` | `str` | Yes | EntityTemplate name that owns the trigger |
| `trigger_condition` | `str` | Yes | Human-readable condition (e.g. `"status transitions to 'completed'"`) |
| `steps` | `List[ProcessStep]` | Yes | Ordered list; must be non-empty |
| `services_required` | `List[str]` | Recommended | Service class names the pipeline expects to exist |
| `integrations_required` | `List[str]` | Recommended | External integrations (e.g. `"stripe"`, `"sendgrid"`) |
| `description` | `str` | No | Human-readable summary |

### 5.2 ProcessStep fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | - | snake_case, unique within the pipeline |
| `action_type` | `str` | - | `service_call \| state_transition \| notification \| external_api \| batch \| schedule` |
| `service` | `str` | - | Service class or entity name |
| `method` | `str` | - | Method to invoke |
| `input_mapping` | `Dict[str,str]` | `{}` | Maps step inputs to context paths (e.g. `"entity.patient_id"`) |
| `on_success` | `str` | `""` | Next step name, or `"END"` to terminate the pipeline |
| `on_failure` | `str` | `"FAIL"` | `"FAIL"` aborts; `"SKIP"` continues to `on_success` target |
| `compensation` | `str` | `""` | Rollback method name for saga-style compensation |
| `timeout_seconds` | `int` | `30` | Per-step timeout; external API steps should increase this |
| `retry_count` | `int` | `3` | Retry attempts before triggering `on_failure` path |
| `description` | `str` | `""` | Single sentence explaining the step's purpose |

### 5.3 action_type semantics

| action_type | Generated code pattern |
|---|---|
| `service_call` | Synchronous call to an internal service method |
| `state_transition` | Updates entity status field through the WorkflowTemplate state machine |
| `notification` | Async task dispatched to notification service; `on_failure=SKIP` is idiomatic |
| `external_api` | HTTP call to a third-party API; always set `timeout_seconds` and `retry_count` |
| `batch` | Queues work for a scheduled batch processor |
| `schedule` | Registers a future job with the scheduler service |

### 5.4 input_mapping path syntax

| Prefix | Resolves to |
|---|---|
| `entity.<field>` | Field on the trigger entity instance |
| `steps.<step_name>.<key>` | Output key from a previous step's result |
| `context.<key>` | Key from the run's `accumulated_context` |
| `'literal'` | String literal (wrap in single quotes) |

---

## 6. Artifact files

These files are written by code. Earlier versions of this file listed schemas that did not match the code; the
schemas below come from the writers.

### 6.1 `domain_knowledge.json`

Written by p06_review_security into the project directory when `load_pack(domain)` finds a pack
(`phases/p06_review_security/subtasks.py:346-356`). Content is `DomainKnowledgePack.to_dict_full()`
(`core/domain_knowledge/base.py:148-210`): `domain`, `display_name`, `version` (`"1.0"`), `entities` (name,
table, description, `audit_trail`, `soft_delete`, `indexes`, `fields` with `name`, `type`, `required`, `pii`,
`phi`, `pci`, `encrypted_at_rest`, `never_store`, `description`), `workflows` (name, entity, field, states,
transitions, terminal_states, description), `compliance` (standard, rule, affected_fields, enforcement,
implementation_hint), `api_patterns`, `pipelines` (see section 5) and `prompt_injection`. No file is written for a
domain with no pack.

### 6.2 `compliance_manifest.json`

Written into the generated project root by p06 (`phases/p06_review_security/manifest.py:20-111`) and by
`core/compliance/manifest_writer.py:83-161`. It is the result of a code scan of the generated `main.py`, not a
per-standard pass or fail list. Fields: `schema_version` (`"1.0"`), `generated_at`, `project_name`, `domain`,
`overall_score` (from the scanner), `drift_fingerprint` (SHA-256 of the route-bearing `.py` files),
`framework_versions` (a fixed map: HIPAA 2024, GDPR 2018, PCI-DSS 4.0, SOC2 2017), and `components`: one entry
per route with `file`, `route`, `has_auth`, `has_audit_log`, `has_input_validation`, `has_rate_limiting`,
`rules_satisfied`, `rules_violated` (each with `id`, `name`; violated ones add `severity` and `remediation`).
The old fields `standards`, `overall_status`, `rules`, `pii_fields_found`, `encryption_verified` do not exist in
the code. The manifest does not state compliance with any standard.

### 6.3 `business_model.json`

Written by p00_research (`phases/p00_research/business_model_generator.py:86-134`) from an LLM answer, or from a
fixed fallback when the answer is missing or not valid JSON. Keys: `target_market`, `problem_statement`,
`value_proposition`, `revenue_model`, `pricing_tiers`, `tam_usd_billions`, `sam_usd_billions`,
`som_usd_millions`, `tam_source`, `competitive_landscape`, `go_to_market`, `gtm_detail`, `unit_economics`
(`estimated_cac_usd`, `estimated_ltv_usd`, `ltv_cac_ratio`, `payback_months`), `key_risks`,
`compliance_requirements`, plus `domain` and `generated_by` added by the code. The old schema in this file
(`project_name`, `build_type`, `core_entities`, `non_functional_requirements`) was not what the code writes.
The market and economics numbers are model output, not data.

### 6.4 `formal_verification_report.json`

See section 3.

---

## 7. Extension points

The old text named three insertion points (before P00, after P15, after P20) in a P00 to P20 sequence. That
sequence no longer exists, and no extension mechanism for third-party phases was found in the code. To add a
phase today:

1. Create `phases/<name>/` with `task_agent.py`, `gate.py` and a supervisor class that extends `PhaseBase`.
2. Call it from the stage supervisor that should own it (`stages/sNN_*/supervisor.py`). Stages are not
   loaded from configuration.
3. Add the name to `INACTIVE_PHASE_DIRS` in `orchestrator/phase_sequence.py` only if you want it listed there; the
   set is documentation for the supervisors.
4. To add a whole new stage, add it to `PHASE_SEQUENCE` and `PHASE_SUPERVISORS`, and decide whether it belongs in
   `CRITICAL_PHASES` (`phase_sequence.py:22`) and `MANDATORY_STAGES` (`orchestrator/stage_gate.py`).

A claim in the old text that phases after P20 are skipped for non-kubernetes builds has no code behind it:
conditions live in each supervisor (section 3).

## 8. Domain pack checklist

A pack follows the conventions above when:

- `PACK.domain` is a lowercase slug and is listed in `_DOMAIN_PACK_MAP`
- `PACK.display_name` is non-empty and `PACK.entities` has at least one entity
- `PACK.prompt_injection` is non-empty
- entities with `phi` or `pci` fields set `audit_trail=True`, and those fields set `encrypted_at_rest=True`
- workflow `terminal_states` have no outbound transitions
- `ComplianceRule.enforcement` is `"mandatory"` or `"recommended"`
- every pipeline has at least one step, and every `on_success` is a step name in that pipeline or `"END"`
- `PACK.to_dict_full()` returns a JSON-serialisable dict

None of these is checked by code at load time (`load_pack` only imports the module and reads `PACK`).
