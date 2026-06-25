from __future__ import annotations
import logging
from typing import Optional
from datetime import datetime, timedelta
from src.database import SessionLocal
from src.models import RepairJob

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [60, 300, 900]
# seconds: 1min, 5min, 15min

def should_retry(
    job_id: str,
    attempt: int
) -> bool:
    """Determine if a failed job should retry."""
    return attempt < MAX_RETRIES

def get_retry_delay(attempt: int) -> int:
    """Get delay in seconds before next retry."""
    if attempt < len(RETRY_DELAYS):
        return RETRY_DELAYS[attempt]
    return RETRY_DELAYS[-1]

def record_retry_attempt(
    job_id: str,
    attempt: int,
    error: str
) -> None:
    """Log a retry attempt."""
    logger.warning(
        f"Job {job_id} retry attempt "
        f"{attempt}/{MAX_RETRIES}: {error}")

def send_to_dead_letter_queue(
    job_payload: dict,
    error: str,
    attempts: int
) -> dict:
    """
    Send a permanently failed job to the DLQ.
    Stores it in the DB with escalated=True
    and records the failure reason.
    Returns the DLQ entry dict.
    """
    job_id = job_payload.get(
        "job_id", "unknown")
    logger.error(
        f"Job {job_id} sent to DLQ after "
        f"{attempts} attempts: {error}")
    
    session = SessionLocal()
    try:
        existing = session.query(RepairJob)\
            .filter(RepairJob.id == job_id)\
            .first()
        
        if existing:
            existing.escalated = True
            existing.explanation = (
                f"[DLQ] Failed after "
                f"{attempts} attempts: {error}"
            )
            session.commit()
            logger.info(
                f"Updated job {job_id} "
                f"as DLQ escalation")
        else:
            logger.warning(
                f"DLQ: job {job_id} "
                f"not found in DB")
    except Exception as e:
        logger.error(
            f"DLQ DB update failed: {e}")
    finally:
        session.close()
    
    return {
        "job_id": job_id,
        "status": "dead_letter",
        "attempts": attempts,
        "error": error,
        "timestamp": datetime.utcnow()
            .isoformat()
    }

def process_with_retry(
    job_payload: dict,
    processor_fn=None
) -> dict:
    """
    Process a job with automatic retry logic.
    Falls back to synchronous processing if
    Redis is unavailable.
    
    Returns result dict with status and
    attempt count.
    """
    from src.queue.repair_task import \
        process_repair_job
    
    if processor_fn is None:
        processor_fn = process_repair_job
    
    job_id = job_payload.get(
        "job_id", "unknown")
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(
                f"Processing job {job_id}, "
                f"attempt {attempt + 1}/"
                f"{MAX_RETRIES}")
            result = processor_fn(job_payload)
            
            if result.get("success"):
                return {
                    "status": "success",
                    "attempts": attempt + 1,
                    "result": result
                }
            else:
                last_error = result.get(
                    "error", "Unknown failure")
                record_retry_attempt(
                    job_id, attempt + 1,
                    last_error)
        
        except Exception as e:
            last_error = str(e)
            record_retry_attempt(
                job_id, attempt + 1,
                last_error)
            logger.warning(
                f"Attempt {attempt + 1} "
                f"exception: {e}")
    
    # All retries exhausted
    dlq_entry = send_to_dead_letter_queue(
        job_payload, last_error or "Unknown",
        MAX_RETRIES)
    
    return {
        "status": "dead_letter",
        "attempts": MAX_RETRIES,
        "dlq_entry": dlq_entry
    }
