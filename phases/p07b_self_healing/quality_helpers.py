"""
P07b Quality Helpers — deterministic self-healing patches triggered by QualityMonitor.

Covers two known failure patterns:
  auth_failure  — duplicate UNIQUE-field values in src/seed.py
                  (e.g. two records with the same email/slug/file_path)
  empty_crud    — relative imports in src/routers/crud.py
                  (e.g. `from .schemas import …` instead of `from schemas import …`)

Each fixer returns either the fixed file content (str) or None if no fixable
pattern was found.  The caller is responsible for writing the patched content
back to disk.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from aether_os.core.error_registry import ErrorCategory, get_registry

logger = logging.getLogger(__name__)


def _record_repair(category: ErrorCategory, detail: str, phase: str = "p07b_self_healing") -> None:
    """Record a successful repair to the error registry for future learning."""
    try:
        reg = get_registry()
        reg.record(category=category, phase=phase, detail=detail, fix_applied=True)
    except Exception as e:
        logger.warning("p07b: error_registry record failed (non-fatal): %s", e)


# ── Seed unique-field deduplication ─────────────────────────────────────────────

# Fields that are expected to be UNIQUE in the generated models
_KNOWN_UNIQUE_FIELDS = frozenset({"email", "username", "slug", "file_path", "code", "sku"})


def fix_seed_unique_violations(seed_content: str) -> Optional[str]:
    """Detect duplicate keyword-argument string literals for known unique fields
    in seed.py and make each value unique by appending a sequential suffix.

    Returns the patched content, or None if no duplicates were found.

    Example — before::

        User(email="admin@example.com"),
        User(email="admin@example.com"),   # duplicate → UNIQUE constraint error

    After::

        User(email="admin@example.com"),
        User(email="admin@example.com_2"),  # made unique
    """
    changed = False

    for field_name in _KNOWN_UNIQUE_FIELDS:
        # Pattern: field_name="value" or field_name='value'
        pattern = re.compile(
            r'(\b' + re.escape(field_name) + r'\s*=\s*)(["\'])(.+?)\2',
            re.MULTILINE,
        )

        # Collect all occurrences: (match_start, match_end, value)
        occurrences = [(m.start(), m.end(), m.group(3)) for m in pattern.finditer(seed_content)]

        # Count how many times each value appears
        value_counts: dict[str, int] = {}
        for _, _, val in occurrences:
            value_counts[val] = value_counts.get(val, 0) + 1

        # Only process fields that have at least one duplicate
        has_duplicate = any(c > 1 for c in value_counts.values())
        if not has_duplicate:
            continue

        # Walk through and replace each duplicate (starting from the 2nd occurrence)
        # We rebuild the string from right to left so offsets stay valid
        seen: dict[str, int] = {}
        replacements: list[tuple[int, int, str]] = []

        for start, end, val in occurrences:
            seen[val] = seen.get(val, 0) + 1
            if seen[val] > 1:
                # Append _{n} suffix inside the string literal
                quote = seed_content[start + len(field_name):].lstrip()[1]  # ' or "
                new_val = f"{val}_{seen[val]}"
                replacement = f'{field_name}={quote}{new_val}{quote}'
                replacements.append((start, end, replacement))

        # Apply replacements from right to left to preserve offsets
        for start, end, replacement in reversed(replacements):
            seed_content = seed_content[:start] + replacement + seed_content[end:]
            changed = True
            logger.info(
                "[quality_helpers] Deduped seed field '%s' — applied suffix to occurrence at offset %d",
                field_name, start,
            )

    if changed:
        _record_repair(
            ErrorCategory.SEED_UNIQUE_VIOLATION,
            "Deduplicated UNIQUE-field values in seed.py (suffix appended to duplicates)",
        )
    return seed_content if changed else None


# ── Crud.py relative import fixer ────────────────────────────────────────────────

_RELATIVE_IMPORT_RE = re.compile(
    r'from\s*\.+\s*(\w)',  # from .foo or from ..foo
    re.MULTILINE,
)

_RELATIVE_IMPORT_PLAIN_RE = re.compile(
    r'import\s*\.+\s*(\w)',  # import .foo or import ..foo
    re.MULTILINE,
)


def fix_crud_relative_imports(crud_content: str) -> Optional[str]:
    """Replace relative imports in crud.py with flat absolute imports.

    The generated app runs from the src/ directory so all sibling modules
    (models, schemas, database, auth) are importable without a package prefix.

    Returns the patched content, or None if no relative imports were found.

    Before::

        from .schemas import InvoiceCreate, InvoiceOut
        from ..database import get_db

    After::

        from schemas import InvoiceCreate, InvoiceOut
        from database import get_db
    """
    original = crud_content

    # from .foo → from foo / from ..foo → from foo
    crud_content = _RELATIVE_IMPORT_RE.sub(r'from \1', crud_content)
    # import .foo → import foo
    crud_content = _RELATIVE_IMPORT_PLAIN_RE.sub(r'import \1', crud_content)

    if crud_content == original:
        return None

    logger.info("[quality_helpers] Fixed relative imports in crud.py")
    _record_repair(
        ErrorCategory.RELATIVE_IMPORT,
        "Replaced relative imports (from .X / import .X) with flat absolute imports in crud.py",
    )
    return crud_content


# ── File locators ──────────────────────────────────────────────────────────────

def find_seed_py(project_dir: Path) -> Optional[Path]:
    """Return the path to src/seed.py inside the project, or None if missing."""
    candidates = [
        project_dir / "p04_backend" / "backend_codegen",
        project_dir / "p03_scaffolding",
        project_dir,
    ]
    for base in candidates:
        # Walk subdirectories: the backend lives under a named project subdir
        if not base.exists():
            continue
        for candidate_seed in base.rglob("seed.py"):
            parts = candidate_seed.parts
            # Must be inside a src/ directory and not in __pycache__ or .venv
            if any(skip in parts for skip in ("__pycache__", ".venv", "venv", "node_modules")):
                continue
            if "src" in parts:
                return candidate_seed
    return None


def find_crud_py(project_dir: Path) -> Optional[Path]:
    """Return the path to src/routers/crud.py inside the project, or None if missing."""
    candidates = [
        project_dir / "p04_backend" / "backend_codegen",
        project_dir / "p03_scaffolding",
        project_dir,
    ]
    for base in candidates:
        if not base.exists():
            continue
        for candidate_crud in base.rglob("crud.py"):
            parts = candidate_crud.parts
            if any(skip in parts for skip in ("__pycache__", ".venv", "venv", "node_modules")):
                continue
            if "src" in parts:
                return candidate_crud
    return None
