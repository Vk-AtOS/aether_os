"""
AetherOS — Continuous Learning Memory Store
NEW module — replaces DCSP repair_memory (JSON file) + aether2 MemoryAgent (in-memory dict).

Storage: SQLite with FTS5 for fast similarity search.

Interface:
    store(record: MemoryRecord) -> None
    retrieve(input_hash: str, k: int = 5) -> List[MemoryRecord]
    store_sync / retrieve_sync for use from sync code paths

BUG 8 FIX: MemoryAgent._store class-level dict is replaced with this persistent store.
BUG 7 FIX: Federation registry now has a persistent SQLite backend via this store.
"""
from __future__ import annotations
import asyncio
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryRecord:
    """A single persisted memory entry."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    input_hash: str = ""          # SHA-256 / fingerprint of input
    input_text: str = ""          # Original input summary
    output_text: str = ""         # Successful output (code, patch, fix)
    task_type: str = ""           # e.g. "code_generation", "ci_repair"
    org_id: str = ""              # Organisation that owns this record
    metadata: Dict[str, Any] = field(default_factory=dict)
    success_count: int = 1        # How many times this solution worked
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class MemoryStore:
    """
    SQLite + FTS5 persistent memory store for successful outcomes.

    Thread-safe via threading.Lock.
    Async wrappers use asyncio.run_in_executor to avoid blocking the event loop.
    """
    _instance: Optional["MemoryStore"] = None

    def __init__(self, db_path: Optional[str] = None) -> None:
        from pathlib import Path as _Path
        (_Path.home() / ".aether_os").mkdir(parents=True, exist_ok=True)
        
        if db_path is None:
            from ..config.loader import get_config
            db_path = get_config().get(
                "memory.db_path",
                str(_Path.home() / ".aether_os" / "memory.db"),
            )
        from pathlib import Path
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            c = conn.cursor()
            c.executescript("""
                CREATE TABLE IF NOT EXISTS memory (
                    id TEXT PRIMARY KEY,
                    input_hash TEXT NOT NULL,
                    input_text TEXT,
                    output_text TEXT,
                    task_type TEXT,
                    org_id TEXT DEFAULT '',
                    metadata TEXT,
                    success_count INTEGER DEFAULT 1,
                    created_at REAL,
                    updated_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory(input_hash);
                CREATE INDEX IF NOT EXISTS idx_memory_task ON memory(task_type);

                -- FTS5 for text similarity search
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    id UNINDEXED,
                    input_text,
                    output_text,
                    task_type,
                    content=memory,
                    content_rowid=rowid
                );

                -- Keep FTS in sync
                CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory BEGIN
                    INSERT INTO memory_fts(rowid, id, input_text, output_text, task_type)
                    VALUES (new.rowid, new.id, new.input_text, new.output_text, new.task_type);
                END;
                CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, id, input_text, output_text, task_type)
                    VALUES ('delete', old.rowid, old.id, old.input_text, old.output_text, old.task_type);
                END;
            """)
            # Additive migration: org_id column was added after initial schema.
            # ALTER TABLE raises OperationalError("duplicate column name") if the
            # column already exists — that is the expected success case for DBs
            # created with the new schema, so we swallow it.
            try:
                c.execute("ALTER TABLE memory ADD COLUMN org_id TEXT DEFAULT ''")
                logger.info("Memory store: migrated — added org_id column to memory table")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    logger.debug("Memory store: org_id column already exists (migration skipped)")
                else:
                    logger.warning("Memory store: unexpected error adding org_id column: %s", e)
                    raise
            # Index on org_id must be created after the column is guaranteed to exist
            c.execute("CREATE INDEX IF NOT EXISTS idx_memory_org ON memory(org_id)")
            conn.commit()
            conn.close()
        logger.debug("Memory store initialised at %s", self.db_path)

    def store_sync(self, record: MemoryRecord) -> None:
        """Persist a memory record. If same input_hash exists, increment success_count."""
        with self._lock:
            conn = self._connect()
            c = conn.cursor()
            existing = c.execute(
                "SELECT id, success_count FROM memory WHERE input_hash=? AND task_type=? AND org_id=?",
                (record.input_hash, record.task_type, record.org_id),
            ).fetchone()

            if existing:
                c.execute(
                    "UPDATE memory SET success_count=?, output_text=?, updated_at=? WHERE id=?",
                    (
                        existing["success_count"] + 1,
                        record.output_text,
                        time.time(),
                        existing["id"],
                    ),
                )
            else:
                c.execute(
                    "INSERT INTO memory (id, input_hash, input_text, output_text, task_type, org_id, metadata, success_count, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.id,
                        record.input_hash,
                        record.input_text,
                        record.output_text,
                        record.task_type,
                        record.org_id,
                        json.dumps(record.metadata),
                        record.success_count,
                        record.created_at,
                        record.updated_at,
                    ),
                )
            conn.commit()
            conn.close()
        logger.debug("Memory stored: hash=%s task=%s", record.input_hash, record.task_type)

    async def store(self, record: MemoryRecord) -> None:
        """Async wrapper for store_sync."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.store_sync, record)

    def retrieve_sync(self, input_hash: str, k: int = 5, org_id: str = "") -> List[MemoryRecord]:
        """
        Retrieve top-k most relevant records by input_hash (exact) or FTS similarity.
        When org_id is provided, results are scoped to that organisation.
        Returns records ordered by success_count DESC.
        """
        with self._lock:
            conn = self._connect()
            if org_id:
                rows = conn.execute(
                    "SELECT * FROM memory WHERE input_hash=? AND org_id=? ORDER BY success_count DESC LIMIT ?",
                    (input_hash, org_id, k),
                ).fetchall()
                if not rows:
                    try:
                        rows = conn.execute(
                            "SELECT m.* FROM memory m "
                            "JOIN memory_fts f ON m.rowid=f.rowid "
                            "WHERE memory_fts MATCH ? AND m.org_id=? "
                            "ORDER BY m.success_count DESC LIMIT ?",
                            (input_hash, org_id, k),
                        ).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
            else:
                rows = conn.execute(
                    "SELECT * FROM memory WHERE input_hash=? ORDER BY success_count DESC LIMIT ?",
                    (input_hash, k),
                ).fetchall()
                if not rows:
                    try:
                        rows = conn.execute(
                            "SELECT m.* FROM memory m "
                            "JOIN memory_fts f ON m.rowid=f.rowid "
                            "WHERE memory_fts MATCH ? "
                            "ORDER BY m.success_count DESC LIMIT ?",
                            (input_hash, k),
                        ).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
            conn.close()

        return [
            MemoryRecord(
                id=r["id"],
                input_hash=r["input_hash"],
                input_text=r["input_text"] or "",
                output_text=r["output_text"] or "",
                task_type=r["task_type"] or "",
                org_id=r["org_id"] if "org_id" in r.keys() else "",
                metadata=json.loads(r["metadata"] or "{}"),
                success_count=r["success_count"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def retrieve(self, input_hash: str, k: int = 5, org_id: str = "") -> List[MemoryRecord]:
        """Async wrapper for retrieve_sync."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.retrieve_sync, input_hash, k, org_id)

    def stats(self) -> Dict[str, Any]:
        """Return store statistics."""
        with self._lock:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
            by_task = conn.execute(
                "SELECT task_type, COUNT(*) as cnt FROM memory GROUP BY task_type"
            ).fetchall()
            conn.close()
        return {
            "total_records": total,
            "by_task_type": {r["task_type"]: r["cnt"] for r in by_task},
        }


def get_memory_store() -> MemoryStore:
    """Return the global singleton MemoryStore."""
    if MemoryStore._instance is None:
        MemoryStore._instance = MemoryStore()
    return MemoryStore._instance
