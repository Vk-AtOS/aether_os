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
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    org_id TEXT,
                    user_id TEXT,
                    action TEXT,
                    resource_type TEXT,
                    resource_id TEXT,
                    metadata TEXT,
                    ip_address TEXT,
                    created_at REAL
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

    def log_audit_event(self, org_id: str, user_id: str, action: str, 
                        resource_type: str, resource_id: str, metadata: Dict[str, Any], 
                        ip_address: str) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO audit_log (id, org_id, user_id, action, resource_type, resource_id, metadata, ip_address, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), org_id, user_id, action, resource_type, resource_id, 
                 json.dumps(metadata), ip_address, time.time()),
            )
            conn.commit()
            conn.close()

    def get_audit_logs(self, org_id: str, page: int = 1, limit: int = 50, 
                       action: Optional[str] = None, from_ts: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM audit_log WHERE org_id = ?"
            params = [org_id]
            if action:
                query += " AND action = ?"
                params.append(action)
            if from_ts:
                query += " AND created_at >= ?"
                params.append(from_ts)
            
            total = conn.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.append(limit)
            params.append((page - 1) * limit)
            
            rows = conn.execute(query, params).fetchall()
            conn.close()
            
        return {
            "logs": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if limit > 0 else 1
        }

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
