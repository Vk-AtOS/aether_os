"""P04 Consolidated Task Agent — backend codegen + UI/UX design."""
from __future__ import annotations
import json
import logging
import re
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
            # Extract API routes from generated main.py so p05 can wire to real endpoints
            _backend_out = Path(r.output_path)
            for _main_candidate in [
                _backend_out / "src" / "main.py",
                _backend_out.parent / "src" / "main.py",
            ]:
                if _main_candidate.exists():
                    _code = _main_candidate.read_text()
                    _routes = []
                    for _m in re.finditer(
                        r'@app\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']',
                        _code, re.IGNORECASE
                    ):
                        _routes.append({"method": _m.group(1).upper(), "path": _m.group(2)})
                    if _routes:
                        _routes_file = _backend_out / "api_routes.json"
                        _routes_file.write_text(json.dumps(_routes, indent=2))
                        phase_input.input_data["api_routes_path"] = str(_routes_file)
                        logger.info("p04: extracted %d routes → %s", len(_routes), _routes_file)
                    break
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
