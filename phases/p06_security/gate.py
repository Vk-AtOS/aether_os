"""P06 Gate — zero HIGH findings."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    high_remaining = result.metadata.get("high_remaining", 0)
    issues = []
    if high_remaining > 0:
        issues.append(f"{high_remaining} HIGH severity findings remain")
    if not result.output_path or not Path(result.output_path).exists():
        issues.append("security_report.json not found")
    return GateOutcome(passed=len(issues)==0, issues=issues)
