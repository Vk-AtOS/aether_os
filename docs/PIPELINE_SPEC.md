# AetherOS Pipeline Specification
**Version:** 1.0  
**Date:** 2026-06-20  
**Status:** Authoritative

---

## 1. Overview

AetherOS is an AI software factory that transforms a natural-language product specification into a
fully deployed, production-ready application. The pipeline is a deterministic sequence of numbered
phases (P00–P20). Each phase receives a `PhaseInput`, performs focused work, writes output
artifacts to disk, and returns a `PhaseResult`. A central orchestrator (`factory_pipeline.py`)
accumulates phase outputs into a shared `accumulated_context` dict that flows into every
subsequent phase.

**Why this document exists:**
- Defines the contract every phase must satisfy so new phases can be added without reading the
  orchestrator source.
- Specifies the `DomainKnowledgePack` plugin interface so third-party domain packs can be
  authored and dropped in without modifying core code.
- Serves as the authoritative reference for artifact schemas so downstream consumers (portals,
  CI systems, compliance tools) can parse run outputs without consulting phase code.

**Pipeline entry point:** `orchestrator/factory_pipeline.py`  
**Phase registry:** `orchestrator/phase_sequence.py`  
**Base dataclasses:** `core/domain_knowledge/base.py`  
**Domain packs:** `core/domain_knowledge/packs/`

---

## 2. Phase Interface Schema

Every phase supervisor class must accept a `PhaseInput` and return a dict that conforms to the
`PhaseResult` shape. Both types are defined in `orchestrator/messages.py`.

### 2.1 PhaseInput (Pydantic model)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PhaseInput",
  "type": "object",
  "required": ["run_id", "project_id", "phase", "output_dir", "client_id"],
  "properties": {
    "run_id":            { "type": "string", "description": "UUID of the factory run" },
    "project_id":        { "type": "string", "description": "UUID of the project" },
    "phase":             { "type": "string", "description": "Phase name (e.g. p04_backend)" },
    "input_data":        {
      "type": "object",
      "description": "Slice of accumulated_context passed to this phase",
      "additionalProperties": true
    },
    "output_dir":        { "type": "string", "description": "Absolute path for phase artifacts" },
    "domain":            { "type": "string", "default": "general" },
    "client_id":         { "type": "string", "description": "Human-readable project slug" },
    "is_change_request": { "type": "boolean", "default": false },
    "change_context":    { "type": ["object", "null"], "default": null },
    "memory_context":    {
      "type": "array",
      "items": { "type": "object" },
      "description": "Relevant past-run memory entries from mem0"
    }
  }
}
```

### 2.2 PhaseResult (Pydantic model)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PhaseResult",
  "type": "object",
  "required": ["run_id", "phase", "status"],
  "properties": {
    "run_id":          { "type": "string" },
    "phase":           { "type": "string" },
    "status":          { "type": "string", "enum": ["passed", "failed", "escalated", "upstream"] },
    "output_path":     { "type": "string", "default": "" },
    "confidence":      { "type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.0 },
    "issues":          { "type": "array", "items": { "type": "string" } },
    "next_phase":      { "type": ["string", "null"] },
    "upstream_route":  { "type": ["string", "null"] },
    "failure_context": { "type": ["object", "null"] },
    "artifacts":       { "type": "object", "additionalProperties": true }
  }
}
```

### 2.3 Orchestrator conventions

- After each phase the orchestrator stores:
  - `accumulated_context["{phase_name}_output"]` = `phase_result["artifacts"]`
  - `accumulated_context["{phase_name}_path"]` = `phase_result["output_path"]`
- Well-known keys listed in the Phase Catalogue (Section 3) are extracted by the orchestrator
  from artifact files and added directly to `accumulated_context` under their canonical name.
- Critical phases (`p01_intake_requirements`, `p02_architecture`, `p02b_domain_ir`,
  `p04_backend`, `p05_frontend`) abort the pipeline on failure. All others log the failure and
  continue.

---

## 3. Phase Catalogue

Columns:
- **phase_id** — directory name and registry key
- **name** — human display name
- **input_keys** — keys the phase reads from `input_data` (subset of `accumulated_context`)
- **output_keys** — keys the phase adds to `accumulated_context` after it runs

