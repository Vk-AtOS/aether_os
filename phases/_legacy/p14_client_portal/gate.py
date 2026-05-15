from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import TaskResult, GateOutcome

async def validate(result: TaskResult, phase_input: Any) -> GateOutcome:
    issues = list(result.issues)
    output = Path(result.output_path)
    if not (output / "client_portal.html").exists():
        issues.append("client_portal.html missing")
    if (output / "client_portal.html").stat().st_size < 100:
        issues.append("client_portal.html too small")
    if not (output.parent / "migrations/add_portal.sql").exists():
        issues.append("add_portal.sql missing")
    return GateOutcome(passed=len(issues) == 0, issues=issues, confidence=result.confidence)
