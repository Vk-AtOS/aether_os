"""P08 Supervisor Agent — CI/CD."""
from __future__ import annotations
from typing import Any, Dict, List
from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
from aether_os.phases.p08_cicd import gate as p08_gate


class CICDSupervisor(PhaseBase):
    phase_name = "p08_cicd"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p08_cicd.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        return p08_gate.validate(result)
