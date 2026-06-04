"""
AetherOS — Unified Audit Logger
Migrated from aether2/aether/audit/logger.py with asyncio.Lock for async safety.
Writes JSONL append-only log + keeps in-memory buffer for fast queries.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Append-only audit logger with JSONL file persistence.

    Thread/async safe: uses asyncio.Lock for async code paths.
    The sync `log_sync` method uses a threading.Lock for use from sync contexts.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self._storage_path = storage_path
        self._entries: List[Dict[str, Any]] = []
        self._lock: Optional[asyncio.Lock] = None  # created lazily to avoid Python 3.9 event-loop requirement at init time

        import threading
        self._sync_lock = threading.Lock()

        if storage_path:
            storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _build_entry(
        self,
        actor: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        session_id: str = "",
    ) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "actor": actor,
            "action": action,
            "details": details or {},
            "session_id": session_id,
        }

    def _write_to_disk(self, entry: Dict[str, Any]) -> None:
        if self._storage_path:
            try:
                with open(self._storage_path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError as exc:
                logger.error("Audit log write failed: %s", exc)

    async def log(
        self,
        actor: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        session_id: str = "",
    ) -> Dict[str, Any]:
        """Async-safe audit log entry."""
        entry = self._build_entry(actor, action, details, session_id)
        async with self._get_lock():
            self._entries.append(entry)
            self._write_to_disk(entry)
        return entry

    def log_sync(
        self,
        actor: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        session_id: str = "",
    ) -> Dict[str, Any]:
        """Sync-safe audit log entry (for use from non-async code)."""
        entry = self._build_entry(actor, action, details, session_id)
        with self._sync_lock:
            self._entries.append(entry)
            self._write_to_disk(entry)
        return entry

    def filter(
        self,
        actor: Optional[str] = None,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = list(self._entries)
        if actor:
            results = [e for e in results if e["actor"] == actor]
        if action:
            results = [e for e in results if e["action"] == action]
        return results

    def all(self) -> List[Dict[str, Any]]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)

    def export(self, output: Path) -> None:
        output.write_text(json.dumps(self._entries, indent=2))


_instance: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Return the global singleton AuditLogger."""
    global _instance
    if _instance is None:
        from ..config.loader import get_config
        log_path_str = get_config().get("audit.log_path", "")
        log_path = Path(log_path_str) if log_path_str else (Path.home() / ".aether_os" / "audit.jsonl")
        _instance = AuditLogger(storage_path=log_path)
    return _instance
