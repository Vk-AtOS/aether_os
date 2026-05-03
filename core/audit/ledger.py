"""
AetherOS — Decision Ledger (Run/Event Log)
Migrated from aether2/aether/memory/ledger.py.
SQLite-backed run + event log with thread-safe access.
"""
from __future__ import annotations
import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class DecisionLedger:
    """
    SQLite-backed run and event ledger.

    Schema:
      - runs(id, command, status, started_at, finished_at)
      - events(id, run_id, agent, action, detail, timestamp)
      - snapshots(id, run_id, file_path, content, created_at)
    """
    _instance: Optional["DecisionLedger"] = None

    def __init__(self, db_path: Optional[str] = None) -> None:
        from pathlib import Path
        _DB_DIR = Path.home() / ".aether_os"
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        
        if db_path is None:
            from ..config.loader import get_config
            db_path = get_config().get("database.path", str(_DB_DIR / "aether_os.db"))
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    command TEXT,
                    org_id TEXT,
                    status TEXT,
                    started_at REAL,
                    finished_at REAL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT,
                    agent TEXT,
                    action TEXT,
                    detail TEXT,
                    timestamp REAL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    run_id TEXT,
                    file_path TEXT,
                    content TEXT,
                    created_at REAL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
            """)
            conn.commit()
            conn.close()

    def save_run(self, run_id: str, command: str, org_id: Optional[str] = None, status: str = "running") -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO runs (id, command, org_id, status, started_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, command, org_id, status, time.time()),
            )
            conn.commit()
            conn.close()

    def update_run_status(self, run_id: str, status: str) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            finished_at = time.time() if status in ("completed", "failed", "gated") else None
            if finished_at:
                conn.execute(
                    "UPDATE runs SET status=?, finished_at=? WHERE id=?",
                    (status, finished_at, run_id),
                )
            else:
                conn.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
            conn.commit()
            conn.close()

    def log_event(self, run_id: str, agent: str, action: str, detail: Union[str, Dict[str, Any]]) -> None:
        event_id = str(uuid.uuid4())
        if isinstance(detail, dict):
            detail = json.dumps(detail)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO events (id, run_id, agent, action, detail, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, run_id, agent, action, detail, time.time()),
            )
            conn.commit()
            conn.close()

    def get_run_history(self, org_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            if org_id:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE org_id = ? ORDER BY started_at DESC LIMIT ?", (org_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def get_run_detail(self, run_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            if org_id:
                run_row = conn.execute("SELECT * FROM runs WHERE id=? AND org_id=?", (run_id, org_id)).fetchone()
            else:
                run_row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            
            if not run_row:
                conn.close()
                return {}
            events = conn.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY timestamp ASC", (run_id,)
            ).fetchall()
            conn.close()
        result = dict(run_row)
        result["events"] = [dict(e) for e in events]
        return result


def get_ledger() -> DecisionLedger:
    """Return the global singleton DecisionLedger."""
    if DecisionLedger._instance is None:
        DecisionLedger._instance = DecisionLedger()
    return DecisionLedger._instance
