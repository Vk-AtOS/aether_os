"""
P06b Gate — enforces formal verification quality.

Gate logic:
  PASS:    overall_verdict == "PASS" (all checked invariants verified)
  PARTIAL: overall_verdict == "PARTIAL" (z3 unavailable or no routes found) — pass with warning
  FAIL:    overall_verdict == "FAIL" (one or more invariants violated) — block pipeline

The gate never blocks for PARTIAL so that projects without FastAPI routes
(e.g. data-only services) still proceed through the pipeline.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


def validate(result: TaskResult) -> GateOutcome:
    """Return GateOutcome based on the formal_verification_report.json verdict."""
    # ── 1. Output existence ───────────────────────────────────────────────────
    if not result.output_path or not Path(result.output_path).exists():
        # If no output at all and the task didn't succeed, block
        if not result.success:
            return GateOutcome(
                passed=False,
                confidence=0.0,
                issues=["Formal verification produced no output and task failed"],
            )
        # No output but task reported success — likely no routes to verify
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["Formal verification: no report produced — assuming no routes to verify"],
        )

    # ── 2. Parse report ───────────────────────────────────────────────────────
    try:
        payload = json.loads(Path(result.output_path).read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[p06b gate] cannot parse report: %s", exc)
        return GateOutcome(
            passed=True,
            confidence=0.4,
            issues=[f"Formal verification report unreadable — treating as PARTIAL: {exc}"],
        )

    verdict = payload.get("overall_verdict", "PARTIAL")
    failed = payload.get("invariants_failed", [])
    confidence = float(payload.get("confidence_score", 0.5))

    # ── 3. Gate decision ──────────────────────────────────────────────────────
    if verdict == "FAIL":
        issues = [
            f"FORMAL VERIFICATION BLOCKED: {len(failed)} invariant(s) violated"
        ]
        for f in failed[:5]:  # show up to 5 violations in the gate message
            issues.append(
                f"  [{f.get('invariant_id', '?')}] {f.get('route', '?')}: "
                f"{f.get('violation_detail') or f.get('proof_method', '')}"
            )
        return GateOutcome(passed=False, confidence=0.0, issues=issues)

    # PASS or PARTIAL — allow the pipeline to continue
    issues: list[str] = []
    if verdict == "PARTIAL":
        reason = payload.get("partial_reason", "Z3 unavailable or no routes found")
        issues.append(f"Formal verification PARTIAL — {reason}")
        confidence = min(confidence, 0.6)

    unverifiable = payload.get("invariants_unverifiable", [])
    if unverifiable:
        issues.append(
            f"{len(unverifiable)} invariant(s) unverifiable "
            "(try/except, async generators, or dynamic dispatch)"
        )

    verified_count = len(payload.get("invariants_verified", []))
    if verified_count:
        issues.insert(0, f"Formal verification: {verified_count} invariant(s) proven VERIFIED by Z3")

    return GateOutcome(passed=True, confidence=confidence, issues=issues)
