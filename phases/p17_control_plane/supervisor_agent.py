"""P17 Control Plane Supervisor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class ControlPlaneSupervisor(PhaseBase):
    phase_name = "p17_control_plane"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p17_control_plane.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate passes if operator/main.go was generated or the phase was skipped."""
        if result.metadata.get("skipped"):
            return GateOutcome(passed=True, confidence=1.0)
        main_go = Path(result.output_path) / "main.go"
        if main_go.exists():
            return GateOutcome(passed=True, confidence=result.confidence)
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=["operator/main.go not found after generation"],
        )
