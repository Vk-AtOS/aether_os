"""P08 Supervisor — CI/CD + deployment consolidated."""
from __future__ import annotations
from typing import Any, List
from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
from aether_os.phases.p08_cicd_deployment import gate as p08_gate


class CICDDeploymentSupervisor(PhaseBase):
    phase_name = "p08_cicd_deployment"

    async def run_task(self, phase_input: Any, memory_ctx: List) -> TaskResult:
        from aether_os.phases.p08_cicd_deployment.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        output_dir = get_project_manager().get_output_dir(phase_input.project_id, self.phase_name)
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        return p08_gate.validate(result)
