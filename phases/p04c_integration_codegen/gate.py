"""P04c Gate — validates integration clients were generated for discovered services."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.6,
            issues=["Integration codegen produced no output — external service clients not generated"],
        )

    output_path = Path(result.output_path)
    py_files = list(output_path.rglob("*.py")) if output_path.is_dir() else [output_path]
    client_files = [f for f in py_files if any(kw in f.name.lower() for kw in ("client", "connector", "integration", "adapter"))]

    if not client_files and py_files:
        issues.append("No client/connector files found — integration clients may not be properly named")

    confidence = 0.85 if not issues else 0.65
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
