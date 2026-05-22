"""P07 Gate — enforces test quality.

Blocks if:
  - No test code was generated at all
  - Tests ran and the pass-rate is below the minimum threshold

Passes with warnings for partial failures or low coverage.
"""
from __future__ import annotations
import logging
from typing import Any, Dict

from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

_MIN_PASS_RATE = 0.70   # 70 % tests must pass


def validate(result: TaskResult | Dict[str, Any]) -> GateOutcome:
    """Accept both the old dict form and the new TaskResult form."""
    # ── Normalise input ───────────────────────────────────────────────────────
    if isinstance(result, dict):
        test_code    = result.get("test_code", "")
        passed_flag  = result.get("passed", True)
        total        = int(result.get("total_tests", 0))
        passed_count = int(result.get("passed_tests", total))
        meta         = result
    else:
        meta         = result.metadata or {}
        passed_flag  = result.success
        total        = int(meta.get("total_tests", 0))
        passed_count = int(meta.get("passed_tests", total))
        # Consolidated format: sub-phase results are nested under "phases" key
        if "phases" in meta:
            # Extract test_code from any sub-phase that produced it
            test_code = ""
            for sp in meta["phases"].values():
                tc = sp.get("test_code", "") if isinstance(sp, dict) else ""
                if tc:
                    test_code = tc
                    break
        else:
            test_code = meta.get("test_code", "")

    issues: list[str] = []

    # ── Check the new test_quality_flag written by the consolidated task_agent ─
    quality_flag = meta.get("test_quality_flag", "")
    if quality_flag == "fail":
        issues.append(
            f"Test quality: FAIL — only {meta.get('passed_tests', 0)}/{meta.get('total_tests', 0)} tests passed"
        )
        return GateOutcome(passed=False, confidence=0.3, issues=issues)
    elif quality_flag == "warn":
        issues.append("Test quality: WARN — partial test coverage or inconclusive results")
    elif quality_flag == "pass":
        # Already confirmed passing via quality flag — skip legacy checks below
        coverage = meta.get("coverage_pct")
        if coverage is not None:
            try:
                cov = float(coverage)
                if cov < 60:
                    issues.append(f"Coverage {cov:.0f}% is low — aim for ≥ 80%")
            except (TypeError, ValueError):
                pass
        confidence = 0.95 if not issues else 0.75
        return GateOutcome(passed=True, confidence=confidence, issues=issues)

    # ── Legacy path: no quality_flag set (old-format result) ─────────────────

    # ── Hard block: no tests generated ───────────────────────────────────────
    if not test_code and not meta.get("test_file"):
        # In consolidated mode (phases key present), task_agent marks testing
        # as non-blocking (success=True) — trust it rather than hard-blocking.
        if "phases" in meta or passed_flag:
            issues.append("No test code generated (likely rate-limited) — tests omitted, review manually")
            return GateOutcome(passed=True, confidence=0.5, issues=issues)
        issues.append("No test code was generated — pipeline blocked until tests exist")
        return GateOutcome(passed=False, confidence=0.0, issues=issues)

    # ── Evaluate pass rate ────────────────────────────────────────────────────
    if total > 0:
        pass_rate = passed_count / total
        if pass_rate < _MIN_PASS_RATE:
            issues.append(
                f"Test pass-rate {pass_rate:.0%} is below the required {_MIN_PASS_RATE:.0%} "
                f"({passed_count}/{total} passed)"
            )
            return GateOutcome(passed=False, confidence=pass_rate, issues=issues)
        if pass_rate < 1.0:
            failed = total - passed_count
            issues.append(f"{failed} test(s) failed (pass-rate {pass_rate:.0%}) — review recommended")
    elif not passed_flag:
        issues.append("Test runner reported failure — inspect test output")
        return GateOutcome(passed=False, confidence=0.1, issues=issues)

    # ── Coverage warning ──────────────────────────────────────────────────────
    coverage = meta.get("coverage_pct")
    if coverage is not None:
        try:
            cov = float(coverage)
            if cov < 60:
                issues.append(f"Coverage {cov:.0f}% is low — aim for ≥ 80%")
        except (TypeError, ValueError):
            pass

    confidence = 0.95 if not issues else 0.75
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
