"""P09 Gate — always passes (observability is non-blocking)."""
from __future__ import annotations
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    return GateOutcome(passed=True, confidence=0.8, issues=[])
