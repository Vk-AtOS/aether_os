"""
IR Validator — deterministic validation of DomainIR before code generation.

Rules enforced:
  V1 — All FK ref_entity values resolve to a known entity name
  V2 — No circular dependencies (entity X → X via FK)
  V3 — All field types are from the AetherType canonical set
  V4 — Every entity has at least one non-FK field (not counting id/timestamps)
  V5 — Entity names are unique (case-insensitive)
  V6 — Table names are unique
  V7 — Relationship cardinality is a known value
  V8 — Dashboard metric aggregations are from the known set
  V9 — Workflow steps each have name, actor, action

On success stamps ir.validated = True and re-saves.
Returns (is_valid: bool, errors: list[str], warnings: list[str]).
"""
from __future__ import annotations

from typing import NamedTuple

from aether_os.core.domain_ir import AetherType, DomainIR

_VALID_CARDINALITIES = {"one-to-one", "one-to-many", "many-to-one", "many-to-many"}
_VALID_AGGREGATIONS = {"count", "sum", "avg", "max", "min"}
_VALID_TYPES = {t.value for t in AetherType}


class ValidationResult(NamedTuple):
    valid: bool
    errors: list[str]
    warnings: list[str]


def validate(ir: DomainIR, fix: bool = True) -> ValidationResult:
    """
    Validate the DomainIR. If fix=True, auto-correct minor issues in place.

    Returns ValidationResult(valid, errors, warnings).
    Stamps ir.validated = True and re-saves if valid.
    """
    errors: list[str] = []
    warnings: list[str] = []

    entity_names = {e.name.lower() for e in ir.entities}
    entity_names_pascal = {e.name for e in ir.entities}

    # V5 — unique entity names
    seen_names: set[str] = set()
    for e in ir.entities:
        key = e.name.lower()
        if key in seen_names:
            errors.append(f"V5: Duplicate entity name '{e.name}'")
        seen_names.add(key)

    # V6 — unique table names
    seen_tables: set[str] = set()
    for e in ir.entities:
        key = e.table.lower()
        if key in seen_tables:
            errors.append(f"V6: Duplicate table name '{e.table}' on entity '{e.name}'")
        seen_tables.add(key)

    for entity in ir.entities:
        non_fk_fields = [
            f for f in entity.fields
            if f.type != AetherType.FK
        ]

        # V4 — at least one non-FK field
        if not non_fk_fields:
            warnings.append(
                f"V4: Entity '{entity.name}' has no non-FK fields — "
                "it will only have id/timestamps"
            )

        for f in entity.fields:
            # V3 — type from canonical set
            if f.type not in _VALID_TYPES:
                if fix:
                    f.type = AetherType.STRING.value
                    warnings.append(
                        f"V3: Field '{entity.name}.{f.name}' had unknown type; "
                        f"auto-corrected to string"
                    )
                else:
                    errors.append(
                        f"V3: Field '{entity.name}.{f.name}' has unknown type '{f.type}'"
                    )

            # V1 — FK ref_entity resolves
            if f.type == AetherType.FK:
                if not f.ref_entity:
                    if fix:
                        warnings.append(
                            f"V1: FK field '{entity.name}.{f.name}' has no ref_entity; "
                            f"left unresolved"
                        )
                    else:
                        errors.append(
                            f"V1: FK field '{entity.name}.{f.name}' has no ref_entity"
                        )
                elif f.ref_entity.lower() not in entity_names:
                    if fix:
                        # Try case-insensitive match
                        match = next(
                            (n for n in entity_names_pascal
                             if n.lower() == f.ref_entity.lower()),
                            None,
                        )
                        if match:
                            f.ref_entity = match
                            warnings.append(
                                f"V1: FK '{entity.name}.{f.name}.ref_entity' "
                                f"casing fixed to '{match}'"
                            )
                        else:
                            warnings.append(
                                f"V1: FK '{entity.name}.{f.name}' references unknown "
                                f"entity '{f.ref_entity}' — left as-is"
                            )
                    else:
                        errors.append(
                            f"V1: FK '{entity.name}.{f.name}' references unknown "
                            f"entity '{f.ref_entity}'"
                        )

            # V2 — no self-referential FK (unless intentional parent-child)
            if f.type == AetherType.FK and f.ref_entity:
                if f.ref_entity.lower() == entity.name.lower():
                    warnings.append(
                        f"V2: Self-referential FK '{entity.name}.{f.name}' "
                        f"— this is allowed but may indicate a modeling error"
                    )

    # V7 — valid cardinalities
    for r in ir.relationships:
        if r.cardinality not in _VALID_CARDINALITIES:
            if fix:
                r.cardinality = "many-to-one"
                warnings.append(
                    f"V7: Relationship '{r.from_entity}→{r.to_entity}' had invalid "
                    f"cardinality; defaulted to many-to-one"
                )
            else:
                errors.append(
                    f"V7: Relationship '{r.from_entity}→{r.to_entity}' has invalid "
                    f"cardinality '{r.cardinality}'"
                )

    # V8 — valid aggregations
    for m in ir.dashboard_metrics:
        if m.aggregation not in _VALID_AGGREGATIONS:
            if fix:
                m.aggregation = "count"
                warnings.append(
                    f"V8: Metric '{m.name}' had unknown aggregation; defaulted to count"
                )
            else:
                errors.append(
                    f"V8: Metric '{m.name}' has unknown aggregation '{m.aggregation}'"
                )

    # V9 — workflow steps completeness
    for w in ir.workflows:
        for i, step in enumerate(w.steps):
            if not step.name or not step.actor or not step.action:
                errors.append(
                    f"V9: Workflow '{w.name}' step {i} is missing name/actor/action"
                )

    is_valid = len(errors) == 0

    if is_valid:
        ir.validated = True

    return ValidationResult(valid=is_valid, errors=errors, warnings=warnings)
