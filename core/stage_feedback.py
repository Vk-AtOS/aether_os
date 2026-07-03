"""Per-stage learning feedback — records what each stage produced and what had to be fixed."""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FEEDBACK_LOG = Path(__file__).parent / "knowledge_graph" / "stage_feedback.jsonl"


def record_stage_output(
    stage_id: str,
    run_id: str,
    output_files: list[str],
    quality_scores: dict[str, float],
) -> None:
    """Record what a stage produced and its quality scores."""
    _append({
        "event": "stage_output",
        "stage_id": stage_id,
        "run_id": run_id,
        "output_files": output_files,
        "quality_scores": quality_scores,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


def record_stage_fix(
    stage_id: str,
    run_id: str,
    fix_description: str,
    bug_class: str,
) -> None:
    """Record a fix applied during or after a stage."""
    _append({
        "event": "stage_fix",
        "stage_id": stage_id,
        "run_id": run_id,
        "fix": fix_description,
        "bug_class": bug_class,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


def get_stage_failure_rate(stage_id: str, last_n: int = 50) -> float:
    """Return fraction of last N runs that needed fixes in this stage."""
    records = _load_recent(stage_id, last_n)
    if not records:
        return 0.0
    outputs = [r for r in records if r["event"] == "stage_output"]
    fixes = [r for r in records if r["event"] == "stage_fix"]
    if not outputs:
        return 0.0
    runs_with_fixes = len({r["run_id"] for r in fixes})
    return round(runs_with_fixes / len(outputs), 3)


def get_top_issues(stage_id: str, last_n: int = 50) -> list[dict[str, Any]]:
    """Return most common bug classes for this stage."""
    records = _load_recent(stage_id, last_n)
    fixes = [r for r in records if r["event"] == "stage_fix"]
    counts: Counter[str] = Counter(r.get("bug_class", "unknown") for r in fixes)
    return [{"bug_class": k, "count": v} for k, v in counts.most_common(10)]


def _append(record: dict) -> None:
    try:
        _FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_FEEDBACK_LOG, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        logger.warning("stage_feedback: write failed: %s", e)


def _load_recent(stage_id: str, last_n: int) -> list[dict]:
    try:
        if not _FEEDBACK_LOG.exists():
            return []
        lines = _FEEDBACK_LOG.read_text().strip().split("\n")
        records = []
        for line in lines:
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("stage_id") == stage_id:
                    records.append(r)
            except Exception as e:
                logger.warning("stage_feedback: malformed line skipped: %s", e)
        return records[-(last_n * 2):]  # approximate: 2x entries per run
    except Exception as e:
        logger.warning("stage_feedback: read failed: %s", e)
        return []
