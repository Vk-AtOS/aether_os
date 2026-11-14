"""
Stage 3: BACKEND — shared utilities.

validate_backend_output: checks that key FastAPI source files are present.
get_entity_count:        counts entity-level CRUD routers in routers/.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Files that must exist per backend language (relative to the backend root).
_REQUIRED_FILES_BY_LANG = {
    "python": ["src/main.py", "src/models.py", "src/routers/crud.py", "src/seed.py", "src/auth.py"],
    "go": ["main.go", "go.mod"],
    "typescript": ["package.json", "src/index.ts"],
}
_REQUIRED_FILES = _REQUIRED_FILES_BY_LANG["python"]  # kept for importers


def detect_backend_lang(root: Path) -> str:
    """Language of the generated backend, from its marker files (python is the default)."""
    if (root / "go.mod").is_file() or (root / "main.go").is_file():
        return "go"
    if (root / "package.json").is_file() and not (root / "src" / "main.py").is_file():
        return "typescript"
    return "python"


def validate_backend_output(output_path: str) -> list[str]:
    """Return a list of required files that are missing from *output_path*.

    The required set depends on the backend language (FastAPI, Go or TypeScript),
    detected from the generated files; an empty list means the backend is
    structurally complete. An absent or non-directory path reports the Python set.
    """
    if not output_path:
        return list(_REQUIRED_FILES)

    root = Path(output_path)
    if not root.is_dir():
        logger.warning("validate_backend_output: path does not exist or is not a dir: %s", output_path)
        return list(_REQUIRED_FILES)

    required = _REQUIRED_FILES_BY_LANG[detect_backend_lang(root)]
    missing = [rel for rel in required if not (root / rel).is_file()]
    if missing:
        logger.debug("validate_backend_output: %d missing file(s): %s", len(missing), missing)
    return missing


def get_entity_count(output_path: str) -> int:
    """Count the number of entity-level CRUD routers in *output_path*/src/routers/.

    Each ``*.py`` file in the routers directory (excluding ``__init__.py``,
    ``auth.py``, ``crud.py``, ``stats.py``, ``realtime_router.py``, and
    ``pipeline_events.py``) is treated as one entity router.  Falls back to
    counting ``APIRouter`` declarations inside ``routers/crud.py`` when no
    separate per-entity router files are present.

    Args:
        output_path: Absolute path to the backend output directory.

    Returns:
        Integer count of entity routers (0 when the directory is absent).
    """
    if not output_path:
        return 0

    routers_dir = Path(output_path) / "src" / "routers"
    if not routers_dir.is_dir():
        return 0

    # Excluded infrastructure files that are not entity routers
    _excluded = {
        "__init__.py",
        "auth.py",
        "crud.py",
        "stats.py",
        "realtime_router.py",
        "pipeline_events.py",
    }

    per_entity_files = [
        f for f in routers_dir.glob("*.py")
        if f.name not in _excluded
    ]

    if per_entity_files:
        return len(per_entity_files)

    # Fall back: count APIRouter(prefix=...) declarations inside crud.py
    crud_py = routers_dir / "crud.py"
    if crud_py.is_file():
        try:
            import re
            text = crud_py.read_text(encoding="utf-8", errors="ignore")
            prefixes = re.findall(r'APIRouter\([^)]*prefix\s*=\s*["\']', text, re.IGNORECASE)
            return len(prefixes)
        except Exception as exc:
            logger.warning("get_entity_count: failed to read crud.py: %s", exc)

    return 0
