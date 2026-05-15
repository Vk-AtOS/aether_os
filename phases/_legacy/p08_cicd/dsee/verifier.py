"""
Stability verification for DSEE Phase 4.

Verifies stability conditions based on test results and impact analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dsee.test_runner import TieredTestRunResult
    from src.dsee.impact import ImpactResult


@dataclass
class VerificationResult:
    """Result of the stability verification."""

    approved: bool
    failures: list[str] = field(default_factory=list)


def verify_stability(
    test_result: TieredTestRunResult,
    impact_result: ImpactResult
) -> VerificationResult:
    """
    Verify all four stability conditions.

    Conditions:
    1. All tests passed.
    2. Runtime error eliminated (ImpactResult.safe is True).
    3. No warnings introduced ("PytestWarning" or "DeprecationWarning").
    4. Performance threshold stable (dependency_ripple_count < 10).

    Args:
        test_result: Result from the tiered test runner.
        impact_result: Result from the static impact simulation.

    Returns:
        VerificationResult indicating approval and any failures.
    """
    failures = []

    # 1. All tests passed
    if not test_result.passed:
        failures.append("Test suite failed: One or more tests did not pass.")

    # 2. Runtime error eliminated
    if not impact_result.safe:
        failures.append(f"Risk level too high: {impact_result.risk_level}. Reasons: {', '.join(impact_result.reasons)}")

    # 3. No warnings introduced
    warning_keywords = ["PytestWarning", "DeprecationWarning"]
    found_warnings = [kw for kw in warning_keywords if kw in test_result.output]
    if found_warnings:
        failures.append(f"Warnings introduced: {', '.join(found_warnings)}")

    # 4. Performance threshold stable
    if impact_result.dependency_ripple_count >= 10:
        failures.append(
            f"Performance threshold exceeded: {impact_result.dependency_ripple_count} "
            "downstream functions affected (limit is 10)."
        )

    return VerificationResult(
        approved=len(failures) == 0,
        failures=failures
    )