| phase_id | name | input_keys | output_keys |
|---|---|---|---|
| p00_research | Research & Spec Analysis | `designer_spec`, `domain`, `user_learning` | `p00_research_output`, `build_profile` |
| p00b_data_archaeology | Data Archaeology | `designer_spec`, `build_profile` | `p00b_data_archaeology_output` |
| p00c_architecture_planner | Architecture Planner | `designer_spec`, `build_profile` | `service_map`, `p00c_architecture_planner_output` |
| p01_intake_requirements | Intake & Requirements | `designer_spec`, `domain`, `build_profile` | `p01_intake_requirements_output` |
| p01b_integration_discovery | Integration Discovery | `p01_intake_requirements_output`, `designer_spec` | `integration_map`, `p01b_integration_discovery_output` |
| p02_architecture | Architecture Design | `p01_intake_requirements_output`, `domain_knowledge`, `build_profile` | `architecture_json`, `p02_architecture_path`, `p02_architecture_output` |
| p02b_domain_ir | Domain IR Generation | `architecture_json`, `domain_knowledge` | `domain_ir_path`, `p02b_domain_ir_output` |
| p02c_permission_modeling | Permission Modeling | `domain_ir_path`, `architecture_json` | `permission_model`, `p02c_permission_modeling_output` |
| p03_scaffolding | Project Scaffolding | `architecture_json`, `build_profile`, `client_id` | `p03_scaffolding_output` |
| p04_backend | Backend Codegen | `architecture_json`, `domain_ir_path`, `domain_knowledge`, `build_profile`, `integration_map` | `backend_src_dir`, `backend_main_py`, `api_routes_path`, `p04_backend_output` |
| p04b_business_logic | Business Logic Layer | `backend_src_dir`, `domain_knowledge`, `architecture_json` | `applied_patterns`, `p04b_business_logic_output` |
| p04c_integration_codegen | Integration Clients | `integration_map`, `backend_src_dir` | `p04c_integration_codegen_output` |
| p05_frontend | Frontend Codegen | `backend_src_dir`, `architecture_json`, `domain_knowledge`, `build_profile` | `p05_frontend_output` |
| p05b_mobile | Mobile (React Native) | `architecture_json`, `build_profile` | `p05b_mobile_output` |
| p05c_desktop | Desktop (Electron) | `architecture_json`, `build_profile` | `p05c_desktop_output` |
| p05d_cli | CLI Tool | `architecture_json`, `build_profile` | `p05d_cli_output` |
| p05e_serverless | Serverless Functions | `architecture_json`, `build_profile` | `p05e_serverless_output` |
| p06_review_security | Security Review | `backend_src_dir`, `domain_knowledge`, `permission_model` | `council_review`, `council_feedback`, `p06_review_security_output` |
| p07_testing | Test Generation | `backend_src_dir`, `architecture_json`, `domain_knowledge` | `p07_testing_output` |
| p07b_self_healing | Self-Healing | `backend_src_dir`, `council_feedback`, `p07_testing_output` | `backend_src_dir`, `backend_main_py`, `p07b_self_healing_output` |
| p08_cicd_deployment | CI/CD Pipeline | `backend_src_dir`, `architecture_json`, `build_profile` | `p08_cicd_deployment_output` |
| p09_observability | Observability Config | `backend_src_dir`, `build_profile` | `p09_observability_output` |
| p10_docs_delivery | Documentation | `architecture_json`, `backend_src_dir`, `domain_knowledge` | `p10_docs_delivery_output` |
| p11_deployment | Docker Build & Deploy | `backend_src_dir`, `client_id`, `run_id` | `live_url`, `p11_deployment_output` |
| p11a_monitoring | Prometheus + Grafana | `live_url`, `build_profile` | `p11a_monitoring_output` |
| p11b_error_tracking | Sentry + structlog | `backend_src_dir`, `live_url` | `p11b_error_tracking_output` |
| p11c_analytics | PostHog Analytics | `live_url`, `client_id` | `p11c_analytics_output` |
| p11d_alerting | Alertmanager + Runbooks | `live_url`, `build_profile` | `p11d_alerting_output` |
| p11e_enterprise_deployment | Enterprise Deploy (Helm/TF) | `architecture_json`, `build_profile`, `service_map` | `p11e_enterprise_deployment_output` |
| p12a_feature_flags | Feature Flags (Unleash) | `backend_src_dir`, `architecture_json` | `p12a_feature_flags_output` |
| p12b_ab_testing | A/B Testing (GrowthBook) | `backend_src_dir`, `live_url` | `p12b_ab_testing_output` |
| p13_app_memory | App Memory Layer (mem0) | `backend_src_dir`, `architecture_json` | `graph_context`, `knowledge_graph_path`, `p13_app_memory_output` |
| p14_client_portal | Client Review Portal | `p10_docs_delivery_output`, `live_url`, `run_id` | `p14_client_portal_output` |
| p15_handoff | Technical Handoff Package | `architecture_json`, `backend_src_dir`, `live_url`, `council_review` | `p15_handoff_output` |
| p16_iam | IAM / OPA Policies | `permission_model`, `architecture_json`, `build_profile` | `p16_iam_output` |
| p17_control_plane | K8s Operator + CRDs | `service_map`, `architecture_json`, `build_profile` | `p17_control_plane_output` |
| p18_billing_metering | Billing & Metering | `architecture_json`, `build_profile` | `p18_billing_metering_output` |
| p19_service_catalog | Service Catalog UI | `service_map`, `architecture_json` | `p19_service_catalog_output` |
| p20_multiregion | Multi-Region Deploy | `p11e_enterprise_deployment_output`, `build_profile` | `p20_multiregion_output` |

