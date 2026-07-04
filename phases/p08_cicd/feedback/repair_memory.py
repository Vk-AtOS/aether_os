"""
Repair memory for the AetherOS CI/CD phase.
Persists successful fixes associated with error fingerprints to JSON.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class RepairMemory:
    """Thread-safe persistent memory for repair reuse."""

    def __init__(self, path: str | None = None) -> None:
        if path is None:
            self.path = Path.home() / ".aether_os" / "repair_memory.json"
        else:
            self.path = Path(path)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._memory: Dict[str, Dict[str, Any]] = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception as exc:
                logger.warning("repair_memory: could not load %s: %s", self.path, exc)
        return {}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._memory, indent=2))
        except Exception as exc:
            logger.error("repair_memory: could not save: %s", exc)

    def lookup(self, fp: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._memory.get(fp)

    def record_success(
        self,
        fp: str,
        patch_diff: str,
        confidence: float,
        repo_name: str,
    ) -> None:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            if fp in self._memory:
                entry = self._memory[fp]
                entry["success_count"] += 1
                entry["last_seen"] = now
                entry["patch_diff"] = patch_diff
                entry["confidence"] = confidence
            else:
                self._memory[fp] = {
                    "patch_diff": patch_diff,
                    "confidence": confidence,
                    "repo_name": repo_name,
                    "success_count": 1,
                    "last_seen": now,
                }
            self._save()

    def record_failure(self, fp: str) -> None:
        with self._lock:
            if fp in self._memory:
                self._memory[fp]["success_count"] = max(
                    0, self._memory[fp]["success_count"] - 1
                )
                self._save()


# Module-level singleton — avoids repeated JSON loads
GLOBAL_REPAIR_MEMORY = RepairMemory()
