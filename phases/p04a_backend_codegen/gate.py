"""P04a Gate — validates backend code was generated."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    p = Path(result.output_path or "")
    if not p.exists():
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["Backend output directory not found"])

    py_files = list(p.rglob("*.py")) if p.is_dir() else ([p] if p.suffix == ".py" else [])
    if not py_files:
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["No Python files found in backend output"])

    return GateOutcome(passed=True, confidence=0.85, issues=[])
