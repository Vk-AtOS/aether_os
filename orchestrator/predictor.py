from __future__ import annotations
import math
import json
import os
from typing import Dict, Any, Tuple, List
import logging
logger = logging.getLogger(__name__)
from aether_os.core.audit.ledger import get_ledger


class PipelinePredictor:
    _instance = None

    def __init__(self):
        self.ledger = get_ledger()

    def record_stage_timing(self, run_id: str, stage: str, duration: float):
        self.ledger.log_event(run_id, "predictor", "stage_timing", {"stage": stage, "duration": duration})

    def _fetch_timing_rows(self) -> list:
        """Synchronous helper — runs in a thread via asyncio.to_thread or directly in sync contexts."""
        from sqlalchemy import create_engine, text as _sa_text
        query = "SELECT detail FROM events WHERE agent = 'predictor' AND action = 'stage_timing' ORDER BY timestamp DESC LIMIT 100"
        _db_url = os.environ.get("DATABASE_URL", "sqlite:///aether_os.db")
        # Strip async driver prefix so the sync engine works on both SQLite and PostgreSQL
        _sync_url = _db_url.replace("postgresql+asyncpg://", "postgresql://").replace("sqlite+aiosqlite://", "sqlite://")
        engine = create_engine(_sync_url)
        with engine.connect() as conn:
            return conn.execute(_sa_text(query)).fetchall()

    def get_stage_baseline(self, stage: str) -> Tuple[float, float]:
        """Returns (average, std_dev) for the given stage."""
        rows = []
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # Inside an async context: push blocking DB call to a thread pool
                import concurrent.futures
                fut: concurrent.futures.Future = concurrent.futures.Future()
                async def _run():
                    try:
                        fut.set_result(await asyncio.to_thread(self._fetch_timing_rows))
                    except Exception as _e:
                        logger.debug("predictor: _fetch_timing_rows thread error: %s", _e)
                        fut.set_exception(_e)
                asyncio.run_coroutine_threadsafe(_run(), loop)
                rows = fut.result(timeout=5)
            except RuntimeError:
                # No running event loop — call synchronously
                rows = self._fetch_timing_rows()
        except Exception as exc:
            logger.warning("[predictor] DB query failed: %s", exc)
            return (0.0, 0.0)

        durations = []
        for row in rows:
            try:
                data = json.loads(row[0])
                if data.get("stage") == stage:
                    durations.append(data.get("duration", 0))
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
        
        if len(durations) < 3:
            return (0.0, 0.0)
        
        avg = sum(durations) / len(durations)
        variance = sum((x - avg) ** 2 for x in durations) / len(durations)
        std_dev = math.sqrt(variance)
        
        return (avg, std_dev)

    def predict_stall_risk(self, stage: str, current_duration: float) -> Dict[str, Any]:
        avg, std_dev = self.get_stage_baseline(stage)
        
        if avg == 0:
             return {
                "risk_score": 0,
                "prediction": "UNKNOWN",
                "estimated_stall_in_seconds": 0,
                "recommendation": "Not enough data"
            }

        if std_dev == 0:
            std_dev = 1.0 # Prevent div by zero

        z_score = (current_duration - avg) / std_dev
        
        # Risk mapping
        if z_score < 1.0:
            prediction = "LOW"
            score = 10
        elif z_score < 1.5:
            prediction = "MEDIUM"
            score = 40
        elif z_score < 2.5:
            prediction = "HIGH"
            score = 80
        else:
            prediction = "CRITICAL"
            score = 95
            
        return {
            "risk_score": score,
            "prediction": prediction,
            "z_score": round(z_score, 2),
            "avg_duration": round(avg, 2),
            "recommendation": "Monitor closely" if score > 50 else "Normal operation"
        }


def get_predictor() -> PipelinePredictor:
    if PipelinePredictor._instance is None:
        PipelinePredictor._instance = PipelinePredictor()
    return PipelinePredictor._instance
