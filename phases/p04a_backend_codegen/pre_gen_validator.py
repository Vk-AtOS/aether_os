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
import re
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

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_UNSAFE_TEXT = re.compile(r"[\'\"\\\x00-\x1f`]")


def check_identifiers(entities: List[Dict], business_rules: Optional[List[Dict]] = None) -> List[str]:
    """Names that are written into generated Python/SQL source must be plain identifiers (KAN-169).

    Entity, table, field and reference names, rule names and enum values come from a model-written spec; one
    containing a quote or a newline would become code in models.py / schemas.py / crud.py. Reject, never escape.
    """
    errors: List[str] = []

    def bad_ident(kind: str, value) -> None:
        if value not in (None, "") and not (isinstance(value, str) and _IDENT.match(value)):
            errors.append(f"unsafe_name: {kind} {str(value)[:40]!r} is not a plain identifier")

    for e in entities:
        bad_ident("entity name", e.get("name"))
        bad_ident("table name", e.get("table"))
        for f in e.get("fields") or []:
            if not isinstance(f, dict):
                continue
            bad_ident("field name", f.get("name"))
            bad_ident("referenced entity", f.get("ref_entity"))
            for v in f.get("enum_values") or []:
                if not isinstance(v, str) or _UNSAFE_TEXT.search(v):
                    errors.append(f"unsafe_name: enum value {str(v)[:40]!r} of field {f.get('name')!r} contains a quote, backslash or control character")
    for rule in business_rules or []:
        bad_ident("business rule entity", rule.get("entity"))
    return errors


def _fk_edges(entities: List[Dict]) -> Dict[str, Dict[str, bool]]:
    """entity -> {referenced entity: every FK between the two is NOT NULL}. Reads IR fields (type 'fk' with
    ref_entity) and legacy ForeignKey('table.id') type strings."""
    names = {(e.get("name") or "").lower() for e in entities if e.get("name")}
    tables = {(e.get("table") or "").lower(): (e.get("name") or "").lower() for e in entities}
    graph: Dict[str, Dict[str, bool]] = {}
    for e in entities:
        name = (e.get("name") or "").lower()
        if not name:
            continue
        deps: Dict[str, bool] = graph.setdefault(name, {})
        for f in e.get("fields") or []:
            if not isinstance(f, dict):
                continue
            ftype = str(f.get("type", "")).lower()
            target = None
            if ftype == "fk" and f.get("ref_entity"):
                target = str(f["ref_entity"]).lower()
            elif "foreignkey" in ftype or "foreign_key" in ftype:
                m = re.search(r"['\"]([a-z_]+)\.", ftype)
                if m:
                    t = m.group(1)
                    target = tables.get(t) or next((n for n in names if n in (t, t + "s", t.rstrip("s"))), None)
            if target and target in names and target != name:
                required = f.get("nullable") is False
                deps[target] = deps.get(target, True) and required
    return graph


def check_entity_fk_ordering(entities: List[Dict]) -> List[str]:
    """Detect circular FK references (A -> B -> A). A cycle whose every foreign key is NOT NULL cannot be seeded
    or inserted (each row needs the other first): error. If some key in the cycle is nullable the cycle can be
    broken by inserting NULL first: it is reported by check_fk_cycles_nullable as a warning.

    Reads both IR fields (type 'fk' + ref_entity) and ForeignKey('table.id') type strings; before, only the
    latter were read, so no IR cycle was ever found (KAN-169).
    """
    return [m for m in _fk_cycles(entities) if m.startswith("circular_fk:")]


def check_fk_cycles_nullable(entities: List[Dict]) -> List[str]:
    return [m for m in _fk_cycles(entities) if m.startswith("circular_fk_nullable:")]


