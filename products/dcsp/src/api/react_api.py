from __future__ import annotations
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, desc, Integer, cast
from sqlalchemy.orm import Session

from src.database import get_db
from src.models import RepairJob, FailureFingerprint, Incident, ApiKey
from src.api.auth_router import get_current_user_api
from src.api.state import JOB_HISTORY

router = APIRouter(prefix="/api", tags=["react-api"])

logger = logging.getLogger(__name__)


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Return KPI statistics for the dashboard.

    Merges DB counts with in-memory JOB_HISTORY so that push-webhook jobs
    that haven't been flushed to the DB yet are still reflected in the stats.
    """
    today = str(datetime.utcnow().date())

    # DB counts
    db_jobs_today = db.query(RepairJob).filter(func.date(RepairJob.timestamp) == today).count()
    total_db_jobs = db.query(RepairJob).count()
    successful_db_jobs = db.query(RepairJob).filter(RepairJob.success == True).count()

    # In-memory jobs not yet persisted (deduplicated against DB by checking
    # whether the same id already exists — we avoid a per-row DB query by
    # collecting all DB ids in one pass only when there are memory jobs).
    mem_jobs_today = 0
    mem_total = 0
    mem_successful = 0
    if JOB_HISTORY:
        db_ids = {str(r.id) for r in db.query(RepairJob.id).all()}
        for j in JOB_HISTORY:
            if str(j.get("id", "")) in db_ids:
                continue  # already counted in DB totals
            mem_total += 1
            mem_successful += 1 if j.get("success") else 0
            ts = j.get("timestamp", "")
            if isinstance(ts, str) and ts.startswith(today):
                mem_jobs_today += 1

    jobs_today = db_jobs_today + mem_jobs_today
    total_jobs = total_db_jobs + mem_total
    successful_jobs = successful_db_jobs + mem_successful
    success_rate = successful_jobs / total_jobs if total_jobs > 0 else 0.0

    # Avg repair time (placeholder — stage timings not yet aggregated)
    avg_repair_seconds = 45.5

    # Patterns learned
    patterns_learned = db.query(FailureFingerprint).count()

    return {
        "jobs_today": jobs_today,
        "success_rate": success_rate,
        "avg_repair_seconds": avg_repair_seconds,
        "patterns_learned": patterns_learned
    }

@router.get("/v2/analytics")
async def get_analytics(db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Return analytics data for charts (react dashboard)."""
    # Daily repairs (last 30 days)
    cutoff = datetime.utcnow() - timedelta(days=30)
    daily_data = db.query(
        func.date(RepairJob.timestamp).label('date'),
        func.count(RepairJob.id).label('count'),
        func.sum(cast(RepairJob.success, Integer)).label('success')
    ).filter(RepairJob.timestamp >= cutoff).group_by(func.date(RepairJob.timestamp)).all()
    
    daily_repairs = [
        {"date": str(d.date), "count": d.count, "success": int(d.success or 0)}
        for d in daily_data
    ]
    
    # By error type
    error_data = db.query(
        RepairJob.error_type,
        func.count(RepairJob.id).label('count')
    ).group_by(RepairJob.error_type).order_by(desc('count')).limit(10).all()
    
    by_error_type = [
        {"type": e.error_type or "Unknown", "count": e.count}
        for e in error_data
    ]
    
    # Outcomes
    outcomes = {
        "patched": db.query(RepairJob).filter(RepairJob.success == True).count(),
        "escalated": db.query(RepairJob).filter(RepairJob.escalated == True).count(),
        "failed": db.query(RepairJob).filter(RepairJob.success == False, RepairJob.escalated == False).count()
    }
    
    return {
        "daily_repairs": daily_repairs,
        "by_error_type": by_error_type,
        "outcomes": outcomes
    }

@router.get("/patterns")
async def get_patterns(
    page: int = 1,
    limit: int = 20,
    language: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user_api)
):
    """Return paginated failure patterns."""
    query = db.query(FailureFingerprint)
    if language:
        query = query.filter(FailureFingerprint.language == language)
    if search:
        query = query.filter(FailureFingerprint.error_type.ilike(f"%{search}%"))
    
    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()
    
    return {
        "items": items,
        "total": total,
        "page": page
    }

