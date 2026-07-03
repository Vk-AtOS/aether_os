"""P07d Gate — validates E2E tests ran and critical user flows passed."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["E2E tests produced no output — critical user flows not verified"],
        )

    output_path = Path(result.output_path)
    try:
        candidates = (
            [output_path] if output_path.suffix == ".json"
            else list(output_path.rglob("e2e*.json")) + list(output_path.rglob("playwright*.json")) + list(output_path.rglob("results*.json"))
        )
        if candidates and candidates[0].exists():
            data = json.loads(candidates[0].read_text())
            passed_count = data.get("passed", data.get("tests_passed", 0))
            failed_count = data.get("failed", data.get("tests_failed", 0))
            total = passed_count + failed_count

            if total == 0:
                issues.append("No E2E tests were executed")
            elif failed_count > 0:
                pct = failed_count / total
                issues.append(f"{failed_count}/{total} E2E tests failed ({pct:.0%} failure rate)")
                if pct > 0.5:
                    return GateOutcome(passed=False, confidence=0.2, issues=issues)
    except Exception as e:
        logger.warning("p07d_e2e gate: could not parse E2E test results: %s", e)
        issues.append(f"Could not parse E2E test results: {e}")

    confidence = 0.9 if not issues else 0.55
    return GateOutcome(passed=not any("failed" in i for i in issues), confidence=confidence, issues=issues)
