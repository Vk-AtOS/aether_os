from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from src.models import Incident, RepairJob
from src.database import get_db

logger = logging.getLogger(__name__)

def get_or_create_incident(
    db: Session,
    fingerprint: str,
    error_type: str,
    language: str,
    repo_name: str
) -> Incident:
    """
    Find existing incident by fingerprint
    or create a new one.
    Updates affected_repos and job_count.
    """
    incident = db.query(Incident).filter(
        Incident.fingerprint == fingerprint,
        Incident.status == "active"
    ).first()

    if incident:
        # Update existing incident
        repos = json.loads(
            incident.affected_repos or "[]")
        if repo_name not in repos:
            repos.append(repo_name)
            incident.affected_repos = \
                json.dumps(repos)
        incident.job_count += 1
        incident.last_seen = datetime.utcnow()
        db.commit()
        db.refresh(incident)
        return incident

    # Create new incident
    incident = Incident(
        fingerprint=fingerprint,
        error_type=error_type,
        language=language,
        affected_repos=json.dumps([repo_name]),
        job_count=1,
        status="active"
    )
    db.add(incident)
    db.commit()
    refresh_incident(db, incident)
    return incident

def refresh_incident(db: Session, incident: Incident):
    db.refresh(incident)

def get_incident_by_id(
    db: Session,
    incident_id: str
) -> Optional[Incident]:
    return db.query(Incident).filter(
        Incident.id == incident_id
    ).first()

def list_incidents(
    db: Session,
    status: Optional[str] = None,
    limit: int = 50
) -> list[Incident]:
    q = db.query(Incident)
    if status:
        q = q.filter(
            Incident.status == status)
    return q.order_by(
        Incident.last_seen.desc()
    ).limit(limit).all()

def resolve_incident(
    db: Session,
    incident_id: str,
    resolution: str
) -> Optional[Incident]:
    incident = get_incident_by_id(
        db, incident_id)
    if not incident:
        return None
    incident.status = "resolved"
    incident.resolution = resolution
    db.commit()
    db.refresh(incident)
    return incident

def escalate_incident(
    db: Session,
    incident_id: str
) -> Optional[Incident]:
    incident = get_incident_by_id(
        db, incident_id)
    if not incident:
        return None
    incident.status = "escalated"
    db.commit()
    db.refresh(incident)
    return incident

def get_incident_stats(
    db: Session
) -> dict:
    """Summary stats for dashboard."""
    total = db.query(Incident).count()
    active = db.query(Incident).filter(
        Incident.status == "active"
    ).count()
    escalated = db.query(Incident).filter(
        Incident.status == "escalated"
    ).count()
    resolved = db.query(Incident).filter(
        Incident.status == "resolved"
    ).count()
    return {
        "total": total,
        "active": active,
        "escalated": escalated,
        "resolved": resolved
    }
