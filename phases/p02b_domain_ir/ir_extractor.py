"""
P02b IR Extractor — entity filtering, prompts, helpers, and single-pass extraction.
Extracted from task_agent.py to keep it under 350 lines.

Public API:
  _GARBAGE_ENTITY_NAMES   — frozenset of tech-stack / keyword strings to block
  _filter_garbage_entities(entities_raw) — removes tech-stack and pseudo-entities
  _extract_json(text)     — parses first JSON object from LLM response
  _seed_entities(arch)    — builds entity seed string from architecture.json
  _build_ir_from_passes(p1, p2, p3, p4, domain, app_name) — merges passes → DomainIR
  run_4pass_extraction(*, requirements, seed, llm) — single LLM call, returns (p1,p2,p3,p4,errors)
  build_stub_ir(app_name) — minimal 1-entity stub when LLM produces nothing
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Tuple

from aether_os.core.domain_ir import (
    DomainIR, IREntity, IRField, IRRelationship, IRBusinessRule,
    IRPermission, IRWorkflow, IRWorkflowStep, IRDashboardMetric,
    IRNotification, IRClarifyingQuestion, AetherType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Garbage entity filter
# ---------------------------------------------------------------------------

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
# JSON parsing helper
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Extract the first JSON object from LLM response text."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("[p02b] _extract_json: direct parse failed: %s", e)
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("[p02b] _extract_json: parse after markdown strip failed: %s", e)
    # Find first { ... } block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning("[p02b] _extract_json: JSON block extraction failed: %s", e)
    return {}


# ---------------------------------------------------------------------------
# Architecture seed helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# IR assembly
# ---------------------------------------------------------------------------

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
# Single-pass extraction (public entry point)
# ---------------------------------------------------------------------------

_COMBINED_PROMPT_TEMPLATE = (
    "You are a software architect extracting a Domain Intermediate Representation "
    "from a requirements document.\n\n"
    "Requirements:\n{requirements}\n\n"
    "Known entities from architecture analysis (use as starting point, add missing ones):\n{seed}\n\n"
    "Produce ONE JSON object with EVERY field below. Return ONLY the JSON, no commentary, no markdown fences.\n\n"
    "SCHEMA:\n"
    "- entities: list of {{ name (PascalCase), table (snake_case plural), description, fields }}\n"
    "  where fields is a list of {{ name, type (string|text|integer|decimal|boolean|date|datetime|email|url|enum|fk|json), nullable, unique, index, ref_entity (PascalCase for fk), enum_values, default, confidence (0.0-1.0) }}\n"
    "  Exclude id/created_at/updated_at — those are auto-added.\n"
    "- relationships: list of {{ from_entity, to_entity, cardinality (one-to-one|one-to-many|many-to-one|many-to-many), through_table, label }}\n"
    "- business_rules: list of {{ name (snake_case), expression, entity, error_message }}\n"
    "- permissions: list of {{ role, entity, actions: [read,create,update,delete] }}\n"
    "- workflows: list of {{ name (snake_case), trigger, entity, steps: [{{name, actor, action}}] }}\n"
    "- dashboard_metrics: list of {{ name (snake_case), label, query_hint, entity, aggregation (count|sum|avg|max|min) }}\n"
    "- notifications: list of {{ event, channel (email|in_app|webhook), recipient_role, template }}\n"
    "- clarifying_questions: list of {{ field_path, confidence, question, options }} — EMPTY unless a field truly cannot be inferred\n\n"
    "Rules:\n"
    "1. Extract entities exhaustively. Every noun in the spec that is persisted gets an entity.\n"
    "2. Every fk field MUST have ref_entity matching a PascalCase name in entities.\n"
    "3. Permissions: include at minimum admin (full access) and one end-user role.\n"
    "4. Dashboard metrics: at least 3 KPIs that a business owner would care about.\n"
)


async def run_4pass_extraction(
    *,
    requirements: str,
    seed: str,
    llm: Any,
) -> Tuple[Dict, Dict, Dict, Dict, List[str]]:
    """Run true 4-pass Domain IR extraction, one focused LLM call per concern.

    Pass 1 — entities and fields (the skeleton of the data model)
    Pass 2 — relationships between entities (cardinality, FK, join tables)
    Pass 3 — business rules, permissions, workflows, metrics, notifications
    Pass 4 — consistency review: fill gaps, fix FK refs, merge duplicates

    Each pass uses a focused prompt (~300–400 tokens) so the LLM produces
    higher-quality output than a single mega-prompt.  Results are merged by
    _build_ir_from_passes() which takes pass4 as the authoritative source.

    Returns (pass1, pass2, pass3, pass4, errors).
    On parse failure for any pass the dict is {} and errors records the reason.
    """
    errors: List[str] = []
    req_snippet = requirements[:6000]

    # ── Pass 1: entities and fields ──────────────────────────────────────────
    p1: Dict = {}
    _p1_prompt = _PASS1_PROMPT.format(
        requirements=req_snippet,
        seed_entities=seed,
    )
    try:
        resp1 = await llm.call(_p1_prompt, task_type="analysis", max_tokens=4096)
        p1 = _extract_json(resp1)
        if not p1.get("entities"):
            logger.warning("p02b pass1 returned no entities")
            errors.append("pass1_no_entities")
    except Exception as exc:
        logger.error("p02b pass1 LLM error: %s", exc)
        errors.append(f"pass1_llm_error: {exc}")

    logger.info("p02b pass1 complete — %d entities", len(p1.get("entities", [])))

    # ── Pass 2: relationships ────────────────────────────────────────────────
    p2: Dict = {}
    if p1.get("entities"):
        _p2_prompt = _PASS2_PROMPT.format(
            requirements=req_snippet,
            entities_json=json.dumps(p1.get("entities", [])[:30], indent=2),
        )
        try:
            resp2 = await llm.call(_p2_prompt, task_type="analysis", max_tokens=2048)
            p2 = _extract_json(resp2)
            if not p2.get("relationships"):
                logger.warning("p02b pass2 returned no relationships")
                errors.append("pass2_no_relationships")
        except Exception as exc:
            logger.error("p02b pass2 LLM error: %s", exc)
            errors.append(f"pass2_llm_error: {exc}")

        logger.info("p02b pass2 complete — %d relationships", len(p2.get("relationships", [])))

    # ── Pass 3: business rules, permissions, workflows, metrics, notifications ─
    p3: Dict = {}
    if p1.get("entities"):
        _p3_prompt = _PASS3_PROMPT.format(
            requirements=req_snippet,
            entities_json=json.dumps(p1.get("entities", [])[:20], indent=2),
        )
        try:
            resp3 = await llm.call(_p3_prompt, task_type="analysis", max_tokens=3000)
            p3 = _extract_json(resp3)
        except Exception as exc:
            logger.error("p02b pass3 LLM error: %s", exc)
            errors.append(f"pass3_llm_error: {exc}")

        logger.info(
            "p02b pass3 complete — %d rules / %d metrics / %d workflows",
            len(p3.get("business_rules", [])),
            len(p3.get("dashboard_metrics", [])),
            len(p3.get("workflows", [])),
        )

    # ── Pass 4: consistency review ───────────────────────────────────────────
    p4: Dict = {}
    if p1.get("entities"):
        _interim_ir = {
            "entities": p1.get("entities", []),
            "relationships": p2.get("relationships", []),
            "business_rules": p3.get("business_rules", []),
            "permissions": p3.get("permissions", []),
            "workflows": p3.get("workflows", []),
            "dashboard_metrics": p3.get("dashboard_metrics", []),
            "notifications": p3.get("notifications", []),
            "clarifying_questions": [],
        }
        _p4_prompt = _PASS4_PROMPT.format(
            requirements=req_snippet,
            ir_json=json.dumps(_interim_ir, indent=2)[:5000],
        )
        try:
            resp4 = await llm.call(_p4_prompt, task_type="analysis", max_tokens=4096)
            p4 = _extract_json(resp4)
            if not p4.get("entities"):
                # If pass4 fails to return a complete IR, fall back to the merged interim
                logger.warning("p02b pass4 returned incomplete IR — using interim merge as pass4")
                p4 = _interim_ir
                errors.append("pass4_incomplete_fell_back_to_interim")
        except Exception as exc:
            logger.error("p02b pass4 LLM error: %s", exc)
            errors.append(f"pass4_llm_error: {exc}")
            p4 = _interim_ir  # safety fallback

        logger.info(
            "p02b pass4 complete — %d entities / %d relationships / %d metrics",
            len(p4.get("entities", [])),
            len(p4.get("relationships", [])),
            len(p4.get("dashboard_metrics", [])),
        )

    # If all passes failed, return empty dicts
    if not p1 and not p4:
        logger.error("p02b: all 4 passes failed to produce any entities")
    return p1, p2, p3, p4, errors


def build_stub_ir(app_name: str) -> Dict:
    """Build a minimal stub IR dict when the LLM produces no entities."""
    _stub_entity_name = (
        re.sub(r"[^A-Za-z0-9]", "", "".join(w.capitalize() for w in app_name.split()[:2]))
        or "Item"
    )
    return {
        "entities": [{
            "name": _stub_entity_name,
            "table": _stub_entity_name.lower() + "s",
            "description": f"Primary entity for {app_name}",
            "fields": [
                {
                    "name": "name", "type": "string", "nullable": False,
                    "unique": False, "index": False, "ref_entity": None,
                    "enum_values": [], "default": None, "confidence": 0.7,
                },
                {
                    "name": "description", "type": "text", "nullable": True,
                    "unique": False, "index": False, "ref_entity": None,
                    "enum_values": [], "default": None, "confidence": 0.7,
                },
            ],
        }],
    }
