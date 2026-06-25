"""
Repair memory for DCSP.
Persists successful fixes associated with error fingerprints to JSON.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class RepairMemory:
    """Thread-safe persistent memory for repair reuse."""

    def __init__(self, path: str | None = None) -> None:
        if path is None:
            home = Path.home()
            self.path = home / ".dcsp" / "repair_memory.json"
        else:
            self.path = Path(path)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._memory: Dict[str, Dict[str, Any]] = self._load()

    def lookup(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Returns stored entry for a fingerprint, or None."""
        with self._lock:
            return self._memory.get(fingerprint)

    def record_success(self, fingerprint: str, patch_diff: str, 
                       confidence: float, repo_name: str) -> None:
        """Records a successful repair attempt."""
        with self._lock:
            now = datetime.utcnow().isoformat()
            if fingerprint in self._memory:
                entry = self._memory[fingerprint]
                entry["success_count"] += 1
                entry["last_seen"] = now
                entry["patch_diff"] = patch_diff
                entry["confidence"] = confidence
            else:
                self._memory[fingerprint] = {
                    "patch_diff": patch_diff,
                    "confidence": confidence,
                    "repo_name": repo_name,
                    "success_count": 1,
                    "last_seen": now
                }
            self._save()

    def record_failure(self, fingerprint: str) -> None:
        """Decrements success count or removes entry on failure."""
        with self._lock:
            if fingerprint in self._memory:
                self._memory[fingerprint]["success_count"] -= 1
                if self._memory[fingerprint]["success_count"] <= 0:
                    del self._memory[fingerprint]
                self._save()

    def _save(self) -> None:
        """Writes memory to file."""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, indent=2)
        except OSError as e:
            print(f"WARNING: Could not save repair memory: {e}")

    def _load(self) -> Dict[str, Dict[str, Any]]:
        """Loads memory from file."""
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: Could not load repair memory: {e}")
            return {}


# Global singleton
GLOBAL_REPAIR_MEMORY = RepairMemory()
