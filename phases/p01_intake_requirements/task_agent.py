"""P01 Consolidated Task Agent — intake + requirements in one phase."""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # Sub-task 1: Intake (3 min timeout)
    try:
        from aether_os.phases.p00_intake.task_agent import run as p00_run
        sub_dir = output_dir / "intake"
        r = await asyncio.wait_for(p00_run(phase_input, memory_ctx, sub_dir), timeout=180.0)
        results["intake"] = r
        if r.success and r.metadata:
            phase_input.input_data.update(r.metadata.get("intake_record", {}))
        logger.info("p00_intake completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("p00_intake timed out after 180s, continuing")
    except Exception as e:
        logger.warning("p00_intake failed: %s", e)

    # Sub-task 2: Requirements (3 min timeout)
    try:
        from aether_os.phases.p01_requirements.task_agent import run as p01_run
        sub_dir = output_dir / "requirements"
        r = await asyncio.wait_for(p01_run(phase_input, memory_ctx, sub_dir), timeout=180.0)
        results["requirements"] = r
        if r.success and r.metadata:
            phase_input.input_data.update(r.metadata)
        logger.info("p01_requirements completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("p01_requirements timed out after 180s, continuing")
    except Exception as e:
        logger.warning("p01_requirements failed: %s", e)

    # Write consolidated summary
    summary = {
        "phases": {
            k: {
                "output_path": v.output_path,
                "success": v.success,
                "confidence": v.confidence,
                "metadata": v.metadata,
            }
            for k, v in results.items()
        }
    }
    summary_path = output_dir / "consolidated.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    any_success = any(v.success for v in results.values())
    best = next((v for v in results.values() if v.success), None) or next(iter(results.values()), None)

    return TaskResult(
        output_path=str(summary_path),
        confidence=0.85 if any_success else 0.3,
        metadata=summary,
        success=any_success or bool(results),
        issues=[] if any_success else ["All sub-tasks failed"],
    )
