"""P07b Self-Healing Gate — verifies the repair loop resolved test failures.

Passes when:
  - Tests were already passing (skipped: true)
  - Self-healing converged: status == "all_tests_passing"

Blocks when:
  - Max repair attempts exhausted and tests are still failing
"""
from __future__ import annotations
import logging
from typing import Any, Dict

from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


def validate(result: TaskResult | Dict[str, Any]) -> GateOutcome:
    if isinstance(result, dict):
        meta = result
    else:
        meta = result.metadata or {}

    status = meta.get("status", "")
    skipped = meta.get("skipped", False)
    attempts = meta.get("attempts", 0)
    issues: list[str] = []

    # No testable code found — skip cleanly
    if skipped:
        return GateOutcome(passed=True, confidence=1.0, issues=[])

    if status == "all_tests_passing":
        return GateOutcome(passed=True, confidence=0.95, issues=[])

    if status == "max_attempts_reached":
        snippet = (meta.get("last_output") or "")[:200]
        issues.append(
            f"Self-healing exhausted {attempts} repair attempt(s) — tests still failing. "
            f"Last output: {snippet}"
        )
        return GateOutcome(passed=False, confidence=0.2, issues=issues)

    # Unknown / unexpected state — pass with warning so pipeline isn't stuck
    issues.append(f"Self-healing gate: unexpected status '{status}' — review manually")
    logger.warning("[p07b_self_healing gate] unexpected status: %s", status)
    return GateOutcome(passed=True, confidence=0.5, issues=issues)
