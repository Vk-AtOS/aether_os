from __future__ import annotations
import math
import json
import sqlite3
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

    def get_stage_baseline(self, stage: str) -> Tuple[float, float]:
        """Returns (average, std_dev) for the given stage."""
        # Query raw SQLite for efficiency
        query = "SELECT detail FROM events WHERE agent = 'predictor' AND action = 'stage_timing' ORDER BY timestamp DESC LIMIT 100"
        
        conn = sqlite3.connect(self.ledger.db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

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
