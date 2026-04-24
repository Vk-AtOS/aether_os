"""P01 Supervisor — intake + requirements consolidated."""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
from aether_os.phases.p01_intake_requirements import gate as p01_gate

logger = logging.getLogger(__name__)


class IntakeRequirementsSupervisor(PhaseBase):
    phase_name = "p01_intake_requirements"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p01_intake_requirements.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        return p01_gate.validate(result)
