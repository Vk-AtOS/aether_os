"""
P02b Task Agent — 4-pass Domain IR extraction.

Runs after p02 (architecture). Produces domain_ir.json which all downstream
phases (p04a, p05) consume for deterministic code generation.

Four focused LLM calls, each narrower than a single all-in-one extraction:
  Pass 1 — Entity + Field extraction
  Pass 2 — Relationship extraction
  Pass 3 — Business rules + permissions extraction
  Pass 4 — Consistency review + gap fill

The IR is then validated by IRValidator before being written to disk.
If any field has confidence < CONFIDENCE_THRESHOLD a clarifying question
is added; the pipeline pauses and surfaces these to the user via the
Project Designer UI before continuing.

Backward compatibility: if architecture.json already contains a rich
database_schema, entity names are seeded into Pass 1 so the LLM stays
grounded.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, List

from aether_os.core.llm.client import get_llm_client
from aether_os.core.domain_ir import (
    DomainIR, IREntity, IRField, IRRelationship, IRBusinessRule,
    IRPermission, IRWorkflow, IRWorkflowStep, IRDashboardMetric,
    IRNotification, IRClarifyingQuestion, AetherType,
)

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.6

# Words that should never be treated as business entities
_GARBAGE_ENTITY_NAMES = frozenset({
    # Python reserved keywords
    "none", "true", "false", "and", "or", "not", "in", "is", "if", "else",
    "for", "while", "def", "class", "return", "import", "from", "with",
    # Tech stack / framework terms (must not become DB tables)
    "frontend", "backend", "stack", "tech", "specification", "tailwind",
    "react", "vue", "angular", "svelte", "next", "nuxt", "vite",
    "fastapi", "flask", "django", "express", "node", "npm", "yarn",
    "sqlite", "postgres", "postgresql", "mysql", "mongodb", "redis",
    "docker", "kubernetes", "nginx", "aws", "gcp", "azure",
    "state", "form", "fetching", "cache", "queue", "infrastructure",
    "auth", "authentication", "authorization", "config", "configuration",
    "middleware", "router", "endpoint", "api", "rest", "graphql",
    "schema", "migration", "seed", "fixture", "test",
})

def _filter_garbage_entities(entities_raw: list) -> list:
    """Remove tech-stack words, Python keywords, and field-extracted pseudo-entities."""
    # Pass 1: name blocklist
    name_filtered = []
    for e in entities_raw:
        name = e.get("name", "")
        if not name:
            continue
        if name.lower() in _GARBAGE_ENTITY_NAMES:
            logger.warning("p02b: filtering garbage entity '%s' from IR (blocklist)", name)
            continue
        name_filtered.append(e)

    # Pass 2: pseudo-entity detection — entity whose name is a field of another entity AND
    # has ≤1 non-id/timestamp fields is almost certainly a field extracted as an entity
    _ID_FIELDS = frozenset({"id", "created_at", "updated_at", "deleted_at", "is_active", "is_deleted"})
    all_field_names: set = set()
    for e in name_filtered:
        for f in e.get("fields", []):
            fname = f.get("name", "").lower()
            if fname and fname not in _ID_FIELDS:
                all_field_names.add(fname)

    result = []
    for e in name_filtered:
        name = e.get("name", "")
        non_id_fields = [
            f for f in e.get("fields", [])
            if f.get("name", "").lower() not in _ID_FIELDS
        ]
        if len(non_id_fields) <= 1 and name.lower() in all_field_names:
            logger.warning(
                "p02b: filtering pseudo-entity '%s' (name is a field of another entity, only %d own fields)",
                name, len(non_id_fields),
            )
            continue
        result.append(e)
    return result

# ---------------------------------------------------------------------------
# Pass prompts
# ---------------------------------------------------------------------------

_PASS1_PROMPT = """You are a software architect extracting entities and fields from a requirements document.

Requirements:
{requirements}

Known entities from architecture analysis (use these as your starting point, add any missing ones):
{seed_entities}

Extract ALL business entities. For each entity:
- name: PascalCase entity name
- table: snake_case plural table name
- description: one-sentence purpose
- fields: list of fields (exclude id, created_at, updated_at — those are added automatically)

For each field provide:
- name: snake_case field name
- type: one of: string, text, integer, decimal, boolean, date, datetime, email, url, enum, fk, json
- nullable: true/false
- unique: true/false (only if truly unique like email/username)
- index: true/false (index frequently filtered fields)
- ref_entity: for fk type, the PascalCase entity name this references
- enum_values: for enum type, list the allowed values
- default: default value if any (null if none)
- confidence: float 0.0–1.0 (how confident you are this field belongs here; < 0.6 means ambiguous)

