"""P02b Domain IR phase — 4-pass Domain Intermediate Representation extraction."""
from __future__ import annotations

from typing import Any, Dict, List

from aether_os.phases.base import PhaseBase, TaskResult, GateOutcome


class DomainIRSupervisor(PhaseBase):
    phase_name = "p02b_domain_ir"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.phases.p02b_domain_ir.task_agent import run
        from aether_os.core.projects import get_project_manager
        output_dir = get_project_manager().get_output_dir(phase_input.project_id, self.phase_name)
        return await run(phase_input, memory_ctx, output_dir)

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        if not result.success:
            return GateOutcome(passed=False, issues=result.issues, confidence=0.0)
        ir_path = result.metadata.get("domain_ir_path", "")
        if not ir_path:
            return GateOutcome(passed=False, issues=["domain_ir.json not written"], confidence=0.0)
        entity_count = result.metadata.get("entity_count", 0)
        if entity_count == 0:
            return GateOutcome(passed=False, issues=["No entities extracted"], confidence=0.2)
        return GateOutcome(passed=True, issues=[], confidence=result.confidence)