def _fk_cycles(entities: List[Dict]) -> List[str]:
    graph = _fk_edges(entities)
    found: List[str] = []
    seen_cycles: set = set()

    def dfs(node: str, path: List[str]) -> None:
        for nxt in graph.get(node, {}):
            if nxt in path:
                cyc = path[path.index(nxt):] + [nxt]
                key = frozenset(cyc)
                if key in seen_cycles:
                    continue
                seen_cycles.add(key)
                hard = all(graph[a][b] for a, b in zip(cyc, cyc[1:]))
                label = "circular_fk" if hard else "circular_fk_nullable"
                found.append(f"{label}: foreign keys form a cycle {' -> '.join(cyc)}"
                             + ("; every key is NOT NULL, so no row can be inserted first" if hard else
                                "; seed rows must insert one side with NULL first"))
            elif nxt not in path:
                dfs(nxt, path + [nxt])

    for n in list(graph):
        dfs(n, [n])
    return found


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

    # Check 1b: names that become source code must be plain identifiers (code injection) — hard error
    all_errors.extend(check_identifiers(entities, domain_ir.get("business_rules")))
    all_warnings.extend(check_fk_cycles_nullable(entities))

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


# ── Relative import fixer ─────────────────────────────────────────────────────

def fix_relative_imports(code: str, src_package: str = "src") -> str:
    """Scan code for relative imports and rewrite them as absolute imports.

    Relative imports (from . / from .. / from ...) break when the generated
    app's src/ directory is loaded as a flat package by uvicorn.  This function
    converts them to absolute imports using src_package as the root name.

    Pattern fixes (in priority order):
      from .models import X      → from models import X
      from .schemas import X     → from schemas import X
      from ..models import X     → from models import X
      from . import models       → import models

    The src_package parameter is accepted for forward-compatibility but the
    generated apps always run with src/ on sys.path, so the absolute name is
    just the bare module name (no package prefix).

    Logs every substitution made so the operator can audit what was fixed.

    Args:
        code: Python source code string (may be multi-line).
        src_package: Reserved — not used in rewrite; bare module names are correct.

    Returns:
        Fixed source code string.
    """
    lines = code.splitlines(keepends=True)
    fixed_lines = []
    for line in lines:
        original = line

        # Pattern 1: "from .module import X" or "from ..module import X"
        # Captures: optional spaces, one or more dots, optional module name, import clause
        m = re.match(r'^(\s*)from\s*\.+\s*(\w+)\s+import\s+(.+)$', line.rstrip('\n'))
        if m:
            indent, module, imports = m.group(1), m.group(2), m.group(3)
            fixed = f"{indent}from {module} import {imports}\n"
            if fixed != original:
                logger.info(
                    "[p04a] fix_relative_imports: %r → %r",
                    original.rstrip('\n'), fixed.rstrip('\n'),
                )
                fixed_lines.append(fixed)
                continue

        # Pattern 2: "from . import module" (bare relative import of a module)
        m2 = re.match(r'^(\s*)from\s*\.\s+import\s+(.+)$', line.rstrip('\n'))
        if m2:
            indent, imports = m2.group(1), m2.group(2)
            fixed = f"{indent}import {imports}\n"
            if fixed != original:
                logger.info(
                    "[p04a] fix_relative_imports: %r → %r",
                    original.rstrip('\n'), fixed.rstrip('\n'),
                )
                fixed_lines.append(fixed)
                continue

        # Pattern 3: no-space variant "from..module import X" (Bedrock Nova style)
        m3 = re.match(r'^(\s*)from\.+(\w+)\s+import\s+(.+)$', line.rstrip('\n'))
        if m3:
            indent, module, imports = m3.group(1), m3.group(2), m3.group(3)
            fixed = f"{indent}from {module} import {imports}\n"
            if fixed != original:
                logger.info(
                    "[p04a] fix_relative_imports: %r → %r",
                    original.rstrip('\n'), fixed.rstrip('\n'),
                )
                fixed_lines.append(fixed)
                continue

        fixed_lines.append(line)

    return "".join(fixed_lines)
