"""P04b Supervisor — business logic layer."""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult

logger = logging.getLogger(__name__)

class BusinessLogicSupervisor(PhaseBase):
    phase_name = "p04b_business_logic"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from phases.p04b_business_logic.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        return await task_run(phase_input, memory_ctx, output_dir)
