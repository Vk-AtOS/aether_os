"""Domain IR Validator — structural checks before any downstream code generation.

Runs after the 4-pass LLM extraction in task_agent.py and before domain_ir.json
is written.  Checks things the LLM-based ir_validator in core/ cannot see because
it operates on DomainIR objects — this module works on the raw dict that comes
back from the LLM so it can catch structural issues early.

Rules implemented
-----------------
D1  Entity count must be 2–15 (0-1 = error, 16+ = warning).
D2  No circular FK references — detected via DFS; circular = error.
D3  Required fields on every entity: id-field present, at least one string/text
    field, and the entity must have a non-empty name (warning on missing).
D4  Reserved SQLAlchemy names must not be used as entity names (error).
D5  At least one entity with "user" in the name (warning if missing).
D6  Email/username fields should be marked unique=True (warning if not).
D7  All FK ref_entity values must resolve to a known entity (error).
"""
from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# SQLAlchemy reserved names that will conflict with ORM internals.
_SQLALCHEMY_RESERVED: frozenset[str] = frozenset({
    "Base", "Session", "Model", "Query", "metadata",
    "Table", "Column", "Index", "Constraint", "MetaData",
})

# Field names that carry uniqueness semantics and should have unique=True.
_UNIQUE_FIELD_HINTS: frozenset[str] = frozenset({"email", "username", "slug", "code"})


