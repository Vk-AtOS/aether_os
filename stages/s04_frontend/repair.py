"""s04 targeted repair (KAN-210): fix the files the gate named instead of re-running the whole stage."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Dict

from aether_os.phases.base import TaskResult
from aether_os.phases.p05_frontend.build_loop import result_summary, run_build_loop
from aether_os.phases.p05_frontend.crash_gate import run_crash_gate
from aether_os.phases.p05_frontend.npm_runner import get_npm_semaphore
from aether_os.phases.targeted_retry import parse_failed_files


def failed_files_from_metadata(meta: Dict[str, Any]) -> Dict[str, str]:
    """{file: error} from the build output p05 recorded (bundle errors first, then tsc messages)."""
    text = "\n".join([str(meta.get("build_errors") or ""), *map(str, meta.get("tsc_messages") or [])])
    return parse_failed_files(text)


async def repair_frontend_files(result: TaskResult, frontend_dir: Path) -> TaskResult:
    """Rebuild and patch the failing frontend files with their error context (p05 build loop), return the new result.

    The only call to a repair engine in s04: swap it here when the shared patch helper lands.
    """
    async with get_npm_semaphore():
        loop = await run_build_loop(frontend_dir, max_rounds=2)
        # The repair loop can leave a model-written page that crashes at runtime (run 27: s04 re-ran p05, then
        # rebuilt here without the crash gate). Replace such pages with their templates and rebuild once.
        if await run_crash_gate(frontend_dir, loop.get("tsc_all", [])):
            loop = await run_build_loop(frontend_dir, max_rounds=1)
    meta, issues = result_summary(loop)
    return dataclasses.replace(result, success=bool(loop["success"]), metadata={**result.metadata, **meta},
                               issues=issues)
