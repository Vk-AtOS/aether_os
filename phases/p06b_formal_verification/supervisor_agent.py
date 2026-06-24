"""P06b Supervisor — formal verification of generated routes via Z3 SMT solver."""
from __future__ import annotations

from typing import Any, List

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.phases.p06b_formal_verification import gate as p06b_gate


class FormalVerificationSupervisor(PhaseBase):
    phase_name = "p06b_formal_verification"

    async def run_task(self, phase_input: Any, memory_ctx: List) -> TaskResult:
        from aether_os.phases.p06b_formal_verification.task_agent import run as task_run
        from aether_os.core.projects import get_project_manager
        output_dir = get_project_manager().get_output_dir(
            phase_input.project_id, self.phase_name
        )
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        return p06b_gate.validate(result)
