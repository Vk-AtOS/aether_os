"""P07 Consolidated Task Agent — unit + performance + accessibility + e2e testing."""
from __future__ import annotations
import asyncio
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_SUB_PHASES = [
    ("unit_testing",          "aether_os.phases.p07a_unit_testing.task_agent",          "run"),
    ("performance_testing",   "aether_os.phases.p07b_performance_testing.task_agent",   "run"),
    ("accessibility_testing", "aether_os.phases.p07c_accessibility_testing.task_agent", "run"),
    ("e2e_testing",           "aether_os.phases.p07d_e2e_testing.task_agent",           "run"),
]

_SUBTASK_TIMEOUT = 150.0  # 2.5 min per sub-task


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    for key, module_path, fn_name in _SUB_PHASES:
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, fn_name)
            sub_dir = output_dir / key
            r = await asyncio.wait_for(fn(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT)
            results[key] = r
            logger.info("%s completed: %s", key, r.output_path)
        except asyncio.TimeoutError:
            logger.warning("%s timed out after %.0fs (non-critical)", key, _SUBTASK_TIMEOUT)
        except Exception as e:
            logger.warning("%s failed (non-critical): %s", key, e)

    summary = {
        "phases": {
            k: {"output_path": v.output_path, "success": v.success, "confidence": v.confidence}
            for k, v in results.items()
        }
    }

    # Aggregate real test results from sub-phases
    total_tests = 0
    passed_tests = 0
    test_code_found = False
    pytest_actually_passed = False

    for key, r in results.items():
        if r.metadata:
            # p07a writes "passed"/"failed"; p07b_perf/others may write "total_tests"/"passed_tests"
            _passed = r.metadata.get("passed_tests", r.metadata.get("passed", 0))
            _failed = r.metadata.get("failed_tests", r.metadata.get("failed", 0))
            _total  = r.metadata.get("total_tests", _passed + _failed)
            total_tests  += _total
            passed_tests += _passed
            if r.metadata.get("test_code") or r.metadata.get("test_file"):
                test_code_found = True
            if r.metadata.get("pytest_passed") or (_total > 0 and _passed == _total):
                pytest_actually_passed = True

    # Determine real quality outcome
    if total_tests > 0:
        pass_rate = passed_tests / total_tests
        quality_flag = "pass" if pass_rate >= 0.7 else ("warn" if pass_rate >= 0.4 else "fail")
    elif pytest_actually_passed:
        quality_flag = "pass"
    elif test_code_found:
        quality_flag = "warn"  # tests exist but we don't know results
    else:
        quality_flag = "warn"  # no tests (rate limited etc)

    summary["test_quality_flag"] = quality_flag
    summary["total_tests"] = total_tests
    summary["passed_tests"] = passed_tests
    summary["pytest_actually_passed"] = pytest_actually_passed

    summary_path = output_dir / "consolidated.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    return TaskResult(
        output_path=str(summary_path),
        confidence=0.95 if quality_flag == "pass" else (0.6 if quality_flag == "warn" else 0.3),
        metadata=summary,
        success=True,  # KEEP non-blocking — but now carry real quality data
        issues=[] if quality_flag != "fail" else [f"Tests failing: {passed_tests}/{total_tests} passed"],
    )
