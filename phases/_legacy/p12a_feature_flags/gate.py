from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import TaskResult, GateOutcome

async def validate(result: TaskResult, phase_input: Any) -> GateOutcome:
    issues = list(result.issues)
    output = Path(result.output_path)
    if not (output / "feature_flags.py").exists():
        issues.append("feature_flags.py missing")
    if not (output.parent / "migrations/add_feature_flags.sql").exists():
        issues.append("add_feature_flags.sql missing")
    if not (output.parent / "tests/test_feature_flags.py").exists():
        issues.append("test_feature_flags.py missing")
    return GateOutcome(passed=len(issues) == 0, issues=issues, confidence=result.confidence)