Return ONLY valid JSON:
{{
  "entities": [
    {{
      "name": "Employee",
      "table": "employees",
      "description": "Represents a company employee",
      "fields": [
        {{"name": "first_name", "type": "string", "nullable": false, "unique": false, "index": false, "ref_entity": null, "enum_values": [], "default": null, "confidence": 1.0}},
        {{"name": "email", "type": "email", "nullable": false, "unique": true, "index": true, "ref_entity": null, "enum_values": [], "default": null, "confidence": 1.0}},
        {{"name": "department_id", "type": "fk", "nullable": true, "unique": false, "index": true, "ref_entity": "Department", "enum_values": [], "default": null, "confidence": 0.9}}
      ]
    }}
  ]
}}"""

_PASS2_PROMPT = """You are a software architect extracting relationships between entities.

Requirements:
{requirements}

Entities already extracted:
{entities_json}

Extract ALL relationships between these entities. For each relationship:
- from_entity: PascalCase entity that holds the foreign key
- to_entity: PascalCase entity being referenced
- cardinality: one of: one-to-one, one-to-many, many-to-one, many-to-many
- through_table: for many-to-many, the join table name (snake_case), else null
- label: human-readable description e.g. "Employee belongs to Department"

Return ONLY valid JSON:
{{
  "relationships": [
    {{"from_entity": "Employee", "to_entity": "Department", "cardinality": "many-to-one", "through_table": null, "label": "Employee belongs to Department"}}
  ]
}}"""

_PASS3_PROMPT = """You are a software architect extracting business rules and permissions.

Requirements:
{requirements}

Entities:
{entities_json}

Extract:

1. business_rules — constraints/validations that must always hold:
   - name: snake_case identifier
   - expression: human-readable rule e.g. "salary > 0"
   - entity: which entity this applies to
   - error_message: shown to user when violated

2. permissions — what each role can do:
   - role: e.g. "admin", "manager", "employee", "viewer"
   - entity: entity name
   - actions: list from [read, create, update, delete]

3. workflows — multi-step approval processes:
   - name: snake_case e.g. "leave_approval"
   - trigger: what starts it e.g. "Employee submits leave request"
   - entity: primary entity
   - steps: list of {{name, actor, action}}

4. dashboard_metrics — KPI cards for the dashboard:
   - name: snake_case e.g. "headcount"
   - label: display label e.g. "Total Employees"
   - query_hint: e.g. "COUNT employees WHERE active=true"
   - entity: source entity
   - aggregation: count | sum | avg | max | min

5. notifications — automated alerts:
   - event: trigger event name
   - channel: email | in_app | webhook
   - recipient_role: who receives it
   - template: brief message template

Return ONLY valid JSON with keys: business_rules, permissions, workflows, dashboard_metrics, notifications."""

_PASS4_PROMPT = """You are a senior software architect reviewing an extracted Domain IR for consistency and completeness.

Requirements:
{requirements}

Current IR (after 3 passes):
{ir_json}

Review and fix:
1. Any entity referenced in a relationship but missing from entities list — add it
2. Any FK field whose ref_entity does not match a known entity — correct the ref_entity
3. Any field with confidence < 0.6 — add a clarifying question
4. Any obviously missing field (e.g. Employee has no status field, Payroll has no amount) — add it with confidence 0.8
5. Any duplicate entities (same concept, different names) — merge them
6. Dashboard metrics that reference non-existent entities — fix or remove

For clarifying questions (only for genuinely ambiguous fields):
- field_path: "EntityName.field_name"
- confidence: current confidence score
- question: clear question for the user
- options: 2–4 multiple choice options

Return the COMPLETE corrected IR as valid JSON with ALL keys:
entities, relationships, business_rules, permissions, workflows, dashboard_metrics, notifications, clarifying_questions

The clarifying_questions list should be EMPTY if there is no genuine ambiguity."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Extract the first JSON object from LLM response text."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find first { ... } block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _seed_entities(architecture: dict) -> str:
    """Extract entity names from architecture.json database_schema."""
    schema = architecture.get("database_schema", [])
    if not schema:
        return "None (extract all entities from requirements)"
    names = []
    for tbl in schema:
        table = tbl.get("table", "")
        if table and table not in ("users", "user"):
            # Convert snake_case to PascalCase
            pascal = "".join(w.capitalize() for w in table.rstrip("s").split("_"))
            # Filter out tech-stack words so they don't seed garbage entities
            if pascal.lower() not in _GARBAGE_ENTITY_NAMES:
                names.append(f"- {pascal} (table: {table})")
    return "\n".join(names) if names else "None"