---

## 4. Domain Pack Plugin Standard

A domain pack is a Python module in `core/domain_knowledge/packs/` that exports a module-level
`PACK` variable of type `DomainKnowledgePack`. The orchestrator discovers packs by matching the
`domain` field against the domain value in `PhaseInput`.

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
| `workflows` | `List[WorkflowTemplate]` | `[]` | State machines injected into P04 backend prompt |
| `compliance` | `List[ComplianceRule]` | `[]` | Compliance rules for P06 security review |
| `api_patterns` | `List[str]` | `[]` | REST endpoint examples injected into P02 architecture |
| `pipelines` | `List[BusinessProcessPipeline]` | `[]` | Process orchestration flows for P04b business logic |

### 4.3 EntityTemplate validation rules

- `name`: PascalCase, unique within the pack
- `table`: snake_case, must be a valid SQL identifier
- `fields`: at least one field; first field should be the primary business key
- `audit_trail = True`: required if the entity contains any `phi=True`, `pci=True`, or `pii=True` field
- `soft_delete = True`: recommended for any entity that has foreign-key dependents

### 4.4 FieldDef validation rules

- `type` must be one of: `string | int | float | bool | datetime | fk | text`
- `phi=True` implies `encrypted_at_rest=True` (enforced by P06 security review)
- `pci=True` implies `encrypted_at_rest=True`
- `never_store=True` — field is documented but must not appear in any INSERT/SELECT; use for
  raw card data, CVV, or other data that must stay out of the database entirely

### 4.5 WorkflowTemplate validation rules

- `states`: all values referenced in `transitions` keys and values must appear here
- `terminal_states`: must be a subset of `states`; must have no outbound transitions
- `transitions`: every non-terminal state must have at least one allowed target

### 4.6 ComplianceRule enforcement values

