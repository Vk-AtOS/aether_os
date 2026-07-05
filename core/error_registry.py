"""Categorized error registry for the AetherOS pipeline.

Records every failure category seen during code generation so we can track
whether old categories re-emerge or new ones appear over time.

Data is persisted to ``core/error_registry.json`` as a JSON array.  The file
is created automatically on first write if it does not exist.

Usage
-----
    from aether_os.core.error_registry import ErrorRegistry, ErrorCategory

    registry = ErrorRegistry()
    registry.record(ErrorCategory.RELATIVE_IMPORT, "p04a", "from .models import X")
    summary = registry.get_summary()
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default path — lives alongside this module in the core/ package
_DEFAULT_JSON_PATH = Path(__file__).parent / "error_registry.json"


class ErrorCategory(Enum):
    RELATIVE_IMPORT = "relative_import"
    AST_PARSE_FAILURE = "ast_parse_failure"
    MISSING_ALL_ROUTERS = "missing_all_routers"
    SEED_UNIQUE_VIOLATION = "seed_unique_violation"
    MISSING_ROUTER_REFERENCE = "missing_router_reference"
    UNKNOWN = "unknown"


class ErrorRegistry:
    """File-backed error registry.

    Parameters
    ----------
    json_path:
        Path to the JSON backing file.  Defaults to ``core/error_registry.json``.
        The file is created with ``[]`` if it does not exist.
    """

    def __init__(self, json_path: Optional[Path] = None) -> None:
        self._path = json_path or _DEFAULT_JSON_PATH
        self._ensure_file()

    # ── Public API ────────────────────────────────────────────────────────────

    def record(
        self,
        category: ErrorCategory,
        phase: str,
        detail: str,
        fix_applied: bool = False,
        run_id: str = "",
    ) -> None:
        """Append a new error entry to the registry.

        Parameters
        ----------
        category:
            The ``ErrorCategory`` enum member for this failure.
        phase:
            Pipeline phase identifier, e.g. ``"p04a"``.
        detail:
            Human-readable detail string — typically the validator error message.
        fix_applied:
            Set to True when the pipeline automatically remediated the issue.
        run_id:
            Optional pipeline run identifier.  Existing entries without this
            field have an implicit run_id of "" (backwards compatible).
        """
        entry = {
            "category": category.value,
            "phase": phase,
            "detail": detail,
            "fix_applied": fix_applied,
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            entries = self._load()
            entries.append(entry)
            self._save(entries)
            logger.debug(
                "[error_registry] recorded %s in %s: %s",
                category.value, phase, detail[:120],
            )
        except Exception as exc:
            logger.warning("[error_registry] record() failed (non-fatal): %s", exc)

    def get_summary(self) -> Dict:
        """Return per-category counts and most-recent seen timestamps.

        Returns
        -------
        dict
            ``{"by_category": {"relative_import": {"count": 3, "last_seen": "..."}}, ...}``
        """
        try:
            entries = self._load()
        except Exception as exc:
            logger.warning("[error_registry] get_summary() load failed: %s", exc)
            return {"by_category": {}, "total": 0}

        by_category: Dict[str, Dict] = {}
        for entry in entries:
            cat = entry.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = {"count": 0, "last_seen": None, "fix_count": 0}
            by_category[cat]["count"] += 1
            ts = entry.get("timestamp")
            if ts and (
                by_category[cat]["last_seen"] is None
                or ts > by_category[cat]["last_seen"]
            ):
                by_category[cat]["last_seen"] = ts
            if entry.get("fix_applied"):
                by_category[cat]["fix_count"] += 1

        return {"by_category": by_category, "total": len(entries)}

    def get_for_run(self, run_id: str) -> List[Dict]:
        """Return all error entries for a specific run_id.

        Entries recorded before this field existed (run_id absent or "") are
        excluded.  Returns an empty list when run_id is blank or not found.
        """
        if not run_id:
            return []
        try:
            entries = self._load()
        except Exception as exc:
            logger.warning("[error_registry] get_for_run() load failed: %s", exc)
            return []
        return [e for e in entries if e.get("run_id") == run_id]

    def mark_fixed(self, category: ErrorCategory, fix_description: str) -> None:
        """Append a fix-record entry for a previously seen category.

        This does not mutate existing entries — it adds a new entry with
        ``fix_applied=True`` and the description embedded in ``detail``.
        """
        self.record(
            category=category,
            phase="fix",
            detail=f"[FIX] {fix_description}",
            fix_applied=True,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ensure_file(self) -> None:
        """Create the JSON file with an empty list if it does not exist."""
        try:
            if not self._path.exists():
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text("[]", encoding="utf-8")
        except Exception as exc:
            logger.warning("[error_registry] could not create backing file: %s", exc)

    def _load(self) -> List[Dict]:
        """Load and return the JSON array from disk."""
        try:
            text = self._path.read_text(encoding="utf-8").strip()
            if not text:
                return []
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("[error_registry] JSON decode error, resetting: %s", exc)
            return []

    def _save(self, entries: List[Dict]) -> None:
        """Write the JSON array back to disk atomically via a temp file swap."""
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as exc:
            logger.warning("[error_registry] save failed: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except Exception as cleanup_exc:
                logger.warning("[error_registry] tmp cleanup failed: %s", cleanup_exc)


# Module-level singleton — import and use directly
_registry: Optional[ErrorRegistry] = None


def get_registry() -> ErrorRegistry:
    """Return the module-level singleton ErrorRegistry instance."""
    global _registry
    if _registry is None:
        _registry = ErrorRegistry()
    return _registry
