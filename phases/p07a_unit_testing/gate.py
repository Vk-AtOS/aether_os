"""P07a Gate — validates unit test generation and results."""
from __future__ import annotations
import logging
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


def validate(result: TaskResult) -> GateOutcome:
    meta = result.metadata or {}
    issues: list[str] = []

    # Check pytest result flag
    if not result.success and not meta.get("pytest_passed"):
        return GateOutcome(passed=False, confidence=0.1,
                           issues=["Unit tests failed — fix failing tests before proceeding"])

    # Coverage warning (non-blocking)
    coverage = meta.get("coverage_pct")
    if coverage is not None:
        try:
            cov = float(coverage)
            if cov < 60:
                issues.append(f"Coverage {cov:.0f}% is below 60% — add more test cases")
        except (TypeError, ValueError) as e:
            logger.warning("p07a gate: could not parse coverage_pct %r: %s", coverage, e)

    test_files = meta.get("test_files", 0)
    if test_files == 0 and not meta.get("pytest_passed"):
        issues.append("No test files generated")

    return GateOutcome(passed=True, confidence=0.9 if not issues else 0.7, issues=issues)
