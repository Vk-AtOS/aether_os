from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome
from . import task_agent
from . import gate as gate_module

class SupervisorAgent(PhaseBase):
    phase_name = "p11d_alerting"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_agent.run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        return await gate_module.validate(result, phase_input)
