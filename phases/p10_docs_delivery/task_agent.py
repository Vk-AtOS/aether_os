"""P10 Consolidated Task Agent — documentation + client portal + change requests."""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_SUBTASK_TIMEOUT = 180.0  # 3 min per sub-task (docs generate more text)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # Sub-task 1: Documentation (primary)
    try:
        from aether_os.phases.p09_documentation.task_agent import run as docs_run
        sub_dir = output_dir / "docs"
        r = await asyncio.wait_for(docs_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT)
        results["documentation"] = r
        if r.success:
            phase_input.input_data["docs_path"] = r.output_path
        logger.info("documentation completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("documentation timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as e:
        logger.warning("documentation failed (non-critical): %s", e)

    # Sub-task 2: Client Portal
    try:
        from aether_os.phases.p14_client_portal.task_agent import run as portal_run
        sub_dir = output_dir / "client_portal"
        r = await asyncio.wait_for(portal_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT)
        results["client_portal"] = r
        logger.info("client_portal completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("client_portal timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as e:
        logger.warning("client_portal failed (non-critical): %s", e)

    # Sub-task 3: Change Requests
    try:
        from aether_os.phases.p15_change_requests.task_agent import run as cr_run
        sub_dir = output_dir / "change_requests"
        r = await asyncio.wait_for(cr_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT)
        results["change_requests"] = r
        logger.info("change_requests completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("change_requests timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as e:
        logger.warning("change_requests failed (non-critical): %s", e)

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
        issues=[] if any_success else ["No docs/delivery output generated"],
    )