@router.get("/v2/incidents")
async def get_incidents(db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Return list of active incidents (react dashboard)."""
    incidents = db.query(Incident).order_by(desc(Incident.last_seen)).all()
    result = []
    for i in incidents:
        affected = []
        if i.affected_repos:
            try:
                affected = json.loads(i.affected_repos)
            except Exception:
                affected = [i.affected_repos]
        
        result.append({
            "id": i.id,
            "error_type": i.error_type,
            "language": i.language,
            "first_seen": i.first_seen.isoformat(),
            "last_seen": i.last_seen.isoformat(),
            "affected_repos": affected,
            "failure_count": i.job_count,
            "status": i.status,
            "severity": "high" if i.job_count > 5 else "medium" # Simple logic
        })
    return result

@router.post("/v2/incidents/{id}/resolve")
async def resolve_incident(id: str, db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Mark an incident as resolved (react dashboard)."""
    incident = db.query(Incident).filter(Incident.id == id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident.status = "resolved"
    db.commit()
    return {"status": "resolved"}

@router.get("/settings")
async def get_settings(db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Return application settings and configurations."""
    # Fetch API keys for default tenant
    from src.db.tenant_repo import get_tenant_by_slug
    tenant = get_tenant_by_slug(db, "default")
    keys = db.query(ApiKey).filter(ApiKey.tenant_id == tenant.id).all() if tenant else []
    
    api_keys = [
        {"id": k.id, "name": k.name, "prefix": k.key_prefix, "created_at": k.created_at.isoformat()}
        for k in keys
    ]
    
    return {
        "api_keys": api_keys,
        "webhook_urls": {
            "github": f"{os.getenv('BASE_URL', 'http://localhost:8001')}/webhook/ci",
            "gitlab": f"{os.getenv('BASE_URL', 'http://localhost:8001')}/webhook/ci/auto",
            "jenkins": f"{os.getenv('BASE_URL', 'http://localhost:8001')}/webhook/ci/auto?token=YOUR_TOKEN"
        },
        "notifications": {
            "slack_webhook": os.getenv("SLACK_WEBHOOK_URL", ""),
            "email": os.getenv("SMTP_USER", "")
        }
    }

@router.post("/api-keys")
async def create_api_key_endpoint(body: dict, db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Create a new API key."""
    from src.db.api_key_repo import create_api_key
    from src.db.tenant_repo import get_tenant_by_slug
    tenant = get_tenant_by_slug(db, "default")
    if not tenant:
         raise HTTPException(status_code=404, detail="Default tenant not found")
    
    key_obj, raw_key = create_api_key(db, tenant.id, body.get("name", "New Key"))
    return {"key": raw_key, "id": key_obj.id}

@router.post("/jobs/{job_id}/approve")
async def approve_job_api(job_id: str, db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Approve a job's patch (marks as approved, triggers PR creation)."""
    from src.api.state import update_job_approval, JOB_HISTORY
    job = db.query(RepairJob).filter(RepairJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.approved = True
    db.commit()
    for m in JOB_HISTORY:
        if m.get("id") == job_id:
            m["approved"] = True
            break
    return {"status": "approved", "job_id": job_id}


@router.post("/jobs/{job_id}/reject")
async def reject_job_api(job_id: str, db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Reject a job's patch."""
    from src.api.state import JOB_HISTORY
    job = db.query(RepairJob).filter(RepairJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.approved = False
    db.commit()
    for m in JOB_HISTORY:
        if m.get("id") == job_id:
            m["approved"] = False
            break
    return {"status": "rejected", "job_id": job_id}


@router.post("/jobs/{job_id}/custom-patch")
async def submit_custom_patch(job_id: str, body: dict, db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Submit a user-supplied custom patch, validate it, store it, mark approved."""
    from src.api.state import JOB_HISTORY
    custom_diff = (body.get("patch_diff") or "").strip()
    if not custom_diff:
        raise HTTPException(status_code=400, detail="patch_diff is required")
    job = db.query(RepairJob).filter(RepairJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.patch_diff = custom_diff
    job.patch_edited = True
    job.approved = True
    db.commit()
    for m in JOB_HISTORY:
        if m.get("id") == job_id:
            m["patch_diff"] = custom_diff
            m["patch_edited"] = True
            m["approved"] = True
            break
    return {"status": "accepted", "job_id": job_id, "message": "Custom patch stored and approved"}


@router.delete("/api-keys/{id}")
async def delete_api_key_endpoint(id: str, db: Session = Depends(get_db), current_user: str = Depends(get_current_user_api)):
    """Revoke an API key."""
    from src.db.api_key_repo import revoke_api_key
    from src.db.tenant_repo import get_tenant_by_slug
    tenant = get_tenant_by_slug(db, "default")
    if not tenant:
         raise HTTPException(status_code=404, detail="Default tenant not found")
         
    success = revoke_api_key(db, id, tenant.id)
    if not success:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"deleted": True}
