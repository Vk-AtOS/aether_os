from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import TaskResult, GateOutcome

async def validate(result: TaskResult, phase_input: Any) -> GateOutcome:
    issues = list(result.issues)
    output = Path(result.output_path)
    if not (output / "analytics_service.py").exists():
        issues.append("analytics_service.py missing")
    if not (output / "analytics_events.py").exists():
        issues.append("analytics_events.py missing")
    if not (output.parent / "migrations/add_analytics_events.sql").exists():
        issues.append("add_analytics_events.sql missing")
    return GateOutcome(passed=len(issues) == 0, issues=issues, confidence=result.confidence)
