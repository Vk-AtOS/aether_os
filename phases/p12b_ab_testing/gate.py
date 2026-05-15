from __future__ import annotations
from pathlib import Path
from typing import Any
from aether_os.phases.base import TaskResult, GateOutcome

async def validate(result: TaskResult, phase_input: Any) -> GateOutcome:
    issues = list(result.issues)
    output = Path(result.output_path)
    if not (output / "ab_testing.py").exists():
        issues.append("ab_testing.py missing")
    if not (output.parent / "migrations/add_ab_testing.sql").exists():
        issues.append("add_ab_testing.sql missing")
    if not (output.parent / "tests/test_ab_testing.py").exists():
        issues.append("test_ab_testing.py missing")
    return GateOutcome(passed=len(issues) == 0, issues=issues, confidence=result.confidence)
