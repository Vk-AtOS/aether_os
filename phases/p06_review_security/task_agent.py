"""P06 Consolidated Task Agent — code review + security scan."""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_SUBTASK_TIMEOUT = 150.0


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # Sub-task 1: Code Review
    try:
        from aether_os.phases.p05_code_review.task_agent import run as review_run
        sub_dir = output_dir / "code_review"
        r = await asyncio.wait_for(review_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT)
        results["code_review"] = r
        logger.info("code_review completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("code_review timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as e:
        logger.warning("code_review failed (non-critical): %s", e)

    # Sub-task 2: Security Scan
    try:
        from aether_os.phases.p06_security.task_agent import run as security_run
        sub_dir = output_dir / "security"
        r = await asyncio.wait_for(security_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT)
        results["security"] = r
        logger.info("security scan completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("security timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as e:
        logger.warning("security scan failed (non-critical): %s", e)

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
        confidence=0.8 if any_success else 0.5,
        metadata=summary,
        success=True,  # Review/security is non-blocking
        issues=[],
    )
