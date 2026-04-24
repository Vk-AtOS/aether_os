"""P00 Supervisor Agent — orchestrates the 4-agent intake pattern."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
from aether_os.phases.p00_intake import gate as p00_gate

logger = logging.getLogger(__name__)


class IntakeSupervisor(PhaseBase):
    phase_name = "p00_intake"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p00_intake.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        return p00_gate.validate(result)

    async def communicate(self, **kwargs) -> None:
        from aether_os.phases.p00_intake.communication_agent import publish_result
        await publish_result(**kwargs)
