"""
Aether-One Temporal Code Risk Forecasting

Goal:
    Predict which files are most likely to cause future issues, based on:
      - How often they needed fixes in the past
      - How recent those fixes were
      - How severe the previous risk labels were

Data source:
    FixLogDB (existing table), which stores:
      - project_path
      - file_path
      - snapshot_path
      - fix_type
      - message (contains "[risk=LABEL]" prefix)
      - created_at (datetime)

This module is READ-ONLY and safe:
    - It never modifies code or DB.
    - It only reads fix_logs and derives scores.

Public async API:

    async def forecast_project_risk(project_path: str, window_days: int = 90) -> dict:
        Return per-file risk forecast and overall ranking.

    async def forecast_file_risk(project_path: str, file_path: str, window_days: int = 90) -> dict:
        Return detailed risk metrics for a single file.

Scoring model (simple, explainable, offline):

    For each file:
      - frequency_score   → normalized number of fixes in the window
      - recency_score     → exponential decay weighting of recent fixes
      - severity_score    → average mapped value of risk labels

    Combined risk score ∈ [0, 1] approx:
      score = 0.4 * frequency_score + 0.3 * recency_score + 0.3 * severity_score

This is intentionally simple and explainable, and can later be swapped out
for a more advanced offline ML model without changing the API.
"""

from __future__ import annotations

import math
import os
import re
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import make_engine, make_session_maker, Base
from .models import FixLogDB


# Regex to extract "[risk=LABEL]" from FixLogDB.message
RISK_TAG_RE = re.compile(r"\[risk=([A-Z_]+)\]", re.IGNORECASE)


# Map textual risk labels to numeric severity in [0,1]
RISK_SEVERITY = {
    "NONE": 0.0,
    "LOW": 0.3,
    "MEDIUM": 0.6,
    "HIGH": 1.0,
    "UNKNOWN": 0.5,
}


@dataclass
class FileRiskMetrics:
    file_path: str
    fix_count: int
    window_days: int
    last_fix_at: Optional[datetime]
    risk_label_counts: Dict[str, int]
    frequency_score: float
    recency_score: float
    severity_score: float
    risk_score: float  # final combined score


