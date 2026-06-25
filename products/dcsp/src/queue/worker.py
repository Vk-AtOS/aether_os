from __future__ import annotations
import os
import logging
from typing import Optional
try:
    import redis
    from rq import Queue, Worker
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv(
    "REDIS_URL", "redis://localhost:6379/0")

def get_redis_connection():
    """Get Redis connection. Returns None
    if Redis unavailable."""
    if not REDIS_AVAILABLE:
        return None
    try:
        conn = redis.from_url(
            REDIS_URL, socket_timeout=2)
        conn.ping()
        return conn
    except Exception as e:
        logger.warning(
            f"Redis unavailable: {e}")
        return None

def get_repair_queue() -> Optional[object]:
    """Get the repair job queue.
    Returns None if Redis unavailable."""
    conn = get_redis_connection()
    if not conn:
        return None
    try:
        return Queue(
            "repairs", connection=conn)
    except Exception as e:
        logger.warning(
            f"Queue unavailable: {e}")
        return None

def enqueue_repair(
    job_payload: dict
) -> Optional[str]:
    """
    Enqueue a repair job.
    Returns RQ job ID if queued,
    None if Redis unavailable
    (caller should process synchronously).
    """
    queue = get_repair_queue()
    if not queue:
        return None
    try:
        from src.queue.repair_task import \
            process_repair_job
        rq_job = queue.enqueue(
            process_repair_job,
            job_payload,
            job_timeout=300,
            result_ttl=86400
        )
        logger.info(
            f"Enqueued repair job: {rq_job.id}")
        return rq_job.id
    except Exception as e:
        logger.warning(
            f"Failed to enqueue: {e}")
        return None

def get_queue_stats() -> dict:
    """Get queue statistics.
    Returns zeros if Redis unavailable."""
    queue = get_repair_queue()
    if not queue:
        return {
            "queued": 0,
            "started": 0,
            "finished": 0,
            "failed": 0,
            "redis_available": False
        }
    try:
        conn = get_redis_connection()
        started_registry = \
            queue.started_job_registry
        finished_registry = \
            queue.finished_job_registry
        failed_registry = \
            queue.failed_job_registry
        return {
            "queued": len(queue),
            "started": len(started_registry),
            "finished": len(finished_registry),
            "failed": len(failed_registry),
            "redis_available": True
        }
    except Exception as e:
        logger.warning(
            f"Stats unavailable: {e}")
        return {
            "queued": 0,
            "started": 0,
            "finished": 0,
            "failed": 0,
            "redis_available": False
        }
