"""
In-memory state for DCSP API.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from threading import Lock

# Global in-memory job history
# Each entry: {id, timestamp, repo_name, branch, success, confidence, escalated, explanation, approved}
JOB_HISTORY: List[Dict[str, Any]] = []
HISTORY_LOCK = Lock()
MAX_HISTORY = 1000

def add_job_to_history(job_data: Dict[str, Any]) -> None:
    """Add a job to the in-memory history, maintaining MAX_HISTORY limit."""
    with HISTORY_LOCK:
        # Ensure job has a unique ID and approval status
        if "id" not in job_data:
            job_data["id"] = str(uuid.uuid4())
        if "approved" not in job_data:
            job_data["approved"] = None # None = pending, True = approved, False = rejected
        if "approved_pr_url" not in job_data:
            job_data["approved_pr_url"] = None
        if "source" not in job_data:
            job_data["source"] = "slm"
        if "fingerprint" not in job_data:
            job_data["fingerprint"] = ""
            
        JOB_HISTORY.insert(0, job_data)
        if len(JOB_HISTORY) > MAX_HISTORY:
            JOB_HISTORY.pop()

def update_job_approval(job_id: str, approved: bool) -> bool:
    """Update approval status of a job in history and database."""
    updated_in_memory = False
    with HISTORY_LOCK:
        for job in JOB_HISTORY:
            if job["id"] == job_id:
                job["approved"] = approved
                updated_in_memory = True
                break
    
    if updated_in_memory:
        # Try to update database in background (fire and forget)
        try:
            from src.database import SessionLocal
            from src.db.job_repo import update_job_approval as db_update_approval
            
            def _update_db():
                session = SessionLocal()
                try:
                    db_update_approval(session, job_id, approved)
                finally:
                    session.close()
            
            import threading
            threading.Thread(target=_update_db, daemon=True).start()
        except Exception as e:
            print(f"WARNING: Failed to trigger background DB update for approval: {e}")
            
    return updated_in_memory

def update_job_pr_url(job_id: str, pr_url: str) -> bool:
    """Update the approved_pr_url of a job in history and database."""
    updated_in_memory = False
    with HISTORY_LOCK:
        for job in JOB_HISTORY:
            if job["id"] == job_id:
                job["approved_pr_url"] = pr_url
                updated_in_memory = True
                break
    
    if updated_in_memory:
        try:
            from src.database import SessionLocal
            from src.models import RepairJob
            
            def _update_db():
                session = SessionLocal()
                try:
                    job = session.query(RepairJob).filter(RepairJob.id == job_id).first()
                    if job:
                        job.approved_pr_url = pr_url
                        session.commit()
                finally:
                    session.close()
            
            import threading
            threading.Thread(target=_update_db, daemon=True).start()
        except Exception as e:
            print(f"WARNING: Failed to trigger background DB update for PR URL: {e}")
            
    return updated_in_memory
