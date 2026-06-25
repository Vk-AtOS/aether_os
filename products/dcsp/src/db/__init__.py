"""
Database operations for DCSP.
"""

from __future__ import annotations

from src.db.job_repo import (
    save_job,
    get_recent_jobs,
    get_job_by_id,
    update_job_approval,
    get_job_stats
)

__all__ = [
    "save_job",
    "get_recent_jobs",
    "get_job_by_id",
    "update_job_approval",
    "get_job_stats"
]
