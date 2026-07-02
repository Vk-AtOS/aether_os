"""Post-generation deterministic backend validator for p04a.

Runs after code generation and before the pipeline advances.  Zero LLM calls,
no async — pure AST + regex checks designed to catch the failure modes we have
seen most frequently in production.

Public API
----------
    validate_generated_backend(files: dict[str, str]) -> ValidationReport
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    """Structured result returned by validate_generated_backend()."""
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Category names matching ErrorCategory.value strings for registry recording
    categories: List[str] = field(default_factory=list)


# ── Individual checks ─────────────────────────────────────────────────────────

def check_no_relative_imports(code: str) -> List[str]:
    """Return a list of error messages for every relative import found.

    Catches patterns like:
      from . import x
      from .module import x
      from .. import x
      from ..module import x
      from..module import x   (no space — Bedrock Nova variant)

    The crud_generator already applies a regex sanitiser for a subset of these,
    but it only targets known module names (schemas/models/database/auth).  This
    check is broader and acts as the final verification pass.
    """
    errors: List[str] = []
    # Match both spaced (from . import) and no-space (from..module) variants
    pattern = re.compile(r"from\s*\.+\s*\w*\s+import", re.MULTILINE)
    for match in pattern.finditer(code):
        line_no = code[: match.start()].count("\n") + 1
        errors.append(
            f"relative_import: line {line_no}: {match.group().strip()!r}"
        )
    return errors


def check_ast_parse(filename: str, code: str) -> List[str]:
    """Return a single-element list with the SyntaxError message, or empty list.

    Uses compile() rather than ast.parse() because compile() catches duplicate
    keyword arguments (e.g. Column(default=True, default=False)) that ast.parse()
    silently accepts on Python 3.10.
    """
    try:
        compile(code, filename, "exec")
        return []
    except SyntaxError as exc:
        msg = f"ast_parse_failure: {filename}: line {exc.lineno}: {exc.msg}"
        logger.warning("[validator] SyntaxError in %s: %s", filename, exc)
        return [msg]
    except Exception as exc:
        msg = f"ast_parse_failure: {filename}: {exc}"
        logger.warning("[validator] Compile error in %s: %s", filename, exc)
        return [msg]


def check_all_routers_exported(crud_code: str) -> List[str]:
    """Verify crud.py defines the all_routers list that main.py imports.

    main.py relies on:
        from routers.crud import all_routers
        for router in all_routers:
            app.include_router(router, prefix="/api")

    If all_routers is missing the app will fail at startup with an ImportError.
    """
    # Look for any assignment to all_routers at module level
    if re.search(r"^all_routers\s*=", crud_code, re.MULTILINE):
        return []
    return [
        "missing_all_routers: routers/crud.py does not define 'all_routers' — "
        "main.py will fail to start"
    ]


def check_seed_unique_fields(seed_code: str, model_code: str) -> List[str]:
    """Detect duplicate values for fields that are declared unique in models.py.

    Strategy:
    1. Parse model_code to find column names annotated with unique=True.
    2. For each unique field name, collect every string literal assigned to
       that keyword in seed.py (e.g. email="alice@x.com").
    3. Report duplicates found within the seed file.

    This is intentionally conservative — it only flags clear duplicates; it
    does not try to evaluate dynamic expressions.
    """
    errors: List[str] = []

    # ── Step 1: find unique field names from models.py ───────────────────────
    # Pattern: column_name = Column(..., unique=True, ...) on a single logical line.
    # We match the identifier that precedes the = Column( declaration.
    unique_fields: set[str] = set()
    col_pattern = re.compile(
        r"^\s*(\w+)\s*=\s*Column\s*\(.*?\bunique\s*=\s*True",
        re.MULTILINE | re.DOTALL,
    )
    for m in col_pattern.finditer(model_code):
        unique_fields.add(m.group(1))

    # Always treat these well-known fields as unique even if not detected above
    unique_fields.update({"email", "username", "slug", "file_path"})

    if not unique_fields:
        return []

    # ── Step 2: extract keyword-argument string literals from seed.py ────────
    # Match patterns like:  email="alice@example.com"  or  email='alice@example.com'
    kw_pattern = re.compile(
        r'\b(' + "|".join(re.escape(f) for f in unique_fields) + r')\s*=\s*(["\'])(.+?)\2',
        re.MULTILINE,
    )

    seen: Dict[str, List[str]] = {}
    for m in kw_pattern.finditer(seed_code):
        fname = m.group(1)
        value = m.group(3)
        seen.setdefault(fname, []).append(value)

    for fname, values in seen.items():
        if len(values) != len(set(values)):
            dupes = [v for v in set(values) if values.count(v) > 1]
            errors.append(
                f"seed_unique_violation: field '{fname}' has duplicate values "
                f"in seed.py: {dupes}"
            )
            logger.warning(
                "[validator] seed unique violation for field '%s': %s",
                fname, dupes,
            )

    return errors


# ── Orchestrator ──────────────────────────────────────────────────────────────

# Files that are hard-required for a valid generated backend
_REQUIRED_FILES = {"models.py", "schemas.py", "seed.py", "routers/crud.py"}

# AST parse is mandatory for these files; a failure is a hard error
_HARD_PARSE_FILES = {"models.py", "schemas.py", "routers/crud.py"}

# Category constants (must match ErrorCategory enum values in error_registry.py)
_CAT_RELATIVE_IMPORT = "relative_import"
_CAT_AST_PARSE = "ast_parse_failure"
_CAT_MISSING_ALL_ROUTERS = "missing_all_routers"
_CAT_SEED_UNIQUE = "seed_unique_violation"


def validate_generated_backend(files: Dict[str, str]) -> ValidationReport:
    """Run all deterministic checks on the generated backend files.

    Parameters
    ----------
    files:
        Mapping of ``relative_path → source_code`` for every file that was
        written to disk by p04a (e.g. ``{"models.py": "...", "routers/crud.py": "..."}``)

    Returns
    -------
    ValidationReport
        ``passed`` is True only when there are no hard errors (AST parse failures
        or missing all_routers).  Relative imports are treated as warnings when the
        sanitiser has already run (they degrade gracefully); seed duplicates are
        also warnings.
    """
    all_errors: List[str] = []
    all_warnings: List[str] = []
    categories: List[str] = []

    # ── 1. AST parse check — hard error ──────────────────────────────────────
    for filename in _HARD_PARSE_FILES:
        code = files.get(filename, "")
        if not code:
            continue
        parse_errors = check_ast_parse(filename, code)
        if parse_errors:
            all_errors.extend(parse_errors)
            if _CAT_AST_PARSE not in categories:
                categories.append(_CAT_AST_PARSE)

    # Also parse-check seed.py but treat as warning (seed failure is non-fatal)
    seed_code = files.get("seed.py", "")
    if seed_code:
        seed_parse_errors = check_ast_parse("seed.py", seed_code)
        if seed_parse_errors:
            all_warnings.extend(seed_parse_errors)
            if _CAT_AST_PARSE not in categories:
                categories.append(_CAT_AST_PARSE)

    # ── 2. all_routers export check — hard error ──────────────────────────────
    crud_code = files.get("routers/crud.py", "")
    if crud_code:
        router_errors = check_all_routers_exported(crud_code)
        if router_errors:
            all_errors.extend(router_errors)
            if _CAT_MISSING_ALL_ROUTERS not in categories:
                categories.append(_CAT_MISSING_ALL_ROUTERS)

    # ── 3. Relative import check — warning (sanitiser may have already fixed) ─
    for filename, code in files.items():
        if not code:
            continue
        rel_errors = check_no_relative_imports(code)
        if rel_errors:
            prefixed = [f"{filename}: {e}" for e in rel_errors]
            all_warnings.extend(prefixed)
            if _CAT_RELATIVE_IMPORT not in categories:
                categories.append(_CAT_RELATIVE_IMPORT)
            logger.warning(
                "[validator] %d relative import(s) in %s — these may have been "
                "missed by the sanitiser",
                len(rel_errors), filename,
            )

    # ── 4. Seed unique-field duplicate check — warning ────────────────────────
    model_code = files.get("models.py", "")
    if seed_code and model_code:
        try:
            unique_errors = check_seed_unique_fields(seed_code, model_code)
            if unique_errors:
                all_warnings.extend(unique_errors)
                if _CAT_SEED_UNIQUE not in categories:
                    categories.append(_CAT_SEED_UNIQUE)
        except Exception as exc:
            logger.warning("[validator] seed unique check failed (non-fatal): %s", exc)

    passed = len(all_errors) == 0

    if passed:
        logger.info(
            "[validator] backend validation PASSED (%d warnings)",
            len(all_warnings),
        )
    else:
        logger.warning(
            "[validator] backend validation FAILED: %d errors, %d warnings — %s",
            len(all_errors), len(all_warnings), all_errors,
        )

    return ValidationReport(
        passed=passed,
        errors=all_errors,
        warnings=all_warnings,
        categories=categories,
    )
