"""
Background repair tasks using RQ (Redis Queue).

The application uses RQ throughout (worker.py, repair_task.py).
Celery was removed — only RQ is needed.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def repair_job(log_content: str, repo_name: str, branch: str) -> dict:
    """
    RQ-compatible task to run the repair pipeline in the background.
    Called by the RQ worker via enqueue_repair() in worker.py.
    """
    from src.pipeline import run_repair

    historical_records: list = []
    ast_index: dict = {}
    call_graph = None

    try:
        result = run_repair(
            log_content=log_content,
            root_dir=".",
            historical_records=historical_records,
            ast_index=ast_index,
            call_graph=call_graph,
        )
        return {
            "success": result.success,
            "confidence": result.confidence,
            "patch_diff": result.patch_diff,
            "explanation": result.explanation,
            "escalated": result.escalated,
            "violations": result.violations,
        }
    except Exception as e:
        logger.error("repair_job task failed for repo %s: %s", repo_name, e)
        return {
            "success": False,
            "confidence": 0.0,
            "patch_diff": None,
            "explanation": f"Task error: {e}",
            "escalated": True,
            "violations": [],
        }
