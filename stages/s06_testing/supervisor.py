"""
Stage 6: TESTING
================
PURPOSE: Multi-layer automated testing of all generated code. Runs unit tests,
         performance benchmarks, accessibility audits, and E2E browser tests.
         Aggregates results into a single quality verdict.

INPUTS:
  - backend_output_path  : str   — FastAPI src/ (from Stage 3)
  - frontend_output_path : str   — React src/ (from Stage 4)
  - backend_port         : int   — running port (if app is already started)
  - frontend_url         : str   — running URL (for accessibility + E2E)

OUTPUTS:
  - test_results         : dict  — unit test summary (pass/fail counts, coverage)
  - perf_results         : dict  — p50/p95/p99 latency, throughput
  - a11y_results         : dict  — axe-core accessibility violations
  - e2e_results          : dict  — Playwright E2E test summary
  - test_quality_flag    : str   — "pass" | "warn" | "fail" — overall verdict
  - consolidated_report  : dict  — merged across all test types

SUB-STEPS:
  1. p07a_unit_testing — pytest unit tests on static files (runs here, no app needed)

  DEFERRED to Stage 7 (runs after app is proven live):
  2. p07b_performance_testing — 10×5 concurrent requests, p50/p95/p99
  3. p07c_accessibility_testing — axe-core + ARIA scan
  4. p07d_e2e_testing — Playwright TypeScript E2E

  NOTE: Performance, accessibility, and E2E tests require a running app
        (backend_port / frontend_url). Stage 6 runs before the app is started.
        These three are deferred to Stage 7 (HealingStageSupervisor) which starts
        the app first and then triggers the live test pass.

  2. [SEQUENTIAL] Consolidation — aggregate pass rates into test_quality_flag

CRITICAL: No — a crash or timeout of this stage does not end the run.
GATE: blocks (ends the run after the retries) when NO unit test ran: healing would then have no
      test summary to work from. Failing unit tests do NOT block (Stage 7 repairs them); that, and
      everything this stage does not check, is written into the result under "gate".
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
from typing import Any, Dict, List

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult

logger = logging.getLogger(__name__)

# How long to allow each sub-phase before giving up (non-fatal timeout)
_SUBTASK_TIMEOUT = 150.0  # 2.5 minutes per test type

# Unit tests only — run on static files, no running app required.
_SUB_PHASES = [
    ("unit_testing", "aether_os.phases.p07a_unit_testing.task_agent", "run"),
]

# Live tests — deferred to Stage 7 after the app is confirmed healthy.
# HealingStageSupervisor imports and runs these after its health probe passes.
LIVE_TEST_PHASES = [
    ("performance_testing",   "aether_os.phases.p07b_performance_testing.task_agent",   "run"),
    ("accessibility_testing", "aether_os.phases.p07c_accessibility_testing.task_agent", "run"),
    ("e2e_testing",           "aether_os.phases.p07d_e2e_testing.task_agent",           "run"),
]

# What this stage never checks; stated in every result so "s06 passed" is not read as more than it is.
_NOT_CHECKED = [
    *[f"{key}: not run here, deferred to s07_healing (needs the running app)" for key, _, _ in LIVE_TEST_PHASES],
    "frontend unit tests: none are generated or run (p07a tests the backend API only)",
]

STAGE_CONTRACT = {
    "stage": "s06_testing",
    "display_name": "Testing",
    "critical": False,
    "parallel_substeps": [
        "p07a_unit_testing",  # runs here (static)
        # p07b/p07c/p07d deferred to s07_healing after app is live
    ],
    "inputs": [
        "backend_output_path",
        "frontend_output_path",
        "backend_port",
        "frontend_url",
    ],
    "outputs": [
        "test_results",
        "perf_results",
        "a11y_results",
        "e2e_results",
        "test_quality_flag",
        "consolidated_report",
    ],
}


class TestingStageSupervisor(PhaseBase):
    """Consolidated supervisor for Stage 6 (Testing).

    Runs all four test layers (unit, performance, accessibility, E2E) concurrently
    via asyncio.gather with return_exceptions=True so a single test layer failure
    never blocks the others.  Results are aggregated into test_quality_flag.
    """

    phase_name = "s06_testing"

    async def run_task(
        self, phase_input: Any, memory_ctx: List[Dict]
    ) -> TaskResult:
        from aether_os.core.projects import get_project_manager

        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        # ── Idempotency: skip re-run if tests already passed ──────────────────
        # Prevents redundant runs when the orchestrator restarts a stalled pipeline.
        _cached = output_dir / "consolidated.json"
        if _cached.exists():
            try:
                _prev = json.loads(_cached.read_text())
                if (
                    _prev.get("pytest_actually_passed")
                    and _prev.get("test_quality_flag") == "pass"
                ):
                    logger.info("s06_testing: cached result found (tests passed) — skipping re-run")
                    return TaskResult(
                        output_path=str(_cached),
                        confidence=0.95,
                        metadata=_prev,
                        success=True,
                        issues=[],
                    )
            except Exception as exc:
                logger.warning("s06_testing: idempotent cache read failed (non-fatal): %s", exc)

        # ── Run all 4 test layers concurrently ────────────────────────────────
        # We build the coroutines first so we can zip results with keys below.
        async def _run_one(key: str, module_path: str, fn_name: str) -> TaskResult:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, fn_name)
            sub_dir = output_dir / key
            sub_dir.mkdir(parents=True, exist_ok=True)
            return await asyncio.wait_for(
                fn(phase_input, memory_ctx, sub_dir),
                timeout=_SUBTASK_TIMEOUT,
            )

        raw_results = await asyncio.gather(
            *[_run_one(key, mod_path, fn) for key, mod_path, fn in _SUB_PHASES],
            return_exceptions=True,
        )

        # Build a dict of key → TaskResult (skipping exceptions/timeouts gracefully)
        results: Dict[str, TaskResult] = {}
        issues: List[str] = []
        for (key, _, _), outcome in zip(_SUB_PHASES, raw_results):
            if isinstance(outcome, asyncio.TimeoutError):
                logger.warning("s06: %s timed out after %.0fs (non-critical)", key, _SUBTASK_TIMEOUT)
                issues.append(f"{key} timed out")
            elif isinstance(outcome, Exception):
                logger.warning("s06: %s failed (non-critical): %s", key, outcome)
                issues.append(f"{key} failed: {outcome}")
            else:
                results[key] = outcome
                logger.info("s06: %s completed — success=%s", key, outcome.success)

        # ── Step 5: Consolidate results into test_quality_flag ─────────────────
        consolidated = _consolidate_results(results, issues)

        consolidated["gate"] = _gate_report(consolidated)
        _cached.write_text(json.dumps(consolidated, indent=2, default=str))

        quality_flag = consolidated["test_quality_flag"]
        confidence = 0.95 if quality_flag == "pass" else (0.60 if quality_flag == "warn" else 0.30)

        return TaskResult(
            output_path=str(_cached),
            confidence=confidence,
            metadata=consolidated,
            # Non-critical: the run continues, but a failing test verdict is reported as a
            # failed stage (run result stage_summary) instead of "passed".
            success=quality_flag != "fail",
            issues=issues if quality_flag == "fail" else [],
        )

    async def validate_gate(
        self, result: TaskResult, phase_input: Any
    ) -> GateOutcome:
        # Blocks when no unit test ran. Failing tests pass the gate on purpose (Stage 7 repairs
        # them) and are disclosed in metadata["gate"], not hidden.
        meta = result.metadata or {}
        gate = meta.get("gate") or _gate_report(meta)   # a cached result from before the field existed
        if gate["passed"]:
            return GateOutcome(passed=True, confidence=result.confidence, issues=result.issues)
        # p07a names a collection error / an app that does not import (KAN-250); "ran nothing" hid that cause.
        unit = meta.get("test_results") if isinstance(meta.get("test_results"), dict) else {}
        why = "; ".join(str(i) for i in meta.get("skipped_phases") or []) or (
            f"collection error: {unit['collection_error']}" if unit.get("collection_error")
            else "pytest collected or ran nothing")
        return GateOutcome(passed=False, confidence=result.confidence, issues=[f"no unit test ran: {why}"])


# ── Module-level helpers ──────────────────────────────────────────────────────


def _gate_report(consolidated: Dict[str, Any]) -> Dict[str, Any]:
    """The stage gate's verdict plus what it did not check (stored as consolidated["gate"])."""
    total = int(consolidated.get("total_tests") or 0)
    failed = total - int(consolidated.get("passed_tests") or 0)
    return {
        "passed": total > 0,
        "rule": "blocks when no unit test ran; failing unit tests do not block (s07_healing repairs them)",
        "tests_ran": total,
        "tests_failed": failed,
        "tests_failed_but_did_not_block": total > 0 and failed > 0,
        "not_checked": _NOT_CHECKED + [f"layer did not run: {i}" for i in consolidated.get("skipped_phases") or []],
    }


