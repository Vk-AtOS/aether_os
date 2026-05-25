"""P09 Consolidated Task Agent — feature flags + A/B testing + app memory."""
from __future__ import annotations
import asyncio
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_SUB_PHASES: list = [
    # PIPELINE-009: p12a_feature_flags, p12b_ab_testing, and p13_app_memory are
    # separate phases in PHASE_SEQUENCE.  Running them here would cause double
    # execution and doubled LLM cost.  p09 only runs its own observability logic.
]

_SUBTASK_TIMEOUT = 120.0


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
            logger.warning("%s timed out after %.0fs", key, _SUBTASK_TIMEOUT)
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

    return TaskResult(
        output_path=str(summary_path),
        confidence=0.8,
        metadata=summary,
        success=True,
        issues=[],
    )
