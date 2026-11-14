"""P11 Supervisor — Docker deployment phase."""
from __future__ import annotations
from typing import Any, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
from aether_os.phases.p11_deployment import gate as p11_gate


class DeploymentSupervisor(PhaseBase):
    phase_name = "p11_deployment"

    async def run_task(self, phase_input: Any, memory_ctx: List) -> TaskResult:
        from aether_os.phases.p11_deployment.task_agent import TaskAgent
        from aether_os.core.projects import get_project_manager

        agent = TaskAgent()
        result = await agent.run(phase_input)

        output_dir = get_project_manager().get_output_dir(
            phase_input.project_id, self.phase_name
        )

        return TaskResult(
            output_path=result.get("output_file", str(output_dir)),
            confidence=0.9 if result.get("success") else 0.4,
            # a skip is a success only when the agent says so (Docker absent); "success": False +
            # "skipped": True is a failed deploy (no main.py, frontend build failed)
            success=bool(result.get("success", False)),
            metadata=result,
        )

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        return p11_gate.validate(result)
