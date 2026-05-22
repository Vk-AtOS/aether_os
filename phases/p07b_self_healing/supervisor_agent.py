"""P07b Supervisor — self-healing (autonomous bug fix loop)."""
from __future__ import annotations
from typing import Any, List
from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome


class SelfHealingSupervisor(PhaseBase):
    phase_name = "p07b_self_healing"

    async def run_task(self, phase_input: Any, memory_ctx: List) -> TaskResult:
        from aether_os.phases.p07b_self_healing.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        output_dir = get_project_manager().get_output_dir(phase_input.project_id, self.phase_name)
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        from aether_os.phases.p07b_self_healing.gate import validate
        return validate(result)