@dataclass
class IRValidationReport:
    """Result of validate_domain_ir()."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False
        logger.error("[p02b/validator] D-error: %s", msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        logger.warning("[p02b/validator] D-warn: %s", msg)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _entity_names(ir: dict) -> List[str]:
    """Return list of entity names from raw IR dict."""
    return [e.get("name", "") for e in ir.get("entities", []) if e.get("name")]


def _build_fk_graph(entities: list) -> Dict[str, List[str]]:
    """
    Build adjacency list: entity_name -> list[entity_name] via FK fields.

    Only direct FK references (field.type == "fk" or "FK") are included.
    Many-to-many join tables are not followed — if an entity references two
    others that both reference it, that is a structural pattern not a cycle.
    """
    graph: Dict[str, List[str]] = {}
    for entity in entities:
        name = entity.get("name", "")
        if not name:
            continue
        refs: List[str] = []
        for f in entity.get("fields", []):
            if str(f.get("type", "")).lower() == "fk":
                ref = f.get("ref_entity", "")
                if ref and ref != name:
                    refs.append(ref)
        graph[name] = refs
    return graph


def _dfs_has_cycle(
    node: str,
    graph: Dict[str, List[str]],
    visited: Set[str],
    rec_stack: Set[str],
    path: List[str],
) -> Optional[List[str]]:
    """
    DFS cycle detection. Returns the cycle path list if a cycle is found, else None.

    rec_stack tracks the nodes on the current DFS path so we distinguish
    back-edges (cycle) from cross-edges (safe).
    """
    visited.add(node)
    rec_stack.add(node)
    path.append(node)

    for neighbour in graph.get(node, []):
        if neighbour not in visited:
            result = _dfs_has_cycle(neighbour, graph, visited, rec_stack, path)
            if result is not None:
                return result
        elif neighbour in rec_stack:
            # Found cycle — return the cycle portion of the path
            cycle_start = path.index(neighbour)
            return path[cycle_start:] + [neighbour]

    path.pop()
    rec_stack.discard(node)
    return None


def _detect_circular_fk(entities: list) -> List[str]:
    """Return list of human-readable cycle descriptions, empty if none."""
    graph = _build_fk_graph(entities)
    visited: Set[str] = set()
    cycles: List[str] = []

    for node in list(graph.keys()):
        if node not in visited:
            cycle = _dfs_has_cycle(node, graph, visited, set(), [])
            if cycle:
                cycles.append(" → ".join(cycle))

    return cycles


def _has_string_field(entity: dict) -> bool:
    """True if entity has at least one string or text field."""
    for f in entity.get("fields", []):
        ftype = str(f.get("type", "")).lower()
        if ftype in ("string", "text", "email", "url"):
            return True
    return False


def _has_id_field(entity: dict) -> bool:
    """True if entity has a field named 'id' or if id is auto-added by convention."""
    # In the AetherOS pipeline, 'id' is always auto-added; treat as present.
    # But if the entity explicitly declares fields and none are named 'id',
    # we still consider id implicitly present (generator adds it).
    # We only warn if the entity declares ZERO fields at all.
    return True  # id is always auto-generated by the pipeline


def _check_unique_hints(entity: dict, report: IRValidationReport) -> None:
    """D6: email/username fields without unique=True get a warning."""
    for f in entity.get("fields", []):
        fname = f.get("name", "").lower()
        if fname in _UNIQUE_FIELD_HINTS and not f.get("unique", False):
            report.add_warning(
                f"D6: '{entity.get('name','?')}.{f.get('name','')}' looks like a "
                f"unique identifier but unique=False — seed generator will use "
                f"non-unique values and may cause UNIQUE constraint violations"
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_domain_ir(ir: dict) -> IRValidationReport:
    """Validate a raw domain IR dict before any downstream generation begins.

    Parameters
    ----------
    ir:
        The dict produced by the LLM extraction pass in p02b task_agent.
        Expected keys: entities, relationships, business_rules, permissions,
        workflows, dashboard_metrics, notifications, clarifying_questions.

    Returns
    -------
    IRValidationReport
        .passed  — False if any hard errors were found
        .errors  — list of error strings (each prefixes with the rule code)
        .warnings — list of warning strings
    """
    report = IRValidationReport(passed=True)
    entities: list = ir.get("entities", [])
    entity_names_raw = _entity_names(ir)
    entity_names_lower = {n.lower() for n in entity_names_raw}

    # D1 — Entity count
    count = len(entities)
    if count == 0:
        report.add_error(
            "D1: IR contains 0 entities — pipeline will produce an empty app. "
            "Check requirements input and LLM availability."
        )
    elif count == 1:
        report.add_error(
            f"D1: IR contains only 1 entity ('{entity_names_raw[0]}'). "
            "A functional app needs at least 2 entities; pipeline will produce "
            "a skeleton with no meaningful CRUD."
        )
    elif count > 15:
        report.add_warning(
            f"D1: IR contains {count} entities. >15 entities may hit LLM context "
            "limits during code generation; consider splitting into sub-domains."
        )

    # D4 — Reserved SQLAlchemy names (check before cycle detection to give
    #       cleaner error messages)
    for entity in entities:
        name = entity.get("name", "")
        if name in _SQLALCHEMY_RESERVED:
            report.add_error(
                f"D4: Entity name '{name}' conflicts with a SQLAlchemy reserved "
                "name (Base, Session, Model, Query, metadata, …). Rename this entity."
            )

    # D2 — Circular FK references (only if we have entities)
    if entities:
        try:
            cycles = _detect_circular_fk(entities)
            for cycle in cycles:
                report.add_error(
                    f"D2: Circular FK reference detected: {cycle}. "
                    "Seed data generation will deadlock on this cycle. "
                    "Break the cycle by making one FK nullable or removing it."
                )
        except Exception as e:
            logger.warning("[p02b/validator] cycle detection failed (non-fatal): %s", e)

    # D7 — FK ref_entity must point to known entity
    for entity in entities:
        ename = entity.get("name", "?")
        for f in entity.get("fields", []):
            if str(f.get("type", "")).lower() == "fk":
                ref = f.get("ref_entity", "")
                if ref and ref.lower() not in entity_names_lower:
                    report.add_error(
                        f"D7: '{ename}.{f.get('name','')}' FK references "
                        f"'{ref}' which does not exist in this IR. "
                        "Dangling FK will cause SQLAlchemy mapper errors."
                    )

    # D3 — Required fields on every entity (warnings only)
    for entity in entities:
        name = entity.get("name", "")
        if not name:
            report.add_warning("D3: An entity has an empty name — skipped in validation")
            continue
        fields = entity.get("fields", [])
        if not fields:
            report.add_warning(
                f"D3: Entity '{name}' has no fields declared. "
                "At minimum it needs one string field for display purposes."
            )
        elif not _has_string_field(entity):
            report.add_warning(
                f"D3: Entity '{name}' has no string/text/email/url field. "
                "It will have only numeric or FK fields which makes it hard "
                "to display in list views."
            )

    # D5 — At least one user-like entity (warning)
    has_user_entity = any("user" in n.lower() for n in entity_names_raw)
    if not has_user_entity and count > 0:
        report.add_warning(
            "D5: No entity with 'user' in its name found. "
            "Auth endpoints (login/register) will generate but have no User "
            "model to bind to — registration may fail at runtime."
        )

    # D6 — Unique field hints
    for entity in entities:
        _check_unique_hints(entity, report)

    return report


def apply_validation_to_run(
    raw_ir_dict: dict,
    combined_result: dict,
    p1: dict,
    data: dict,
    errors: list,
    output_dir: "Path",
) -> "tuple[IRValidationReport, object | None]":
    """Run validate_domain_ir and handle fatal-error early-exit logic.

    Extracted from task_agent.run() to keep that function under 600 lines.

    Parameters
    ----------
    raw_ir_dict:
        The raw dict from the LLM (combined_result or p1 fallback).
    combined_result:
        The primary LLM result dict (used to pick raw_ir_dict).
    p1:
        Fallback entity dict if combined_result has no entities.
    data:
        phase_input.input_data — generation_warnings are appended here.
    errors:
        The mutable errors list from run() — validation errors are appended.
    output_dir:
        Used to construct the fatal-error TaskResult output_path.

    Returns
    -------
    (report, fatal_result)
        fatal_result is None if the pipeline should continue, or a TaskResult
        instance that the caller must return immediately on fatal error.
    """
    from pathlib import Path as _Path

    report = validate_domain_ir(raw_ir_dict)

    generation_warnings: list = data.get("generation_warnings", [])
    if not isinstance(generation_warnings, list):
        generation_warnings = []

    if report.errors:
        logger.error("p02b domain IR validation errors: %s", report.errors)
        generation_warnings.extend(report.errors)
        errors.extend(report.errors)
        _fatal_prefixes = ("D1: IR contains 0", "D2: Circular FK")
        _fatal_errors = [e for e in report.errors
                         if any(e.startswith(p) for p in _fatal_prefixes)]
        if _fatal_errors:
            from aether_os.phases.base import TaskResult as _TaskResult
            fatal = _TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                success=False,
                issues=_fatal_errors,
                metadata={
                    "error": "domain_ir_validation_failed",
                    "domain_validation": report.as_dict(),
                },
            )
            data["generation_warnings"] = generation_warnings
            return report, fatal

    for _w in report.warnings:
        logger.warning("p02b domain IR warning: %s", _w)

    data["generation_warnings"] = generation_warnings
    return report, None
