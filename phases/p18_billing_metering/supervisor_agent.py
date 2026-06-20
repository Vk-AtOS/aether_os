"""P18 Billing & Metering Supervisor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class BillingMeteringSupervisor(PhaseBase):
    phase_name = "p18_billing_metering"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p18_billing_metering.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate passes if billing_webhook.py was written into the billing output directory."""
        webhook = Path(result.output_path) / "billing_webhook.py"
        if webhook.exists():
            return GateOutcome(passed=True, confidence=result.confidence)
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=["billing/billing_webhook.py not found after generation"],
        )