| Value | Meaning |
|---|---|
| `mandatory` | P06 security review FAILS if the rule is violated in generated code |
| `recommended` | P06 logs a warning; pipeline continues |

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
1. Tracking numbers are globally unique — enforce a UNIQUE constraint.
2. Shipment status transitions are append-only; use an event log, not status updates.
""",
)
```

### 4.8 Pack registration

Drop the file in `core/domain_knowledge/packs/` and register it in
`core/domain_knowledge/loader.py` (or the pack auto-discovery function if present). The domain
slug in `PACK.domain` must exactly match the classifier output for the domain routing to work.

---

## 5. BusinessProcessPipeline Standard

A `BusinessProcessPipeline` describes an ordered, orchestrated sequence of service calls,
state transitions, and notifications that implement a business workflow. Pipelines are attached
to a `DomainKnowledgePack` and consumed by the P04b business logic phase to emit service
orchestration code rather than bare CRUD endpoints.

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
| `name` | `str` | — | snake_case, unique within the pipeline |
| `action_type` | `str` | — | `service_call \| state_transition \| notification \| external_api \| batch \| schedule` |
| `service` | `str` | — | Service class or entity name |
| `method` | `str` | — | Method to invoke |
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

## 6. Artifact Standards

The orchestrator and portal consumers expect the following artifact files in each run's output
directory. All artifacts are JSON unless noted.

### 6.1 `domain_knowledge.json`

Produced by: `DomainKnowledgePack.to_dict_full()`  
Written by: artifact collector after P01 domain resolution

```json
{
  "domain": "string",
  "display_name": "string",
  "version": "1.0",
  "entities": [
    {
      "name": "string",
      "table": "string",
      "description": "string",
      "audit_trail": "boolean",
      "soft_delete": "boolean",
      "indexes": ["string"],
      "fields": [
        {
          "name": "string",
          "type": "string",
          "required": "boolean",
          "pii": "boolean",
          "phi": "boolean",
          "pci": "boolean",
          "encrypted_at_rest": "boolean",
          "never_store": "boolean",
          "description": "string"
        }
      ]
    }
  ],
  "workflows": [
    {
      "name": "string",
      "entity": "string",
      "field": "string",
      "states": ["string"],
      "transitions": { "state": ["string"] },
      "terminal_states": ["string"],
      "description": "string"
    }
  ],
  "compliance": [
    {
      "standard": "string",
      "rule": "string",
      "affected_fields": ["string"],
      "enforcement": "mandatory | recommended",
      "implementation_hint": "string"
    }
  ],
  "api_patterns": ["string"],
  "pipelines": [
    {
      "name": "string",
      "trigger": "string",
      "trigger_entity": "string",
      "trigger_condition": "string",
      "description": "string",
      "services_required": ["string"],
      "integrations_required": ["string"],
      "steps": [
        {
          "name": "string",
          "action_type": "string",
          "service": "string",
          "method": "string",
          "input_mapping": { "key": "path" },
          "on_success": "string",
          "on_failure": "string",
          "compensation": "string",
          "timeout_seconds": "integer",
          "retry_count": "integer",
          "description": "string"
        }
      ]
    }
  ],
  "prompt_injection": "string"
}
```

### 6.2 `compliance_manifest.json`

Produced by: P06 security review  
Purpose: Machine-readable compliance gate result consumed by the client portal

```json
{
  "run_id": "string (UUID)",
  "generated_at": "string (ISO-8601)",
  "standards": ["PCI-DSS", "HIPAA", "GDPR"],
  "overall_status": "pass | fail | partial",
  "rules": [
    {
      "standard": "string",
      "rule": "string",
      "enforcement": "mandatory | recommended",
      "status": "pass | fail | not_applicable",
      "evidence": "string",
      "remediation": "string"
    }
  ],
  "pii_fields_found": ["Entity.field_name"],
  "phi_fields_found": ["Entity.field_name"],
  "pci_fields_found": ["Entity.field_name"],
  "encryption_verified": "boolean",
  "audit_trail_verified": "boolean"
}
```

### 6.3 `business_model.json`

Produced by: P00 research phase  
Purpose: Structured product spec consumed by P01 and P02

```json
{
  "project_name": "string",
  "domain": "string",
  "build_type": "web_app | microservice | mobile | desktop | cli | ml_pipeline",
  "architecture": "monolith | microservices | serverless | event_driven",
  "target_users": ["string"],
  "core_entities": ["string"],
  "key_workflows": ["string"],
  "integrations_needed": ["string"],
  "compliance_requirements": ["string"],
  "non_functional_requirements": {
    "max_response_ms": "integer",
    "target_concurrent_users": "integer",
    "uptime_sla": "string"
  }
}
```

---

## 7. Extension Points

Third-party phases or domain-specific customisations can be inserted at three defined
extension points. Inserting at other positions may break accumulated_context dependencies.

### 7.1 pre-P00 — Stack classification hooks

**Insert before:** `p00_research`  
**Use case:** Custom intent classifiers, domain auto-detectors, enterprise intake forms  
**Required outputs added to accumulated_context:** `designer_spec`, optionally `build_profile`  
**Constraint:** Must not require any accumulated_context keys (nothing has run yet)

### 7.2 post-P15 — Post-delivery add-ons

**Insert after:** `p15_handoff`  
**Use case:** Custom compliance exporters, third-party audit integrations, CRM notification hooks  
**Available accumulated_context keys:** all well-known keys from P00–P15  
**Constraint:** Must not modify `backend_src_dir` or any code artifact — P11 deployment has
already run

### 7.3 post-P20 — Cloud platform extensions

**Insert after:** `p20_multiregion`  
**Use case:** Proprietary cloud provisioning, custom cost-reporting, enterprise SSO wiring  
**Available accumulated_context keys:** all keys from P00–P20  
**Constraint:** Phases here are always skipped (`status = "passed"` with empty artifacts) for
non-kubernetes builds; check `build_profile.architecture == "kubernetes"` before doing work

### 7.4 Registering an extension phase

1. Create `phases/<your_phase>/supervisor_agent.py` with a `YourPhaseSupervisor` class
   implementing `async def run(self, phase_input: PhaseInput) -> dict`.
2. Add the phase name to `PHASE_SEQUENCE` in `orchestrator/phase_sequence.py` at the correct
   position.
3. Add the class path to `PHASE_SUPERVISORS` in `orchestrator/phase_sequence.py`.
4. Mark the phase as non-critical unless pipeline abortion on its failure is intentional.

---

## 8. Summary: Conformance Checklist

A domain pack is conforming when all of the following are true:

- [ ] `PACK.domain` is a lowercase slug with no spaces
- [ ] `PACK.display_name` is non-empty
- [ ] `PACK.entities` has at least one `EntityTemplate`
- [ ] `PACK.prompt_injection` is non-empty and domain-specific
- [ ] Every entity with `phi=True` or `pci=True` fields has `audit_trail=True`
- [ ] Every `phi=True` or `pci=True` field has `encrypted_at_rest=True`
- [ ] All `WorkflowTemplate.terminal_states` have no outbound transitions
- [ ] All `ComplianceRule.enforcement` values are `"mandatory"` or `"recommended"`
- [ ] Every `BusinessProcessPipeline.steps` list is non-empty
- [ ] Every `ProcessStep.on_success` is either a valid step name within the pipeline or `"END"`
- [ ] `PACK.to_dict_full()` returns a JSON-serialisable dict (no non-primitive types)
