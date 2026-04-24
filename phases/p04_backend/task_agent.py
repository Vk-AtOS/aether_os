"""P04 Consolidated Task Agent — backend codegen + UI/UX design."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # Sub-task 1: Backend Codegen
    try:
        from aether_os.phases.p04a_backend_codegen.task_agent import run as p04a_run
        sub_dir = output_dir / "backend_codegen"
        r = await p04a_run(phase_input, memory_ctx, sub_dir)
        results["backend_codegen"] = r
        if r.success and r.metadata:
            phase_input.input_data["backend_output_path"] = r.output_path
            phase_input.input_data.update({k: v for k, v in r.metadata.items() if k not in phase_input.input_data})
        logger.info("p04a_backend_codegen completed: %s", r.output_path)
    except Exception as e:
        logger.warning("p04a_backend_codegen failed: %s", e)

    # Sub-task 2: UI/UX Design
    try:
        from aether_os.phases.p04b_uiux_design.task_agent import run as p04b_run
        sub_dir = output_dir / "uiux_design"
        r = await p04b_run(phase_input, memory_ctx, sub_dir)
        results["uiux_design"] = r
        logger.info("p04b_uiux_design completed: %s", r.output_path)
    except Exception as e:
        logger.warning("p04b_uiux_design failed (non-critical): %s", e)

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
        confidence=0.85 if any_success else 0.3,
        metadata=summary,
        success=any_success or bool(results),
        issues=[] if any_success else ["All sub-tasks failed"],
    )
