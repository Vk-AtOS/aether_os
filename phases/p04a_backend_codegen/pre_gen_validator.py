"""Pre-generation architecture validator for p04a.

Runs BEFORE any LLM call in p04a.  Catches structural problems in the domain IR /
entity list that would cause code generation or seed data to fail at runtime.
No async, no LLM, no external deps beyond stdlib.

Public API
----------
    run_pre_gen_checks(domain_ir: dict) -> PreGenReport
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# SQLAlchemy / Python reserved names that collide with generated code
_RESERVED_NAMES = frozenset({
    "Base", "User", "Session", "Query", "Model",
    "Column", "Table", "Index", "Metadata",
    "Integer", "String", "Boolean", "Float", "Text",
    "DateTime", "Date", "Enum", "JSON",
    "Engine", "Connection", "Transaction",
    "type", "id", "in", "is", "not", "and", "or",
})


@dataclass
class PreGenReport:
    """Result returned by run_pre_gen_checks()."""
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── Individual checks ─────────────────────────────────────────────────────────

def check_entity_fk_ordering(entities: List[Dict]) -> List[str]:
    """Detect circular FK references (A → B → A) that break seed-data generation.

    Parameters
    ----------
    entities:
        List of entity dicts, each with at least {"name": str, "fields": list}.
        Field dicts may contain {"name": str, "type": str} where type patterns
        like "ForeignKey('table.id')" indicate a FK relationship.

    Returns
    -------
    List of error strings (empty means no circular deps found).
    """
    errors: List[str] = []
    # Build a dependency graph: entity → set of entities it FK-references
    graph: Dict[str, set] = {}
    entity_names = {(e.get("name") or "").lower() for e in entities}

    for entity in entities:
        name = (entity.get("name") or "").lower()
        if not name:
            continue
        deps: set = set()
        for field_def in entity.get("fields", []):
            ftype = str(field_def.get("type", "")).lower()
            # Detect patterns: ForeignKey('tablename.id'), Integer FK, etc.
            if "foreignkey" in ftype or "foreign_key" in ftype:
                # Extract table name from e.g. ForeignKey('orders.id')
                import re
                match = re.search(r"['\"]([a-z_]+)\.", ftype)
                if match:
                    ref_table = match.group(1)
                    # Map table name back to entity name (strip trailing 's' heuristic)
                    for ename in entity_names:
                        if ename == ref_table or ename + "s" == ref_table or ename == ref_table + "s":
                            if ename != name:
                                deps.add(ename)
        graph[name] = deps

    # Cycle detection via DFS
    visited: set = set()
    rec_stack: set = set()

    def _dfs(node: str) -> Optional[str]:
        visited.add(node)
        rec_stack.add(node)
        for neighbour in graph.get(node, set()):
            if neighbour not in visited:
                cycle = _dfs(neighbour)
                if cycle:
                    return cycle
            elif neighbour in rec_stack:
                return f"{node} -> {neighbour}"
        rec_stack.discard(node)
        return None

    for node in list(graph):
        if node not in visited:
            cycle_path = _dfs(node)
            if cycle_path:
                errors.append(
                    f"circular_fk: circular foreign-key reference detected: {cycle_path}. "
                    "Seed data generation will deadlock — remove or break the cycle."
                )

    return errors


def check_unique_fields_identified(entities: List[Dict]) -> List[str]:
    """Warn when email/username fields lack a unique marker.

    These fields need unique values in seed data.  If the entity definition does
    not mark them unique, the seed generator may produce duplicates that trigger
    DB constraint violations at startup.

    Returns warnings (not errors) — the field may still be unique even if not
    explicitly declared.
    """
    warnings: List[str] = []
    _implicit_unique = {"email", "username", "slug", "phone", "file_path"}

    for entity in entities:
        name = entity.get("name", "?")
        for field_def in entity.get("fields", []):
            fname = (field_def.get("name") or "").lower()
            if fname not in _implicit_unique:
                continue
            # Accept explicit unique markers in various formats
            is_unique = (
                field_def.get("unique")
                or "unique" in str(field_def.get("type", "")).lower()
                or "unique" in str(field_def.get("constraints", "")).lower()
            )
            if not is_unique:
                warnings.append(
                    f"implicit_unique: entity '{name}' has field '{fname}' which "
                    "should be unique but is not explicitly marked. "
                    "Seed generator will use unique patterns for this field automatically."
                )

    return warnings


def check_no_reserved_names(entities: List[Dict]) -> List[str]:
    """Warn when an entity name collides with SQLAlchemy / Python builtins.

    Entity names like 'User', 'Base', 'Session' shadow SQLAlchemy declarations
    and can cause subtle import-time errors in generated models.py.
    """
    warnings: List[str] = []
    for entity in entities:
        name = entity.get("name", "")
        if name in _RESERVED_NAMES:
            warnings.append(
                f"reserved_name: entity '{name}' collides with a SQLAlchemy or "
                "Python builtin name. Rename to avoid model-class shadowing "
                "(e.g. 'AppUser' instead of 'User')."
            )
    return warnings


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_pre_gen_checks(domain_ir: Dict) -> PreGenReport:
    """Run all pre-generation checks against the domain IR dict.

    Parameters
    ----------
    domain_ir:
        The domain IR dict produced by p02b or the entity list from p01/p02.
        Expected shape: {"entities": [{"name": str, "fields": [...]}], ...}
        Gracefully handles missing keys.

    Returns
    -------
    PreGenReport
        ``passed`` is False ONLY for circular FK errors (those will definitely
        break seed generation).  All other issues are warnings.
    """
    entities: List[Dict] = domain_ir.get("entities") or []

    all_errors: List[str] = []
    all_warnings: List[str] = []

    # Check 1: circular FK refs — hard error (seed will deadlock)
    try:
        fk_errors = check_entity_fk_ordering(entities)
        all_errors.extend(fk_errors)
    except Exception as exc:
        logger.warning("[pre_gen_validator] FK ordering check failed (non-fatal): %s", exc)

    # Check 2: implicit unique fields — warning only
    try:
        unique_warnings = check_unique_fields_identified(entities)
        all_warnings.extend(unique_warnings)
    except Exception as exc:
        logger.warning("[pre_gen_validator] unique field check failed (non-fatal): %s", exc)

    # Check 3: reserved entity names — warning only
    try:
        name_warnings = check_no_reserved_names(entities)
        all_warnings.extend(name_warnings)
    except Exception as exc:
        logger.warning("[pre_gen_validator] reserved name check failed (non-fatal): %s", exc)

    passed = len(all_errors) == 0

    if not passed:
        logger.warning(
            "[pre_gen_validator] PRE-GEN CHECKS FAILED: %d errors, %d warnings — %s",
            len(all_errors), len(all_warnings), all_errors,
        )
    else:
        logger.info(
            "[pre_gen_validator] pre-gen checks passed (%d warnings)",
            len(all_warnings),
        )
    for w in all_warnings:
        logger.warning("[pre_gen_validator] warning: %s", w)

    return PreGenReport(passed=passed, errors=all_errors, warnings=all_warnings)
