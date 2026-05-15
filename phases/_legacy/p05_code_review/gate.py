"""P05 Gate — zero CRITICAL issues."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    critical = result.metadata.get("critical", 0)
    issues = []
    if critical > 0:
        issues.append(f"{critical} CRITICAL issues in review_report.md")
    if not result.output_path or not Path(result.output_path).exists():
        issues.append("review_report.md not found")
    return GateOutcome(passed=len(issues)==0, issues=issues,
                       confidence=result.metadata.get("quality_score",7)/10)
