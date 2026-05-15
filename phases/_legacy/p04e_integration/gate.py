"""P04e Gate."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    if not result.output_path:
        return GateOutcome(passed=False, issues=["No output"])
    client_dir = Path(result.output_path)
    issues = list(result.issues[:3])
    if not client_dir.exists() or not list(client_dir.glob("*")):
        issues.append("api-client directory is empty")
    return GateOutcome(passed=len(issues)==0, issues=issues)
