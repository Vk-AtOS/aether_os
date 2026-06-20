"""
Base dataclasses for the AetherOS domain knowledge system.

Each domain pack exports instances of these types. The loader injects them
into the pipeline so every LLM call receives expert domain context instead
of producing generic CRUD code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FieldDef:
    name: str
    type: str                        # string | int | float | bool | datetime | fk | text
    required: bool = True
    pii: bool = False                # General personal data (GDPR)
    phi: bool = False                # Protected health info (HIPAA)
    pci: bool = False                # Payment card data (PCI-DSS)
    encrypted_at_rest: bool = False
    never_store: bool = False        # e.g. raw CVV — must not be persisted
    description: str = ""


@dataclass
class EntityTemplate:
    name: str                        # PascalCase entity name
    table: str                       # snake_case table name
    description: str
    fields: List[FieldDef] = field(default_factory=list)
    indexes: List[str] = field(default_factory=list)   # field names to index
    audit_trail: bool = False        # all mutations must be logged
    soft_delete: bool = False        # use deleted_at instead of DELETE


@dataclass
class WorkflowTemplate:
    name: str
    entity: str                      # which EntityTemplate this applies to
    field: str                       # the status/state field
    states: List[str] = field(default_factory=list)
    transitions: Dict[str, List[str]] = field(default_factory=dict)  # from → [allowed_tos]
    terminal_states: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class ProcessStep:
    name: str                           # snake_case step identifier
    service_required: str               # which service class handles this step
    method: str                         # method name on the service
    description: str = ""
    input_keys: List[str] = field(default_factory=list)   # context keys needed as input
    on_failure: str = "FAIL"            # FAIL | SKIP | RETRY


@dataclass
class BusinessProcessPipeline:
    name: str                           # PascalCase pipeline name
    trigger: str                        # event type: "create" | "status_change" | "payment"
    trigger_entity: str                 # which entity type fires this trigger
    trigger_condition: str              # human-readable condition (e.g. "status == confirmed")
    steps: List[ProcessStep] = field(default_factory=list)
    integrations_required: List[str] = field(default_factory=list)  # external service names
    description: str = ""


@dataclass
class ComplianceRule:
    standard: str                    # PCI-DSS | HIPAA | GDPR | SOC2 | SOX | TAPA
    rule: str                        # short human-readable rule
    affected_fields: List[str] = field(default_factory=list)
    enforcement: str = "mandatory"   # mandatory | recommended
    implementation_hint: str = ""


@dataclass
class DomainKnowledgePack:
    domain: str
    display_name: str
    entities: List[EntityTemplate] = field(default_factory=list)
    workflows: List[WorkflowTemplate] = field(default_factory=list)
    compliance: List[ComplianceRule] = field(default_factory=list)
    api_patterns: List[str] = field(default_factory=list)
    pipelines: List[BusinessProcessPipeline] = field(default_factory=list)
    prompt_injection: str = ""       # Injected verbatim into every LLM prompt for this domain

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON storage in design_brief."""
        return {
            "domain": self.domain,
            "display_name": self.display_name,
            "prompt_injection": self.prompt_injection,
            "api_patterns": self.api_patterns,
            "entity_names": [e.name for e in self.entities],
            "workflow_names": [w.name for w in self.workflows],
            "compliance_standards": list({r.standard for r in self.compliance}),
            "pii_fields": [
                f"{e.name}.{f.name}"
                for e in self.entities for f in e.fields if f.pii or f.phi or f.pci
            ],
        }

    def compliance_summary(self) -> str:
        """One-paragraph compliance briefing injected into P06 security review."""
        rules = "\n".join(f"  [{r.standard}] {r.rule}" for r in self.compliance)
        return f"Domain: {self.display_name}\nCompliance rules:\n{rules}"

    def schema_hints(self) -> str:
        """Entity + field summary injected into P02 architecture prompt."""
        lines = [f"Domain entity templates for {self.display_name}:"]
        for e in self.entities:
            fnames = ", ".join(f.name for f in e.fields)
            lines.append(f"  {e.name} ({e.table}): {fnames}")
            if e.audit_trail:
                lines.append(f"    → audit trail required on all mutations")
        return "\n".join(lines)

    def workflow_summary(self) -> str:
        """State machine summary injected into P04 backend prompt."""
        lines = []
        for w in self.workflows:
            states = " → ".join(w.states)
            lines.append(f"  {w.name} ({w.entity}.{w.field}): {states}")
        return "Business workflows:\n" + "\n".join(lines) if lines else ""