async def _get_session_for_project(project_path: str) -> AsyncSession:
    """
    Create an async DB session for a given project, ensuring tables exist.
    """
    engine = make_engine(project_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = make_session_maker(engine)
    return SessionLocal()


def _extract_risk_label(message: str) -> str:
    """
    Extract risk label from FixLogDB.message.

    Expected pattern: "[risk=LOW] some message"
    If none found, returns "UNKNOWN".
    """
    if not isinstance(message, str):
        return "UNKNOWN"

    m = RISK_TAG_RE.search(message)
    if not m:
        return "UNKNOWN"

    label = m.group(1).upper()
    if label not in RISK_SEVERITY:
        return "UNKNOWN"
    return label


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    """
    Normalize datetime to timezone-aware UTC for consistent comparisons.
    """
    if dt.tzinfo is None:
        # Assume stored as naive local; treat as UTC for simplicity.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_frequency_score(fix_count: int, max_fix_count: int) -> float:
    """
    Normalize fix_count relative to the maximum observed in the window.

    If max_fix_count == 0, returns 0.0.
    """
    if max_fix_count <= 0:
        return 0.0
    return min(1.0, fix_count / float(max_fix_count))


def _compute_recency_score(fix_times: List[datetime], window_days: int) -> float:
    """
    Compute recency score using exponential decay.

    Each fix contributes:
        w_i = exp(-age_days / half_life)

    with half_life = window_days / 3.

    The score is normalized to [0,1] by assuming that "many" recent fixes
    saturate towards 1.0. This is heuristic but explainable.
    """
    if not fix_times:
        return 0.0

    now = _now_utc()
    half_life = max(1.0, window_days / 3.0)

    total_weight = 0.0
    for ts in fix_times:
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
        w = math.exp(-age_days / half_life)
        total_weight += w

    # Normalize: assume that a total_weight >= 3.0 is "very recent/active"
    return min(1.0, total_weight / 3.0)


def _compute_severity_score(label_counts: Dict[str, int]) -> float:
    """
    Average mapped severity based on observed risk labels.
    """
    if not label_counts:
        return 0.0

    total = 0.0
    count = 0
    for label, c in label_counts.items():
        sev = RISK_SEVERITY.get(label, RISK_SEVERITY["UNKNOWN"])
        total += sev * c
        count += c

    if count <= 0:
        return 0.0
    return min(1.0, total / float(count))


def _combine_scores(freq: float, rec: float, sev: float) -> float:
    """
    Combine frequency, recency, and severity into a single risk score.

    Weights are currently:
        freq: 0.4
        rec : 0.3
        sev : 0.3
    """
    return max(0.0, min(1.0, 0.4 * freq + 0.3 * rec + 0.3 * sev))


async def _load_fix_logs(
    session: AsyncSession,
    project_path: str,
    window_days: int,
) -> List[FixLogDB]:
    """
    Load fix logs for a project within the given time window.
    """
    now = _now_utc()
    window_start = now - timedelta(days=window_days)

    stmt = (
        select(FixLogDB)
        .where(FixLogDB.project_path == project_path)
        .where(FixLogDB.created_at >= window_start)  # type: ignore[attr-defined]
        .order_by(FixLogDB.created_at.desc())        # type: ignore[attr-defined]
    )

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def forecast_project_risk(
    project_path: str,
    window_days: int = 90,
) -> Dict[str, Any]:
    """
    Compute temporal risk forecast for all files in a project.

    Returns a dict:

    {
        "project_path": ...,
        "window_days": 90,
        "generated_at": "...",
        "files": [
            {
                "file_path": "...",
                "fix_count": ...,
                "window_days": ...,
                "last_fix_at": "... or None",
                "risk_label_counts": {...},
                "frequency_score": ...,
                "recency_score": ...,
                "severity_score": ...,
                "risk_score": ...
            },
            ...
        ],
        "sorted_files": [
            "file_with_highest_risk.py",
            ...
        ]
    }
    """
    project_abs = os.path.abspath(os.path.expanduser(project_path))

    session = await _get_session_for_project(project_abs)
    async with session:
        logs = await _load_fix_logs(session, project_abs, window_days)

    # Aggregate per file
    per_file_fix_times: Dict[str, List[datetime]] = defaultdict(list)
    per_file_label_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_file_last_fix: Dict[str, datetime] = {}

    for log in logs:
        file_path = log.file_path or ""
        if not file_path:
            continue

        created_at = _to_utc(log.created_at)  # type: ignore[attr-defined]
        label = _extract_risk_label(log.message or "")

        per_file_fix_times[file_path].append(created_at)
        per_file_label_counts[file_path][label] += 1

        prev = per_file_last_fix.get(file_path)
        if prev is None or created_at > prev:
            per_file_last_fix[file_path] = created_at

    # Compute max fix count for normalization
    max_fix_count = 0
    for file_path, times in per_file_fix_times.items():
        if len(times) > max_fix_count:
            max_fix_count = len(times)

    # Build metrics
    metrics: List[FileRiskMetrics] = []
    for file_path, times in per_file_fix_times.items():
        fix_count = len(times)
        freq_score = _compute_frequency_score(fix_count, max_fix_count)
        rec_score = _compute_recency_score(times, window_days)
        sev_score = _compute_severity_score(per_file_label_counts[file_path])
        risk_score = _combine_scores(freq_score, rec_score, sev_score)

        metrics.append(
            FileRiskMetrics(
                file_path=file_path,
                fix_count=fix_count,
                window_days=window_days,
                last_fix_at=per_file_last_fix.get(file_path),
                risk_label_counts=dict(per_file_label_counts[file_path]),
                frequency_score=freq_score,
                recency_score=rec_score,
                severity_score=sev_score,
                risk_score=risk_score,
            )
        )

    # Sort by descending risk_score
    metrics.sort(key=lambda m: m.risk_score, reverse=True)

    # Serialize to dict
    files_out: List[Dict[str, Any]] = []
    for m in metrics:
        row = asdict(m)
        if m.last_fix_at is not None:
            row["last_fix_at"] = m.last_fix_at.isoformat()
        else:
            row["last_fix_at"] = None
        files_out.append(row)

    return {
        "project_path": project_abs,
        "window_days": window_days,
        "generated_at": _now_utc().isoformat(),
        "files": files_out,
        "sorted_files": [m.file_path for m in metrics],
    }


async def forecast_file_risk(
    project_path: str,
    file_path: str,
    window_days: int = 90,
) -> Dict[str, Any]:
    """
    Compute temporal risk forecast for a single file.

    This is a convenience wrapper over forecast_project_risk.
    """
    project_abs = os.path.abspath(os.path.expanduser(project_path))
    file_abs = os.path.abspath(os.path.expanduser(file_path))

    project_result = await forecast_project_risk(project_abs, window_days=window_days)

    for row in project_result.get("files", []):
        if os.path.abspath(row.get("file_path", "")) == file_abs:
            out = dict(row)
            out["project_path"] = project_abs
            out["window_days"] = window_days
            out["generated_at"] = project_result.get("generated_at")
            return out

    # No data for this file in the window.
    return {
        "project_path": project_abs,
        "file_path": file_abs,
        "window_days": window_days,
        "generated_at": project_result.get("generated_at"),
        "fix_count": 0,
        "last_fix_at": None,
        "risk_label_counts": {},
        "frequency_score": 0.0,
        "recency_score": 0.0,
        "severity_score": 0.0,
        "risk_score": 0.0,
    }

