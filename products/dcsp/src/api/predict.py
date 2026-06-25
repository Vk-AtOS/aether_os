"""
API routes for the Predictive Failure Engine.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from src.intelligence.predictor import PIPELINE_PREDICTOR

router = APIRouter(prefix="/predict", tags=["predictions"])

class StageTimingRequest(BaseModel):
    job_id: str
    stage_name: str
    duration_seconds: int
    outcome: str
    tenant_id: Optional[str] = None

@router.get("/stage/{stage_name}")
async def predict_stage_risk(
    stage_name: str, 
    current_duration: int = Query(..., alias="current_duration"),
    tenant_id: Optional[str] = None
):
    """Returns prediction for a specific stage."""
    return PIPELINE_PREDICTOR.predict_failure_risk(stage_name, current_duration, tenant_id)

@router.get("/pipeline/{job_id}")
async def predict_pipeline_outcome(job_id: str):
    """Returns full pipeline outcome prediction."""
    return PIPELINE_PREDICTOR.predict_pipeline_outcome(job_id)

@router.get("/baselines")
async def get_all_baselines():
    """Returns all stage baselines."""
    from src.db.job_repo import get_all_stage_timings
    from src.database import SessionLocal
    from collections import defaultdict
    import math

    session = SessionLocal()
    try:
        timings = get_all_stage_timings(session)
        stage_groups = defaultdict(list)
        for t in timings:
            stage_groups[t.stage_name].append(t)
            
        baselines = {}
        for stage_name, t_list in stage_groups.items():
            durations = [t.duration_seconds for t in t_list]
            count = len(durations)
            avg = sum(durations) / count
            variance = sum((x - avg) ** 2 for x in durations) / count
            std_dev = math.sqrt(variance)
            failures = sum(1 for t in t_list if t.outcome == "failure")
            
            baselines[stage_name] = {
                "avg_seconds": int(avg),
                "std_dev": round(std_dev, 2),
                "sample_count": count,
                "failure_rate": round(failures / count, 2)
            }
        return baselines
    finally:
        session.close()

@router.post("/record")
async def record_timing(timing: StageTimingRequest):
    """Records a completed stage timing for baseline learning."""
    PIPELINE_PREDICTOR.record_stage_timing(
        timing.job_id, 
        timing.stage_name, 
        timing.duration_seconds, 
        timing.outcome, 
        timing.tenant_id
    )
    return {"status": "recorded"}
