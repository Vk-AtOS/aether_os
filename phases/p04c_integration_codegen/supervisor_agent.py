"""P04c Integration Codegen Supervisor."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class IntegrationCodegenSupervisor(PhaseBase):
    phase_name = "p04c_integration_codegen"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p04c_integration_codegen.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate always passes — integration codegen is best-effort."""
        return GateOutcome(passed=result.success, confidence=result.confidence)
