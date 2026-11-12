"""
Domain IR — Intermediate Representation for AetherOS pipeline.

The Domain IR is the contract between the Planner LLM (p02b) and the
deterministic generators (p04a, p05). It fully describes a business domain
as structured data so that structural code (models, schemas, CRUD, entity
pages, dashboards) can be generated without any LLM involvement.

Architecture:
    Prompt → Preflight Council → p02b (4-pass IR extraction) → IR Validator
    → p04a Deterministic Backend Generator → p05 Deterministic Frontend Generator

Backward compatibility:
    Every phase checks data.get("domain_ir_path") first. If absent, the phase
    falls through to its existing LLM-based behaviour unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Universal Aether Type System
# ---------------------------------------------------------------------------

class AetherType(str, Enum):
    """Canonical types — each maps to SQLAlchemy, TypeScript, Zod, and OpenAPI."""
    STRING   = "string"    # VARCHAR(255)          string      z.string()    string
    TEXT     = "text"      # TEXT                  string      z.string()    string
    INTEGER  = "integer"   # Integer               number      z.number()    integer
    DECIMAL  = "decimal"   # Numeric(14,2)         number      z.number()    number
    BOOLEAN  = "boolean"   # Boolean               boolean     z.boolean()   boolean
    DATE     = "date"      # Date                  string      z.string()    string/date
    DATETIME = "datetime"  # DateTime(timezone=True) string    z.string()    string/date-time
    EMAIL    = "email"     # String(320)           string      z.string().email()  string
    URL      = "url"       # String(2048)          string      z.string().url()    string
    ENUM     = "enum"      # String(50)            string      z.enum([...]) string
    FK       = "fk"        # Integer + ForeignKey  number      z.number()    integer
    JSON     = "json"      # JSON                  object      z.record(...)  object


# Maps AetherType → SQLAlchemy column definition fragment
SA_TYPE_MAP: dict[str, str] = {
    AetherType.STRING:   "String(255)",
    AetherType.TEXT:     "Text",
    AetherType.INTEGER:  "Integer",
    AetherType.DECIMAL:  "Numeric(14, 2)",
    AetherType.BOOLEAN:  "Boolean",
    AetherType.DATE:     "Date",
    AetherType.DATETIME: "DateTime(timezone=True)",
    AetherType.EMAIL:    "String(320), unique=True, index=True",
    AetherType.URL:      "String(2048)",
    AetherType.ENUM:     "String(50)",
    AetherType.FK:       "Integer",  # ForeignKey appended by generator using ref_entity
    AetherType.JSON:     "JSON",
}

# Maps AetherType → TypeScript type string
TS_TYPE_MAP: dict[str, str] = {
    AetherType.STRING:   "string",
    AetherType.TEXT:     "string",
    AetherType.INTEGER:  "number",
    AetherType.DECIMAL:  "number",
    AetherType.BOOLEAN:  "boolean",
    AetherType.DATE:     "string",
    AetherType.DATETIME: "string",
    AetherType.EMAIL:    "string",
    AetherType.URL:      "string",
    AetherType.ENUM:     "string",
    AetherType.FK:       "number",
    AetherType.JSON:     "Record<string, unknown>",
}

# Maps AetherType → Zod schema fragment
ZOD_TYPE_MAP: dict[str, str] = {
    AetherType.STRING:   "z.string()",
    AetherType.TEXT:     "z.string()",
    AetherType.INTEGER:  "z.number().int()",
    AetherType.DECIMAL:  "z.number()",
    AetherType.BOOLEAN:  "z.boolean()",
    AetherType.DATE:     "z.string()",
    AetherType.DATETIME: "z.string()",
    AetherType.EMAIL:    "z.string().email()",
    AetherType.URL:      "z.string().url()",
    AetherType.ENUM:     "z.string()",  # refined to z.enum([...]) when enum_values present
    AetherType.FK:       "z.number().int()",
    AetherType.JSON:     "z.record(z.unknown())",
}

# Maps AetherType → OpenAPI type/format dict
OPENAPI_TYPE_MAP: dict[str, dict] = {
    AetherType.STRING:   {"type": "string"},
    AetherType.TEXT:     {"type": "string"},
    AetherType.INTEGER:  {"type": "integer"},
    AetherType.DECIMAL:  {"type": "number", "format": "float"},
    AetherType.BOOLEAN:  {"type": "boolean"},
    AetherType.DATE:     {"type": "string", "format": "date"},
    AetherType.DATETIME: {"type": "string", "format": "date-time"},
    AetherType.EMAIL:    {"type": "string", "format": "email"},
    AetherType.URL:      {"type": "string", "format": "uri"},
    AetherType.ENUM:     {"type": "string"},
    AetherType.FK:       {"type": "integer"},
    AetherType.JSON:     {"type": "object"},
}


# ---------------------------------------------------------------------------
# IR dataclasses
# ---------------------------------------------------------------------------

@dataclass
class IRField:
    """A single field on an entity."""
    name: str
    type: str                        # AetherType value
    nullable: bool = True
    unique: bool = False
    index: bool = False
    ref_entity: str | None = None    # FK target entity name (snake_case)
    enum_values: list[str] = field(default_factory=list)
    default: Any = None
    confidence: float = 1.0          # 0.0–1.0; < 0.6 triggers clarifying question


@dataclass
class IREntity:
    """A business entity (maps to one DB table + CRUD routes + entity page)."""
    name: str                        # PascalCase, e.g. "Employee"
    table: str                       # snake_case, e.g. "employees"
    fields: list[IRField] = field(default_factory=list)
    description: str = ""


@dataclass
class IRRelationship:
    """A relationship between two entities."""
    from_entity: str                 # PascalCase
    to_entity: str                   # PascalCase
    cardinality: str = "many-to-one" # one-to-one | one-to-many | many-to-one | many-to-many
    through_table: str | None = None # join table name for many-to-many
    label: str = ""                  # e.g. "Employee belongs to Department"


@dataclass
class IRBusinessRule:
    """A business constraint or validation rule."""
    name: str                        # snake_case identifier
    expression: str                  # human-readable, e.g. "salary > 0"
    entity: str                      # which entity this applies to
    error_message: str = ""


@dataclass
class IRPermission:
    """What a role can do to an entity."""
    role: str                        # e.g. "admin", "manager", "employee"
    entity: str                      # entity name
    actions: list[str] = field(default_factory=list)  # read / create / update / delete


@dataclass
class IRWorkflowStep:
    name: str
    actor: str                       # role who performs this step
    action: str                      # e.g. "submit", "approve", "reject"


@dataclass
class IRWorkflow:
    """A multi-step business process requiring approval or sequenced actions."""
    name: str                        # e.g. "leave_approval"
    trigger: str                     # e.g. "Employee submits leave request"
    entity: str                      # primary entity involved
    steps: list[IRWorkflowStep] = field(default_factory=list)


@dataclass
class IRDashboardMetric:
    """A KPI card shown on the generated app's dashboard."""
    name: str                        # e.g. "headcount"
    label: str                       # e.g. "Total Employees"
    query_hint: str                  # e.g. "COUNT employees WHERE active=true"
    entity: str                      # source entity
    aggregation: str = "count"       # count | sum | avg | max | min