def _build_ir_from_passes(
    pass1: dict, pass2: dict, pass3: dict, pass4: dict,
    domain: str, app_name: str,
) -> DomainIR:
    """Merge the 4 pass results into a DomainIR object."""
    # Use pass4 as the authoritative source (it reviewed and corrected everything)
    source = pass4 if pass4 else {}
    entities_raw = source.get("entities") or pass1.get("entities", [])
    entities_raw = _filter_garbage_entities(entities_raw)
    relationships_raw = source.get("relationships") or pass2.get("relationships", [])
    rules_raw = source.get("business_rules") or pass3.get("business_rules", [])
    permissions_raw = source.get("permissions") or pass3.get("permissions", [])
    workflows_raw = source.get("workflows") or pass3.get("workflows", [])
    metrics_raw = source.get("dashboard_metrics") or pass3.get("dashboard_metrics", [])
    notif_raw = source.get("notifications") or pass3.get("notifications", [])
    questions_raw = source.get("clarifying_questions", [])

    ir = DomainIR(domain=domain, app_name=app_name)

    for e in entities_raw:
        fields = []
        for f in e.get("fields", []):
            atype = f.get("type", "string")
            if atype not in [t.value for t in AetherType]:
                atype = "string"
            fields.append(IRField(
                name=f.get("name", ""),
                type=atype,
                nullable=f.get("nullable", True),
                unique=f.get("unique", False),
                index=f.get("index", False),
                ref_entity=f.get("ref_entity"),
                enum_values=f.get("enum_values", []),
                default=f.get("default"),
                confidence=float(f.get("confidence", 1.0)),
            ))
        ir.entities.append(IREntity(
            name=e.get("name", ""),
            table=e.get("table", ""),
            description=e.get("description", ""),
            fields=fields,
        ))

    for r in relationships_raw:
        ir.relationships.append(IRRelationship(
            from_entity=r.get("from_entity", ""),
            to_entity=r.get("to_entity", ""),
            cardinality=r.get("cardinality", "many-to-one"),
            through_table=r.get("through_table"),
            label=r.get("label", ""),
        ))

    for r in rules_raw:
        ir.business_rules.append(IRBusinessRule(
            name=r.get("name", ""),
            expression=r.get("expression", ""),
            entity=r.get("entity", ""),
            error_message=r.get("error_message", ""),
        ))

    for p in permissions_raw:
        ir.permissions.append(IRPermission(
            role=p.get("role", ""),
            entity=p.get("entity", ""),
            actions=p.get("actions", []),
        ))

    for w in workflows_raw:
        steps = [IRWorkflowStep(**s) for s in w.get("steps", []) if "name" in s and "actor" in s and "action" in s]
        ir.workflows.append(IRWorkflow(
            name=w.get("name", ""),
            trigger=w.get("trigger", ""),
            entity=w.get("entity", ""),
            steps=steps,
        ))

    for m in metrics_raw:
        ir.dashboard_metrics.append(IRDashboardMetric(
            name=m.get("name", ""),
            label=m.get("label", ""),
            query_hint=m.get("query_hint", ""),
            entity=m.get("entity", ""),
            aggregation=m.get("aggregation", "count"),
        ))

    for n in notif_raw:
        ir.notifications.append(IRNotification(
            event=n.get("event", ""),
            channel=n.get("channel", "in_app"),
            recipient_role=n.get("recipient_role", "admin"),
            template=n.get("template", ""),
        ))

    for q in questions_raw:
        ir.clarifying_questions.append(IRClarifyingQuestion(
            field_path=q.get("field_path", ""),
            confidence=float(q.get("confidence", 0.0)),
            question=q.get("question", ""),
            options=q.get("options", []),
        ))

    return ir


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(phase_input: Any, memory_ctx: list, output_dir: Path) -> TaskResult:
    """
    Extract Domain IR from requirements using 4 focused LLM passes.

    Reads:  phase_input.input_data["raw_input"], p02_architecture_path
    Writes: domain_ir.json to output_dir
    """
    from aether_os.phases.base import TaskResult as _TaskResult

    data = phase_input.input_data
    run_id: str = phase_input.run_id
    ir_path = output_dir / "domain_ir.json"

    requirements: str = data.get("raw_input", "")
    if not requirements:
        req_path = Path(data.get("requirements_path", ""))
        if req_path.exists():
            requirements = req_path.read_text()

    if not requirements:
        return _TaskResult(
            output_path=str(output_dir),
            confidence=0.0,
            success=False,
            issues=["No requirements found — cannot extract Domain IR"],
            metadata={"error": "missing_requirements"},
        )

    # Load architecture.json for entity seeds
    arch_path_str = data.get("p02_architecture_path", "")
    if not arch_path_str:
        arch_path_str = str(output_dir.parent / "p02_architecture" / "architecture.json")
    arch_path = Path(arch_path_str)
    architecture: dict = {}
    # --- Problem 25 fix: handle str architecture output ---
    _arch_raw = data.get("architecture_output")
    if _arch_raw is not None:
        if isinstance(_arch_raw, str):
            try:
                architecture = json.loads(_arch_raw)
            except Exception:
                logger.warning("p02b: architecture_output is a non-JSON string — will extract from spec")
                architecture = {}
        elif isinstance(_arch_raw, dict):
            architecture = _arch_raw
    if not architecture and arch_path.exists():
        try:
            architecture = json.loads(arch_path.read_text())
        except Exception as exc:
            logger.debug("p02b: failed to read architecture from arch_path (non-fatal): %s", exc)
    # If architecture is still not a dict (e.g. came in as something unexpected), reset
    if not isinstance(architecture, dict):
        logger.warning("p02b: architecture resolved to non-dict type %s — resetting to {}", type(architecture))
        architecture = {}

    domain: str = getattr(phase_input, "domain", None) or architecture.get("domain", "general")
    app_name: str = data.get("app_name", data.get("project_name", "App"))
    seed = _seed_entities(architecture)

    llm = get_llm_client()
    pass_results: list[dict] = []
    errors: list[str] = []

    async def _call(prompt: str, pass_num: int) -> dict:
        try:
            resp = await llm.call(prompt, task_type="analysis", max_tokens=4096)
            result = _extract_json(resp)
            if not result:
                logger.warning("p02b pass %d returned unparseable JSON", pass_num)
                errors.append(f"pass{pass_num}_parse_error")
            return result
        except Exception as exc:
            logger.error("p02b pass %d LLM error: %s", pass_num, exc)
            errors.append(f"pass{pass_num}_llm_error: {exc}")
            return {}

    logger.info("p02b: starting SINGLE-pass Domain IR extraction for run %s", run_id)

    # Single combined prompt — one LLM call instead of four. Reduced from
    # ~240-720s worst case to ~60s. The prompt asks for everything at once
    # because Nova Pro / Llama 3.3 70B handle this in one shot.
    _COMBINED_PROMPT = (
        "You are a software architect extracting a Domain Intermediate Representation "
        "from a requirements document.\n\n"
        f"Requirements:\n{requirements[:6000]}\n\n"
        f"Known entities from architecture analysis (use as starting point, add missing ones):\n{seed}\n\n"
        "Produce ONE JSON object with EVERY field below. Return ONLY the JSON, no commentary, no markdown fences.\n\n"
        "SCHEMA:\n"
        "- entities: list of { name (PascalCase), table (snake_case plural), description, fields }\n"
        "  where fields is a list of { name, type (string|text|integer|decimal|boolean|date|datetime|email|url|enum|fk|json), nullable, unique, index, ref_entity (PascalCase for fk), enum_values, default, confidence (0.0-1.0) }\n"
        "  Exclude id/created_at/updated_at — those are auto-added.\n"
        "- relationships: list of { from_entity, to_entity, cardinality (one-to-one|one-to-many|many-to-one|many-to-many), through_table, label }\n"
        "- business_rules: list of { name (snake_case), expression, entity, error_message }\n"
        "- permissions: list of { role, entity, actions: [read,create,update,delete] }\n"
        "- workflows: list of { name (snake_case), trigger, entity, steps: [{name, actor, action}] }\n"
        "- dashboard_metrics: list of { name (snake_case), label, query_hint, entity, aggregation (count|sum|avg|max|min) }\n"
        "- notifications: list of { event, channel (email|in_app|webhook), recipient_role, template }\n"
        "- clarifying_questions: list of { field_path, confidence, question, options } — EMPTY unless a field truly cannot be inferred\n\n"
        "Rules:\n"
        "1. Extract entities exhaustively. Every noun in the spec that is persisted gets an entity.\n"
        "2. Every fk field MUST have ref_entity matching a PascalCase name in entities.\n"
        "3. Permissions: include at minimum admin (full access) and one end-user role.\n"
        "4. Dashboard metrics: at least 3 KPIs that a business owner would care about.\n"
    )

    combined_result = await _call(_COMBINED_PROMPT, 1)
    logger.info(
        "p02b single-pass complete — %d entities / %d relationships / %d rules / %d metrics",
        len(combined_result.get("entities", [])),
        len(combined_result.get("relationships", [])),
        len(combined_result.get("business_rules", [])),
        len(combined_result.get("dashboard_metrics", [])),
    )
    p1 = p2 = p3 = p4 = combined_result
    pass_results.append(combined_result)

    # If the single call produced nothing, build a minimal stub from app_name (no extra LLM call).
    if not combined_result.get("entities"):
        logger.warning("p02b: LLM produced no entities — building stub IR")
        import re as _re2b
        _stub_entity_name = _re2b.sub(r'[^A-Za-z0-9]', '', "".join(w.capitalize() for w in app_name.split()[:2])) or "Item"
        p1 = {
            "entities": [{
                "name": _stub_entity_name,
                "table": _stub_entity_name.lower() + "s",
                "description": f"Primary entity for {app_name}",
                "fields": [
                    {"name": "name", "type": "string", "nullable": False, "unique": False,
                     "index": False, "ref_entity": None, "enum_values": [], "default": None, "confidence": 0.7},
                    {"name": "description", "type": "text", "nullable": True, "unique": False,
                     "index": False, "ref_entity": None, "enum_values": [], "default": None, "confidence": 0.7},
                ],
            }],
        }
        p2 = p3 = p4 = p1

    # Merge all passes into DomainIR
    ir = _build_ir_from_passes(p1, p2, p3, p4, domain=domain, app_name=app_name)

    # Collect any fields with confidence below threshold as clarifying questions
    for entity in ir.entities:
        for f in entity.fields:
            if f.confidence < CONFIDENCE_THRESHOLD:
                # Avoid duplicates from pass 4
                already = any(
                    q.field_path == f"{entity.name}.{f.name}"
                    for q in ir.clarifying_questions
                )
                if not already:
                    ir.clarifying_questions.append(IRClarifyingQuestion(
                        field_path=f"{entity.name}.{f.name}",
                        confidence=f.confidence,
                        question=f"What does '{f.name}' represent on {entity.name}?",
                        options=[],
                    ))

    # Validate and auto-fix IR before saving
    from aether_os.core.ir_validator import validate as _validate_ir
    val = _validate_ir(ir, fix=True)
    if not val.valid:
        logger.warning("p02b IR validation failed: %s", val.errors)
        errors.extend(val.errors)
    for w in val.warnings:
        logger.debug("p02b IR validator warning: %s", w)

    # --- Problem 25 fix: validate IR is not empty before saving ---
    if not ir.entities:
        raise ValueError(
            f"p02b: DomainIR is incomplete — no entities were extracted for app '{app_name}' "
            f"(domain={domain}). Check requirements input and LLM availability."
        )

    # Save IR to disk
    output_dir.mkdir(parents=True, exist_ok=True)
    ir.save(ir_path)
    logger.info("p02b: domain_ir.json written to %s", ir_path)

    has_questions = bool(ir.clarifying_questions)
    entity_count = len(ir.entities)
    field_count = sum(len(e.fields) for e in ir.entities)

    summary = (
        f"Domain IR extracted: {entity_count} entities, {field_count} fields, "
        f"{len(ir.relationships)} relationships, {len(ir.dashboard_metrics)} KPI metrics"
    )
    if has_questions:
        summary += f"\n{len(ir.clarifying_questions)} clarifying questions need answers before continuing"
    if errors:
        summary += f"\nWarnings: {', '.join(errors)}"

    from aether_os.phases.base import TaskResult as _TaskResult
    return _TaskResult(
        output_path=str(ir_path),
        confidence=1.0 if not errors else 0.85,
        success=True,
        issues=[],
        metadata={
            "domain": domain,
            "entity_count": entity_count,
            "field_count": field_count,
            "relationship_count": len(ir.relationships),
            "metric_count": len(ir.dashboard_metrics),
            "clarifying_questions": len(ir.clarifying_questions),
            "has_questions": has_questions,
            "pass_errors": errors,
            "domain_ir_path": str(ir_path),
            "output": summary,
        },
    )
