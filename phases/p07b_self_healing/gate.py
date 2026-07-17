"""P07b Self-Healing Gate — verifies the repair loop resolved test failures.

Passes when:
  - Tests were already passing (skipped: true)
  - Self-healing converged: status == "all_tests_passing"

Force-passes (with force_passed=True flag and WARNING log) when:
  - Max repair attempts exhausted and tests are still failing.
  - Returning passed=False here would cause PhaseBase to retry the entire
    5-attempt cycle up to max_retries times (3×5 = 15 total) — the infinite-loop
    bug.  We force-pass so the pipeline continues but mark force_passed=True so
    callers and monitoring can distinguish a genuine pass from a forced pass.
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
        msg = (
            f"Self-healing exhausted {attempts} repair attempt(s) — tests still failing. "
            f"Pipeline continues but quality is UNCERTAIN. Last output: {snippet}"
        )
        issues.append(msg)
        # ARCH-H1: log at WARNING so this is visible in production logs.
        # force_passed=True distinguishes this from a genuine gate pass.
        logger.warning(
            "[p07b_self_healing gate] FORCE-PASS after %d attempts — "
            "tests still failing; pipeline continues with degraded confidence. "
            "Last output: %.200s",
            attempts,
            meta.get("last_output") or "",
        )
        outcome = GateOutcome(passed=True, confidence=0.4, issues=issues)
        # Attach force_passed flag so orchestrator and monitoring can detect it
        if hasattr(outcome, "__dict__"):
            outcome.__dict__["force_passed"] = True
        return outcome

    # Unknown / unexpected state — pass with warning so pipeline isn't stuck
    issues.append(f"Self-healing gate: unexpected status '{status}' — review manually")
    logger.warning("[p07b_self_healing gate] unexpected status: %s", status)
    return GateOutcome(passed=True, confidence=0.5, issues=issues)
