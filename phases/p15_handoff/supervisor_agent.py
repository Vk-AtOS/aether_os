"""P15 Handoff Supervisor — generate complete technical delivery package."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class HandoffSupervisor(PhaseBase):
    phase_name = "p15_handoff"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p15_handoff.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate: at least docs/README.md must have been written."""
        if not result.success:
            return GateOutcome(passed=False, issues=result.issues)
        files = result.metadata.get("files_written", [])
        if not any("README" in f for f in files):
            return GateOutcome(
                passed=False,
                issues=["Handoff gate: docs/README.md was not generated"],
                confidence=0.0,
            )
        return GateOutcome(passed=True, confidence=result.confidence)
