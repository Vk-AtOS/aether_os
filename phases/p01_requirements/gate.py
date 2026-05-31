"""P01 Gate — validates that structured requirements were extracted."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    p = Path(result.output_path or "")
    if not p.exists():
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["Requirements file not produced"])

    try:
        data = json.loads(p.read_text())
    except Exception:
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["Requirements output is not valid JSON"])

    reqs = data.get("functional_requirements", [])
    if not reqs:
        return GateOutcome(
            passed=False, confidence=0.0,
            issues=["functional_requirements is empty — no requirements extracted"],
        )

    issues = []
    if not data.get("acceptance_criteria"):
        issues.append("acceptance_criteria missing — add at least one criterion")

    return GateOutcome(passed=True, confidence=0.9 if not issues else 0.7, issues=issues)
