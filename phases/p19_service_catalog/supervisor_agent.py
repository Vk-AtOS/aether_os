"""P19 Service Catalog Supervisor — AetherOS Layer 7."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome

logger = logging.getLogger(__name__)


class ServiceCatalogSupervisor(PhaseBase):
    phase_name = "p19_service_catalog"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p19_service_catalog.task_agent import run as task_run
        output_dir = Path(phase_input.input_data.get("project_dir", "/tmp")) / self.phase_name
        return await task_run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Gate passes if router.py exists OR the phase was skipped (non-cloud build)."""
        skipped = result.metadata.get("skipped", False)
        if skipped:
            return GateOutcome(passed=True, confidence=1.0)
        router_exists = result.metadata.get("router_exists", False)
        return GateOutcome(passed=router_exists or result.success, confidence=result.confidence)
