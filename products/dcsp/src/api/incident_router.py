from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.database import get_db
from src.db.incident_repo import (
    list_incidents,
    get_incident_by_id,
    resolve_incident,
    escalate_incident,
    get_incident_stats
)
from src.api.auth import verify_session_token
import json

router = APIRouter(prefix="/api/incidents",
                   tags=["incidents"])

def _require_auth(request: Request):
    token = request.cookies.get("session_token")
    if not verify_session_token(token):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

@router.get("")
async def get_incidents(
    request: Request,
    status: str = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    _require_auth(request)
    incidents = list_incidents(
        db, status=status, limit=limit)
    return {
        "incidents": [
            _serialize(i) for i in incidents
        ],
        "total": len(incidents)
    }

@router.get("/stats")
async def incidents_stats(
    request: Request,
    db: Session = Depends(get_db)
):
    _require_auth(request)
    return get_incident_stats(db)

@router.get("/{incident_id}")
async def get_incident(
    incident_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    _require_auth(request)
    incident = get_incident_by_id(
        db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )
    return _serialize(incident)

@router.post("/{incident_id}/resolve")
async def resolve(
    incident_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    _require_auth(request)
    body = await request.json()
    resolution = body.get(
        "resolution", "Manually resolved")
    incident = resolve_incident(
        db, incident_id, resolution)
    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )
    return _serialize(incident)

@router.post("/{incident_id}/escalate")
async def escalate(
    incident_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    _require_auth(request)
    incident = escalate_incident(
        db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )
    return _serialize(incident)

def _serialize(incident) -> dict:
    return {
        "id": incident.id,
        "fingerprint": incident.fingerprint,
        "error_type": incident.error_type,
        "language": incident.language,
        "first_seen": str(
            incident.first_seen or ""),
        "last_seen": str(
            incident.last_seen or ""),
        "affected_repos": json.loads(
            incident.affected_repos or "[]"),
        "job_count": incident.job_count,
        "status": incident.status,
        "resolution": incident.resolution
    }
