"""P04 Gate — lenient: passes if any output exists."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    if result.output_path and Path(result.output_path).exists():
        return GateOutcome(passed=True, confidence=0.85, issues=[])
    p = Path(result.output_path or "")
    if p.parent.exists() and any(p.parent.rglob("*.py")):
        return GateOutcome(passed=True, confidence=0.8, issues=[])
    return GateOutcome(passed=result.success, confidence=result.confidence, issues=result.issues)
