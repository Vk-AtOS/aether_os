"""P20 Multi-Region Supervisor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class MultiRegionSupervisor(PhaseBase):
    phase_name = "p20_multiregion"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p20_multiregion.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate passes when multiregion/main.tf was written OR the phase was skipped."""
        if not result.success:
            return GateOutcome(passed=False, issues=result.issues)
        if result.metadata.get("skipped"):
            return GateOutcome(passed=True, confidence=1.0)
        output_dir = Path(result.output_path)
        main_tf = output_dir / "multiregion" / "main.tf"
        if main_tf.exists():
            return GateOutcome(passed=True, confidence=result.confidence)
        return GateOutcome(
            passed=False,
            issues=["p20 gate: multiregion/main.tf not found"],
            confidence=0.0,
        )
