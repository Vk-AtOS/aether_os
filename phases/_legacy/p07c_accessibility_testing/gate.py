"""P07c Gate — zero critical violations."""
from __future__ import annotations
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    critical = result.metadata.get("critical_violations", 0)
    issues = [f"{critical} critical accessibility violations"] if critical > 0 else []
    return GateOutcome(passed=len(issues)==0, issues=issues)
