"""P08 Consolidated Task Agent — CI/CD + deployment + monitoring infra."""
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
    ("cicd",           "aether_os.phases.p08_cicd.task_agent",        "run"),
    ("deployment",     "aether_os.phases.p10_deployment.task_agent",   "run"),
    ("monitoring",     "aether_os.phases.p11a_monitoring.task_agent",  "run"),
    ("error_tracking", "aether_os.phases.p11b_error_tracking.task_agent", "run"),
    ("analytics",      "aether_os.phases.p11c_analytics.task_agent",   "run"),
    ("alerting",       "aether_os.phases.p11d_alerting.task_agent",    "run"),
]

_SUBTASK_TIMEOUT = 150.0  # 2.5 min per sub-task


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    for key, module_path, fn_name in _SUB_PHASES:
        try:
            mod = importlib.import_module(module_path)
            # p08_cicd task_agent uses a class-based CICDAgent, not a top-level run()
            if key == "cicd":
                from aether_os.phases.p08_cicd.task_agent import CICDAgent
                agent = CICDAgent()
                sub_result = await asyncio.wait_for(agent.run(phase_input), timeout=_SUBTASK_TIMEOUT)
                r = TaskResult(
                    output_path=sub_result.get("output_path", ""),
                    confidence=0.8,
                    metadata=sub_result,
                    success=sub_result.get("status") not in ("failed",),
                )
            else:
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
    summary_path = output_dir / "consolidated.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    any_success = any(v.success for v in results.values())
    return TaskResult(
        output_path=str(summary_path),
        confidence=0.85 if any_success else 0.5,
        metadata=summary,
        success=any_success or bool(results),
        issues=[] if any_success else ["All CI/CD sub-tasks failed"],
    )
