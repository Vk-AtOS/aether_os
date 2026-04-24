"""P07a Gate — tests pass + coverage >= 70%."""
from __future__ import annotations
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    issues = list(result.issues)
    if not result.metadata.get("pytest_passed"):
        issues.append("pytest did not pass")
    coverage = result.metadata.get("coverage_pct", 0)
    if coverage < 70 and result.metadata.get("test_files", 0) > 0:
        issues.append(f"Coverage {coverage}% < 70%")
    return GateOutcome(passed=len(issues)==0, issues=issues,
                       confidence=min(coverage/100, 0.95) if coverage else 0.5)
