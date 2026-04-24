"""AetherOS — Per-project usage and billing tracker."""
from __future__ import annotations
import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from pathlib import Path as _Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

(_Path.home() / ".aether_os").mkdir(parents=True, exist_ok=True)

_DB_PATH = _Path.home() / ".aether_os" / "billing.db"

# Anthropic pricing (USD per 1M tokens, as of 2025)
_TOKEN_PRICES: Dict[str, Dict[str, float]] = {
    "claude-sonnet-4-6":    {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5":     {"input": 0.25,  "output": 1.25},
    "claude-opus-4-6":      {"input": 15.00, "output": 75.00},
    "default":              {"input": 3.00,  "output": 15.00},
}


@dataclass
class CostSummary:
    project_id: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    phase_breakdown: Dict[str, float]


class UsageTracker:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    ts REAL NOT NULL DEFAULT (unixepoch('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS phase_completions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    duration_s REAL NOT NULL,
                    ts REAL NOT NULL DEFAULT (unixepoch('now'))
                )
            """)
            conn.commit()

    @staticmethod
    def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        prices = _TOKEN_PRICES.get(model, _TOKEN_PRICES["default"])
        return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

    def record_llm_call(self, project_id: str, phase: str, model: str,
                        input_tokens: int, output_tokens: int,
                        cost_usd: Optional[float] = None) -> None:
        if cost_usd is None:
            cost_usd = self._calc_cost(model, input_tokens, output_tokens)
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO llm_calls(project_id,phase,model,input_tokens,"
                "output_tokens,cost_usd) VALUES(?,?,?,?,?,?)",
                (project_id, phase, model, input_tokens, output_tokens, cost_usd),
            )
            conn.commit()

    def record_phase_completion(self, project_id: str, phase: str,
                                duration_s: float) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO phase_completions(project_id,phase,duration_s) VALUES(?,?,?)",
                (project_id, phase, duration_s),
            )
            conn.commit()

    def get_project_cost(self, project_id: str) -> CostSummary:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
                " COALESCE(SUM(cost_usd),0) FROM llm_calls WHERE project_id=?",
                (project_id,),
            ).fetchone()
            phase_rows = conn.execute(
                "SELECT phase, COALESCE(SUM(cost_usd),0) FROM llm_calls "
                "WHERE project_id=? GROUP BY phase",
                (project_id,),
            ).fetchall()
        return CostSummary(
            project_id=project_id,
            total_input_tokens=row[0],
            total_output_tokens=row[1],
            total_cost_usd=round(row[2], 6),
            phase_breakdown={r[0]: round(r[1], 6) for r in phase_rows},
        )

    def get_phase_cost(self, project_id: str, phase: str) -> float:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls "
                "WHERE project_id=? AND phase=?",
                (project_id, phase),
            ).fetchone()
        return round(row[0], 6)


_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
