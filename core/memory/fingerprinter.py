"""
Project fingerprinting for cross-run similarity matching.

Contains:
  - fingerprint()          — stable hash from CI log content (legacy, kept for compatibility)
  - ProjectFingerprinter   — fingerprint/store/search for full project runs
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".aether_os" / "project_fingerprints.db"


def fingerprint(log_content: str) -> str:
    """Stable 16-char hex fingerprint from CI log content (legacy)."""
    keywords = ["error", "exception", "traceback", "failed", "fatal"]
    relevant_lines = [
        line.strip()
        for line in log_content.splitlines()
        if any(kw in line.lower() for kw in keywords)
    ]
    normalized = "\n".join(relevant_lines)
    normalized = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", normalized)
    normalized = re.sub(r"line \d+", "line N", normalized)
    normalized = re.sub(r"(['\"])(?:(?!\1).)*\1", "FILE", normalized)
    normalized = re.sub(r"[\w\./\\-]+\.py:\d+", "FILE", normalized)
    return hashlib.sha256(normalized.lower().encode()).hexdigest()[:16]


class ProjectFingerprinter:
    """
    Fingerprints a project description and persists it for cross-run matching.

    Storage: SQLite at ~/.aether_os/project_fingerprints.db
    Thread-safe; all DB operations are sync (intended to run in executor threads).
    """

    def __init__(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS project_fingerprints (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      TEXT NOT NULL,
                    org_id      TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    domain      TEXT,
                    raw_input   TEXT,
                    phase_outputs TEXT,
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pfp_org_fp
                    ON project_fingerprints (org_id, fingerprint);
            """)

    def fingerprint(self, raw_input: str, domain: str = "general") -> str:
        """Return a stable fingerprint hash for the given project description."""
        text = f"{domain}::{raw_input.lower().strip()}"
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    def store(
        self,
        run_id: str,
        org_id: str,
        fingerprint: str,
        phase_outputs: Optional[Dict[str, Any]] = None,
        domain: str = "general",
        raw_input: str = "",
    ) -> None:
        """Persist a successful run's fingerprint for future matching."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO project_fingerprints
                        (run_id, org_id, fingerprint, domain, raw_input, phase_outputs, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        org_id,
                        fingerprint,
                        domain,
                        raw_input[:500],
                        json.dumps(phase_outputs or {}),
                        time.time(),
                    ),
                )
        except Exception as exc:
            logger.debug("ProjectFingerprinter.store failed: %s", exc)

    def search(
        self,
        fingerprint: str,
        org_id: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Return up to top_k past runs for the org ordered by recency.

        Exact fingerprint hits come first, then all other recent runs as
        fallback context. Similarity score is 1.0 for exact, 0.5 for fallback.
        """
        results: List[Dict[str, Any]] = []
        try:
            with self._connect() as conn:
                # Exact matches first
                rows = conn.execute(
                    """
                    SELECT run_id, domain, raw_input, created_at
                    FROM project_fingerprints
                    WHERE org_id = ? AND fingerprint = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (org_id, fingerprint, top_k),
                ).fetchall()
                for r in rows:
                    results.append({
                        "run_id": r["run_id"],
                        "domain": r["domain"] or "general",
                        "project_name": r["raw_input"][:60] if r["raw_input"] else "",
                        "similarity": 1.0,
                        "winning_approach": "",
                    })

                # Fill remaining slots with recent org runs
                if len(results) < top_k:
                    fallback = conn.execute(
                        """
                        SELECT run_id, domain, raw_input
                        FROM project_fingerprints
                        WHERE org_id = ? AND fingerprint != ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (org_id, fingerprint, top_k - len(results)),
                    ).fetchall()
                    seen = {r["run_id"] for r in results}
                    for r in fallback:
                        if r["run_id"] not in seen:
                            results.append({
                                "run_id": r["run_id"],
                                "domain": r["domain"] or "general",
                                "project_name": r["raw_input"][:60] if r["raw_input"] else "",
                                "similarity": 0.5,
                                "winning_approach": "",
                            })
        except Exception as exc:
            logger.debug("ProjectFingerprinter.search failed: %s", exc)
        return results[:top_k]
