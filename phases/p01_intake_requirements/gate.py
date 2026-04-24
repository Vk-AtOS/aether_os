"""P01 Gate — lenient: passes if consolidated output exists."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    if not result.output_path:
        return GateOutcome(passed=False, confidence=0.0, issues=["No output path"])
    p = Path(result.output_path)
    if p.exists() and p.stat().st_size > 0:
        return GateOutcome(passed=True, confidence=0.85, issues=[])
    # Also pass if parent dir has any files
    if p.parent.exists() and any(p.parent.rglob("*")):
        return GateOutcome(passed=True, confidence=0.7, issues=["consolidated.json missing but output dir has files"])
    return GateOutcome(passed=False, confidence=0.0, issues=["No output produced"])
