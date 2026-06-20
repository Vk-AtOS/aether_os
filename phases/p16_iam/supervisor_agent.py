"""P16 IAM Supervisor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class IAMSupervisor(PhaseBase):
    phase_name = "p16_iam"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p16_iam.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate passes if policy.rego was written successfully."""
        if not result.success:
            return GateOutcome(passed=False, confidence=0.0, issues=["IAM generation failed"])
        iam_dir = Path(result.output_path)
        policy_file = iam_dir / "policy.rego"
        if not policy_file.exists():
            return GateOutcome(
                passed=False,
                confidence=0.0,
                issues=[f"policy.rego not found at {policy_file}"],
            )
        return GateOutcome(passed=True, confidence=result.confidence)
