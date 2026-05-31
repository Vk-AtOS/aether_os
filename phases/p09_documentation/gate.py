"""P09 Gate — validates documentation delivery (non-blocking)."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

_MIN_README_BYTES = 500


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(passed=True, confidence=0.4,
                           issues=["Documentation not generated — README.md required for handoff"])

    output_path = Path(result.output_path)
    readme = None
    if output_path.is_dir():
        for candidate in ("docs/README.md", "README.md"):
            r = output_path / candidate
            if r.exists():
                readme = r
                break
    elif output_path.suffix == ".md":
        readme = output_path

    if readme and readme.stat().st_size < _MIN_README_BYTES:
        issues.append(f"README.md is too short ({readme.stat().st_size} bytes)")

    return GateOutcome(passed=True, confidence=0.9 if not issues else 0.7, issues=issues)
