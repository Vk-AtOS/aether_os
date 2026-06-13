"""P02c Permission Modeling Supervisor."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class PermissionModelingSupervisor(PhaseBase):
    phase_name = "p02c_permission_modeling"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p02c_permission_modeling.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate: permission_model.json must have at least one role defined."""
        if not result.success:
            return GateOutcome(passed=False, issues=result.issues)
        model = result.metadata.get("permission_model", {})
        if not model.get("roles"):
            return GateOutcome(
                passed=False,
                issues=["p02c gate: permission model has no roles defined"],
                confidence=0.0,
            )
        return GateOutcome(passed=True, confidence=result.confidence)
