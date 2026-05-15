"""Gate for p10_deployment."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    issues = list(result.issues)
    if not result.success:
        issues = issues or ["Task did not succeed"]
    if result.output_path and not Path(result.output_path).exists():
        issues.append("Output path does not exist")
    return GateOutcome(passed=len(issues)==0, issues=issues,
                       confidence=result.confidence if not issues else 0.3)
