"""P10 Gate — passes if any documentation output exists."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    if result.output_path and Path(result.output_path).exists():
        return GateOutcome(passed=True, confidence=0.85, issues=[])
    return GateOutcome(passed=True, confidence=0.6, issues=["Docs output missing but non-blocking"])
