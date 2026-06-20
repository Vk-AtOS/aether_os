"""P21 SRE Agent Supervisor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class SREAgentSupervisor(PhaseBase):
    phase_name = "p21_sre_agent"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p21_sre_agent.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate passes when the SRE CronJob YAML was written."""
        if not result.success:
            return GateOutcome(passed=False, issues=result.issues)
        output_dir = Path(result.output_path)
        cronjob_yaml = output_dir / "k8s" / "sre-agent-cronjob.yaml"
        if cronjob_yaml.exists():
            return GateOutcome(passed=True, confidence=result.confidence)
        return GateOutcome(
            passed=False,
            issues=["p21 gate: k8s/sre-agent-cronjob.yaml not found"],
            confidence=0.0,
        )
