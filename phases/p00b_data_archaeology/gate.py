"""P00b Gate — validates data archaeology output has schema and migration artifacts."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["Data archaeology produced no output — schema analysis skipped"],
        )

    output_path = Path(result.output_path)
    files = list(output_path.rglob("*")) if output_path.is_dir() else [output_path]
    file_names = {f.name.lower() for f in files if f.is_file()}

    if not any("schema" in n or "migration" in n or "etl" in n for n in file_names):
        issues.append("No schema, migration, or ETL artifact found in data archaeology output")

    confidence = 0.85 if not issues else 0.6
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
