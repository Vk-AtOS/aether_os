"""
Repository for RepairJob database operations.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, and_
from src.models import RepairJob, StageTiming

def save_job(session: Session, job_data: Dict[str, Any]) -> RepairJob:
    """Creates and saves a RepairJob from the dict."""
    # Handle violations serialization if it's a list
    violations = job_data.get("violations")
    if isinstance(violations, list):
        violations = json.dumps(violations)
    
    # Handle timestamp if it's a string
    timestamp = job_data.get("timestamp")
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            timestamp = datetime.utcnow()
    elif timestamp is None:
        timestamp = datetime.utcnow()

    job = RepairJob(
        id=job_data.get("id"),
        timestamp=timestamp,
        repo_name=job_data.get("repo_name"),
        branch=job_data.get("branch"),
        commit_sha=job_data.get("commit_sha"),
        ci_system=job_data.get("ci_system"),
        detected_language=job_data.get("detected_language"),
        success=job_data.get("success", False),
        confidence=job_data.get("confidence", 0.0),
        escalated=job_data.get("escalated", False),
        explanation=job_data.get("explanation", ""),
        patch_diff=job_data.get("patch_diff"),
        slm_generated=job_data.get("slm_generated", False),
        approved=job_data.get("approved"),
        violations=violations,
        approved_pr_url=job_data.get("approved_pr_url"),
        sandbox_result=job_data.get("sandbox_result"),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job_by_id(session: Session, job_id: str) -> Optional[RepairJob]:
    """Retrieve a specific repair job by ID."""
    return session.query(RepairJob).filter(RepairJob.id == job_id).first()


def get_recent_jobs(
    session: Session,
    limit: int = 50,
    tenant_id: Optional[str] = None,
) -> List[RepairJob]:
    """Returns most recent jobs ordered by timestamp desc, optionally filtered by tenant."""
    q = session.query(RepairJob).order_by(desc(RepairJob.timestamp))
    if tenant_id:
        q = q.filter(RepairJob.tenant_id == tenant_id)
    return q.limit(limit).all()


def update_job_approval(session: Session, job_id: str, approved: bool) -> bool:
    """Updates approval status of a job. Returns True if found and updated."""
    job = get_job_by_id(session, job_id)
    if job:
        job.approved = approved
        session.commit()
        return True
    return False


def get_job_stats(
    session: Session,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns basic job statistics, optionally filtered by tenant."""
    base = session.query(RepairJob)
    if tenant_id:
        base = base.filter(RepairJob.tenant_id == tenant_id)

    total = base.with_entities(func.count(RepairJob.id)).scalar() or 0
    if total == 0:
        return {
            "total": 0,
            "successful": 0,
            "escalated": 0,
            "avg_confidence": 0.0,
        }

    successful = base.filter(RepairJob.success == True).with_entities(func.count(RepairJob.id)).scalar() or 0  # noqa: E712
    escalated = base.filter(RepairJob.escalated == True).with_entities(func.count(RepairJob.id)).scalar() or 0  # noqa: E712
    avg_confidence = base.with_entities(func.avg(RepairJob.confidence)).scalar() or 0.0

    return {
        "total": total,
        "successful": successful,
        "escalated": escalated,
        "avg_confidence": float(avg_confidence),
    }


def record_stage_timing(
    session: Session, 
    job_id: str, 
    stage_name: str, 
    duration_seconds: int, 
    outcome: str,
    tenant_id: Optional[str] = None
) -> StageTiming:
    """Record a stage timing."""
    timing = StageTiming(
        job_id=job_id,
        stage_name=stage_name,
        duration_seconds=duration_seconds,
        outcome=outcome,
        tenant_id=tenant_id
    )
    session.add(timing)
    session.commit()
    session.refresh(timing)
    return timing


def get_stage_timings(
    session: Session, 
    stage_name: str, 
    tenant_id: Optional[str] = None
) -> List[StageTiming]:
    """Get timings for a specific stage."""
    query = session.query(StageTiming).filter(StageTiming.stage_name == stage_name)
    if tenant_id:
        query = query.filter(StageTiming.tenant_id == tenant_id)
    return query.all()


def get_all_stage_timings(session: Session) -> List[StageTiming]:
    """Get all stage timings."""
    return session.query(StageTiming).all()


def get_job_stage_timings(session: Session, job_id: str) -> List[StageTiming]:
    """Get all stage timings for a specific job."""
    return session.query(StageTiming).filter(StageTiming.job_id == job_id).all()