@dataclass
class IRNotification:
    """An automated notification triggered by a business event."""
    event: str                       # e.g. "leave_approved"
    channel: str                     # email | in_app | webhook
    recipient_role: str              # role who receives it
    template: str = ""               # message template hint


@dataclass
class IRIntegration:
    """An external system integration hint."""
    name: str                        # e.g. "payroll_export"
    system: str                      # e.g. "QuickBooks", "Slack", "HRMS"
    trigger: str = ""                # when it fires
    direction: str = "outbound"      # inbound | outbound | bidirectional


@dataclass
class IRClarifyingQuestion:
    """Surfaced when a field or concept has low confidence during extraction."""
    field_path: str                  # e.g. "Employee.schedule"
    confidence: float = 0.0
    question: str = ""
    options: list[str] = field(default_factory=list)  # multiple-choice options


@dataclass
class DomainIR:
    """
    The complete Domain Intermediate Representation for one application.

    Produced by p02b (4-pass LLM extraction + validation).
    Consumed by p04a (deterministic backend) and p05 (deterministic frontend).
    """
    domain: str                                          # e.g. "hr", "crm", "pos"
    app_name: str                                        # e.g. "PeopleCore HR"
    entities: list[IREntity] = field(default_factory=list)
    relationships: list[IRRelationship] = field(default_factory=list)
    business_rules: list[IRBusinessRule] = field(default_factory=list)
    permissions: list[IRPermission] = field(default_factory=list)
    workflows: list[IRWorkflow] = field(default_factory=list)
    dashboard_metrics: list[IRDashboardMetric] = field(default_factory=list)
    notifications: list[IRNotification] = field(default_factory=list)
    integrations: list[IRIntegration] = field(default_factory=list)
    clarifying_questions: list[IRClarifyingQuestion] = field(default_factory=list)
    clarifications: dict[str, str] = field(default_factory=dict)  # answers to clarifying questions (orchestrator/clarifying.py)
    validated: bool = False
    ir_version: str = "1.0"

    # -----------------------------------------------------------------------
    # Serialisation helpers
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, path: Path) -> None:
        path.write_text(self.to_json())

    @classmethod
    def load(cls, path: Path) -> "DomainIR":
        raw = json.loads(path.read_text())
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, d: dict) -> "DomainIR":
        ir = cls(domain=d.get("domain", ""), app_name=d.get("app_name", ""))
        ir.ir_version = d.get("ir_version", "1.0")
        ir.validated = d.get("validated", False)
        ir.entities = [
            IREntity(
                name=e["name"], table=e["table"],
                description=e.get("description", ""),
                fields=[IRField(**f) for f in e.get("fields", [])],
            )
            for e in d.get("entities", [])
        ]
        ir.relationships = [IRRelationship(**r) for r in d.get("relationships", [])]
        ir.business_rules = [IRBusinessRule(**r) for r in d.get("business_rules", [])]
        ir.permissions = [IRPermission(**p) for p in d.get("permissions", [])]
        ir.workflows = [
            IRWorkflow(
                name=w["name"], trigger=w.get("trigger", ""), entity=w.get("entity", ""),
                steps=[IRWorkflowStep(**s) for s in w.get("steps", [])],
            )
            for w in d.get("workflows", [])
        ]
        ir.dashboard_metrics = [IRDashboardMetric(**m) for m in d.get("dashboard_metrics", [])]
        ir.notifications = [IRNotification(**n) for n in d.get("notifications", [])]
        ir.integrations = [IRIntegration(**i) for i in d.get("integrations", [])]
        ir.clarifying_questions = [IRClarifyingQuestion(**q) for q in d.get("clarifying_questions", [])]
        ir.clarifications = dict(d.get("clarifications") or {})
        return ir

    # -----------------------------------------------------------------------
    # Convenience accessors
    # -----------------------------------------------------------------------

    def get_entity(self, name: str) -> IREntity | None:
        name_lower = name.lower()
        for e in self.entities:
            if e.name.lower() == name_lower or e.table.lower() == name_lower:
                return e
        return None

    def fk_fields(self, entity: IREntity) -> list[IRField]:
        return [f for f in entity.fields if f.type == AetherType.FK]

    def has_low_confidence(self, threshold: float = 0.6) -> bool:
        return bool(self.clarifying_questions) or any(
            f.confidence < threshold
            for e in self.entities
            for f in e.fields
        )
