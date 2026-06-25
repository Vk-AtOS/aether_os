"""
Repository for audit logging.
"""

from __future__ import annotations
from typing import Optional, List
from sqlalchemy.orm import Session
from src.models import AuditLog
import uuid
from datetime import datetime

def save_audit_log(
    session: Session,
    action: str,
    actor: str,
    job_id: Optional[str] = None,
    repo_name: Optional[str] = None,
    details: Optional[str] = None,
    ip_address: Optional[str] = None
) -> AuditLog:
    """Create and save a new audit log entry."""
    audit_log = AuditLog(
        id=str(uuid.uuid4()),
        timestamp=datetime.utcnow(),
        action=action,
        actor=actor,
        job_id=job_id,
        repo_name=repo_name,
        details=details,
        ip_address=ip_address
    )
    session.add(audit_log)
    session.commit()
    session.refresh(audit_log)
    return audit_log

def get_audit_logs(
    session: Session,
    limit: int = 100,
    offset: int = 0,
    action_filter: Optional[str] = None
) -> List[AuditLog]:
    """Retrieve audit logs with optional filtering."""
    query = session.query(AuditLog)
    
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
        
    return query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
