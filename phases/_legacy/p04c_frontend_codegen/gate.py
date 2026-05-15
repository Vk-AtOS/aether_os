"""P04c Gate."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    if not result.output_path:
        return GateOutcome(passed=False, issues=["No output path"])
    frontend_dir = Path(result.output_path)
    issues = list(result.issues[:3])
    if not frontend_dir.exists():
        issues.append("frontend directory not created")
    else:
        files = [f for f in frontend_dir.rglob("*") if f.is_file()]
        if len(files) < 2:
            issues.append(f"Only {len(files)} files in frontend dir")
    return GateOutcome(passed=len(issues)==0, issues=issues)
