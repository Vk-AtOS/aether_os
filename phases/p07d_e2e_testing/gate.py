"""P07d Gate — all critical journeys pass."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    if not result.output_path:
        return GateOutcome(passed=False, issues=["No test output"])
    test_count = result.metadata.get("test_files", 0)
    issues = []
    if test_count == 0:
        issues.append("No e2e test files generated")
    issues.extend(result.issues[:2])
    return GateOutcome(passed=len(issues)==0, issues=issues)
