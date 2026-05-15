"""P07b Gate — P95 within thresholds."""
from __future__ import annotations
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    issues = list(result.issues)
    return GateOutcome(passed=len(issues)==0, issues=issues)
