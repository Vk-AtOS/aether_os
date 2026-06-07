"""P00 Supervisor — domain research phase."""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)

class ResearchSupervisor(PhaseBase):
    phase_name = "p00_research"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from phases.p00_research.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate 1: Confirm research direction with the user."""
        from phases.p00_research.gate import validate as gate_validate
        return gate_validate(result)
