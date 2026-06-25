from __future__ import annotations
import logging
from typing import Any

from src.pipeline import run_repair
from src.models import RepairJob
from src.database import SessionLocal
from src.db.job_repo import save_job
from src.api.state import add_job_to_history

logger = logging.getLogger(__name__)

def process_repair_job(
    job_payload: dict
) -> dict:
    """
    RQ task: process a repair job
    from the queue.
    
    job_payload keys:
      - job_id: str
      - repo_name: str
      - branch: str
      - log_content: str
      - ci_system: str
      - tenant_id: str (optional)
    
    Returns result dict with success status.
    """
    job_id = job_payload.get("job_id", "unknown")
    logger.info(
        f"Processing queued repair: {job_id}")
    
    try:
        result = run_repair(
            repo_name=job_payload["repo_name"],
            branch=job_payload["branch"],
            log_content=job_payload["log_content"],
            ci_system=job_payload.get(
                "ci_system", "github_actions")
        )
        
        session = SessionLocal()
        try:
            job = RepairJob(
                id=job_id,
                tenant_id=job_payload.get(
                    "tenant_id"),
                repo_name=job_payload["repo_name"],
                branch=job_payload["branch"],
                ci_system=job_payload.get(
                    "ci_system", "github_actions"),
                log_content=job_payload[
                    "log_content"][:5000],
                detected_language=result.detected_language,
                success=result.success,
                confidence=result.confidence,
                escalated=result.escalated,
                patch_diff=result.patch_diff,
                explanation=result.explanation,
                fingerprint=result.fingerprint,
                error_type=result.error_type
            )
            save_job(session, job)
            
            # Convert model to dict for add_job_to_history
            job_dict = {
                "id": job.id,
                "tenant_id": job.tenant_id,
                "timestamp": job.timestamp.isoformat() if hasattr(job.timestamp, "isoformat") else str(job.timestamp),
                "repo_name": job.repo_name,
                "branch": job.branch,
                "ci_system": job.ci_system,
                "detected_language": job.detected_language,
                "success": job.success,
                "confidence": job.confidence,
                "escalated": job.escalated,
                "patch_diff": job.patch_diff,
                "explanation": job.explanation,
                "fingerprint": job.fingerprint,
                "approved": None,
                "slm_generated": result.slm_generated,
                "source": result.source,
                "error_type": job.error_type
            }
            add_job_to_history(job_dict)
        finally:
            session.close()
        
        return {
            "success": True,
            "job_id": job_id,
            "repair_success": result.success,
            "confidence": result.confidence
        }
    
    except Exception as e:
        logger.error(
            f"Repair task failed: {e}",
            exc_info=True)
        return {
            "success": False,
            "job_id": job_id,
            "error": str(e)
        }