def _consolidate_results(
    results: Dict[str, TaskResult],
    issues: List[str],
) -> Dict[str, Any]:
    """Aggregate per-layer TaskResults into a single consolidated report.

    test_quality_flag logic:
      "pass" — all layers that ran report no failures (pass_rate >= 0.7 or
               pytest_actually_passed=True and no unit failures)
      "warn" — some layers skipped OR pass_rate is 0.4–0.7 OR >20% failed
      "fail" — pass_rate below 0.4, or unit AND performance layers both failed.
               (It used to need both layers to fail; s06 runs the unit layer only, so
               its verdict could never be "fail" while tests ran: 0 of 10 was a "warn".)
               A "fail" marks the stage failed in the run result; it does not stop healing.
    """
    total_tests = 0
    passed_tests = 0
    test_code_found = False
    pytest_actually_passed = False

    unit_failed = False
    perf_failed = False

    per_layer: Dict[str, Any] = {}

    for key, r in results.items():
        per_layer[key] = {
            "output_path": r.output_path,
            "success": r.success,
            "confidence": r.confidence,
            "issues": r.issues,
        }
        if not r.metadata:
            continue

        _passed = r.metadata.get("passed_tests", r.metadata.get("passed", 0))
        _failed = r.metadata.get("failed_tests", r.metadata.get("failed", 0))
        _total  = r.metadata.get("total_tests", _passed + _failed)

        total_tests  += _total
        passed_tests += _passed

        if r.metadata.get("test_code") or r.metadata.get("test_file"):
            test_code_found = True
        if r.metadata.get("pytest_passed") or (_total > 0 and _passed == _total):
            pytest_actually_passed = True

        # Track which layers individually failed for the "fail" verdict
        if key == "unit_testing" and _total > 0 and _passed < _total:
            unit_failed = True
        if key == "performance_testing" and r.metadata.get("passed") is False:
            perf_failed = True

    # Compute overall pass rate
    if total_tests > 0:
        pass_rate = passed_tests / total_tests
    elif pytest_actually_passed:
        pass_rate = 1.0
    else:
        pass_rate = 0.0

    # Apply the 3-tier verdict logic described in the docstring
    skipped_count = len(_SUB_PHASES) - len(results)
    if skipped_count > 0:
        # Some layers were skipped (timeout/error) → at best "warn"
        if unit_failed and perf_failed:
            quality_flag = "fail"
        elif pass_rate < 0.40:
            quality_flag = "fail"
        else:
            quality_flag = "warn"
    elif total_tests > 0:
        if pass_rate >= 0.70:
            quality_flag = "pass"
        elif pass_rate >= 0.40:
            quality_flag = "warn"
        else:
            quality_flag = "fail"
    elif pytest_actually_passed:
        quality_flag = "pass"
    elif test_code_found:
        quality_flag = "warn"  # tests exist but results are unknown
    else:
        quality_flag = "warn"  # no tests generated (rate-limited etc.)

    return {
        "phases": per_layer,
        "skipped_phases": issues,
        "test_quality_flag": quality_flag,
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "pass_rate": round(pass_rate, 3),
        "pytest_actually_passed": pytest_actually_passed,
        "test_results": results.get("unit_testing", TaskResult("", 0.0)).metadata if "unit_testing" in results else {},
        "perf_results":  results.get("performance_testing", TaskResult("", 0.0)).metadata if "performance_testing" in results else {},
        "a11y_results":  results.get("accessibility_testing", TaskResult("", 0.0)).metadata if "accessibility_testing" in results else {},
        "e2e_results":   results.get("e2e_testing", TaskResult("", 0.0)).metadata if "e2e_testing" in results else {},
        "consolidated_report": {
            "verdict": quality_flag,
            "layers_run": list(results.keys()),
            "layers_skipped": [k for k, _, _ in _SUB_PHASES if k not in results],
        },
    }
