from __future__ import annotations
from pathlib import Path
from typing import Any
from aether_os.phases.base import TaskResult, GateOutcome

async def validate(result: TaskResult, phase_input: Any) -> GateOutcome:
    issues = list(result.issues)
    output = Path(result.output_path)
    if not (output / "sentry_setup.py").exists():
        issues.append("sentry_setup.py missing")
    if not (output / "error_middleware.py").exists():
        issues.append("error_middleware.py missing")
    if not (output.parent / "tests/test_error_tracking.py").exists():
        issues.append("test_error_tracking.py missing")
    return GateOutcome(passed=len(issues) == 0, issues=issues, confidence=result.confidence)
