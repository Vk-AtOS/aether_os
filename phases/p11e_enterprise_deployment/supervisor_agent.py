"""P11e Enterprise Deployment Supervisor."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class EnterpriseDeploymentSupervisor(PhaseBase):
    phase_name = "p11e_enterprise_deployment"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p11e_enterprise_deployment.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate: at least some files were written."""
        if not result.success:
            return GateOutcome(passed=False, issues=result.issues)
        files = result.metadata.get("files_written", [])
        if not files:
            return GateOutcome(passed=False, issues=["p11e gate: no files written"], confidence=0.0)
        return GateOutcome(passed=True, confidence=result.confidence)
