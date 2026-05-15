"""P09 Supervisor Agent."""
from __future__ import annotations
from typing import Any, Dict, List
from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
from aether_os.phases.p09_documentation import gate as phase_gate


class DocumentationSupervisor(PhaseBase):
    phase_name = "p09_documentation"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p09_documentation.task_agent import run
        from aether_os.core.projects import get_project_manager
        output_dir = get_project_manager().get_output_dir(phase_input.project_id, self.phase_name)
        return await run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        return phase_gate.validate(result)
