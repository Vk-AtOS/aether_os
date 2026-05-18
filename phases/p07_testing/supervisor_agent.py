"""P07 Supervisor — testing consolidated."""
from __future__ import annotations
from typing import Any, List
from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome


class TestingSupervisor(PhaseBase):
    phase_name = "p07_testing"

    async def run_task(self, phase_input: Any, memory_ctx: List) -> TaskResult:
        from aether_os.phases.p07_testing.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        output_dir = get_project_manager().get_output_dir(phase_input.project_id, self.phase_name)
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        from aether_os.phases.p07_testing.gate import validate
        return validate(result)
