"""P05c Desktop Supervisor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class DesktopSupervisor(PhaseBase):
    phase_name = "p05c_desktop"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p05c_desktop.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate always passes — desktop generation is optional."""
        return GateOutcome(passed=result.success, confidence=result.confidence)
