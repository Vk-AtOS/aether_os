"""
Stage 1: INTAKE — shared utilities.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


def merge_stage_outputs(results: List[TaskResult]) -> Dict[str, Any]:
    """Merge a list of TaskResult metadata dicts into one flat dict.

    Later values win when two results share a key.  None values are skipped
    so a skipped sub-phase does not erase a value written by an earlier one.

    Args:
        results: TaskResult objects whose .metadata dicts will be merged.

    Returns:
        A single flat dict containing all non-None values from every result.
    """
    merged: Dict[str, Any] = {}
    for result in results:
        if not isinstance(result, TaskResult):
            continue
        for key, value in (result.metadata or {}).items():
            if value is not None:
                merged[key] = value
    return merged
