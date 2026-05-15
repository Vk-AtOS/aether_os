from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import TaskResult, GateOutcome

async def validate(result: TaskResult, phase_input: Any) -> GateOutcome:
    issues = list(result.issues)
    output = Path(result.output_path)
    if not (output / "alertmanager.yml").exists():
        issues.append("alertmanager.yml missing")
    if len(list((output / "alert_runbooks").glob("*.md"))) < 3:
        issues.append("less than 3 runbooks found")
    return GateOutcome(passed=len(issues) == 0, issues=issues, confidence=result.confidence)
