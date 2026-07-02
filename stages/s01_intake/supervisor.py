"""
Stage 1: INTAKE
===============
PURPOSE: Understand what the user wants to build. Research the domain, mine
         similar past builds, discover external integrations, and extract a
         binding project contract from the user's natural language description.

INPUTS (accumulated_context / phase_input.input_data keys consumed):
  - raw_input           : str   — the user's natural language description
  - domain              : str   — business vertical (ecommerce, healthcare, etc.)
  - autonomous_mode     : bool  — skip human approval gates when True
  - build_profile       : dict  — optional existing build profile (for resume runs)

OUTPUTS (phase_input.input_data keys written by this stage):
  - requirements        : dict  — structured project requirements
  - entities            : list  — entity names to be built
  - api_endpoints       : list  — route specs
  - integration_map     : dict  — external services/APIs discovered
  - design_brief        : dict  — competitor analysis + design direction
  - similar_past_runs   : list  — top-3 similar past successful builds
  - project_contract    : dict  — binding spec referenced by downstream stages
  - service_map         : dict  — service decomposition (monolith or microservices)
  - user_personas       : list  — target user types
  - user_roles          : list  — RBAC roles needed

SUB-STEPS:
  1. [PARALLEL] Research         — competitor analysis via p00_research
  2. [PARALLEL] Data Archaeology — past run mining via p00b_data_archaeology
  3. [PARALLEL] Arch Planning    — service map via p00c_architecture_planner
  4. [SEQUENTIAL] Requirements   — entity/contract extraction via p01_intake_requirements
  5. [SEQUENTIAL] Integrations   — external service discovery via p01b_integration_discovery

CRITICAL: True — pipeline aborts if requirements extraction (step 4) fails
LLM CALLS: ~5 total (1 per sub-step)
PARALLEL SPEEDUP: Steps 1-3 run concurrently via asyncio.gather
"""
from __future__ import annotations

import asyncio
import copy
import importlib
import logging
from typing import Any, Dict, List

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult

logger = logging.getLogger(__name__)

STAGE_CONTRACT = {
    "stage": "s01_intake",
    "display_name": "Intake",
    "critical": True,
    "parallel_substeps": [
        "p00_research",
        "p00b_data_archaeology",
        "p00c_architecture_planner",
    ],
    "sequential_substeps": [
        "p01_intake_requirements",
        "p01b_integration_discovery",
    ],
    "inputs": ["raw_input", "domain", "autonomous_mode"],
    "outputs": [
        "requirements",
        "entities",
        "api_endpoints",
        "integration_map",
        "design_brief",
        "similar_past_runs",
        "project_contract",
        "service_map",
        "user_personas",
        "user_roles",
    ],
}


class IntakeStageSupervisor(PhaseBase):
    """Consolidated supervisor for Stage 1 (Intake).

    Orchestrates five legacy phases (p00, p00b, p00c, p01, p01b) into a single
    stage.  Steps 1-3 run in parallel; steps 4-5 run sequentially because each
    depends on the enriched context produced by the previous step.
    """

    phase_name = "s01_intake"

    async def run_task(
        self, phase_input: Any, memory_ctx: List[Dict]
    ) -> TaskResult:
        from aether_os.core.projects import get_project_manager

        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Accumulate enriched context across all sub-phases.
        # We do NOT copy phase_input.input_data here — sub-phases mutate it
        # directly (p01 does `phase_input.input_data["entities"] = ...`).
        issues: List[str] = []

        # ── Steps 1-3: parallel sub-phases ───────────────────────────────────
        # These phases enrich the context independently:
        #   p00_research         → design_brief, build_profile
        #   p00b_data_archaeology → similar_past_runs (or migration scripts)
        #   p00c_architecture_planner → service_map (microservices only)
        parallel_phases = [
            "p00_research",
            "p00b_data_archaeology",
            "p00c_architecture_planner",
        ]
        parallel_results = await asyncio.gather(
            *[
                self._run_sub_phase(phase, phase_input, memory_ctx, pm)
                for phase in parallel_phases
            ],
            return_exceptions=True,
        )
        for phase_name, result in zip(parallel_phases, parallel_results):
            if isinstance(result, Exception):
                logger.warning(
                    "s01 sub-phase %s failed (non-critical): %s", phase_name, result
                )
                issues.append(f"{phase_name} failed: {result}")
            elif isinstance(result, TaskResult) and result.metadata:
                # Merge metadata keys that map to well-known context keys.
                # Each phase writes its own JSON file; here we bubble up
                # keys that downstream stages read from accumulated_context.
                _merge_metadata_into_context(phase_input.input_data, result.metadata)

        # ── Step 4: requirements extraction (CRITICAL) ────────────────────────
        # p01_intake_requirements writes: entities, api_endpoints, project_contract,
        # user_personas, user_roles, integration_flags, intent_verification.
        req_input = _clone_phase_input(phase_input)
        req_result = await self._run_sub_phase(
            "p01_intake_requirements", req_input, memory_ctx, pm
        )
        if isinstance(req_result, Exception):
            logger.error(
                "s01 CRITICAL: requirements extraction raised: %s", req_result
            )
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                success=False,
                issues=issues + [f"requirements extraction failed: {req_result}"],
                metadata=dict(phase_input.input_data),
            )
        if not req_result.success:
            logger.error("s01 CRITICAL: requirements extraction returned success=False")
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                success=False,
                issues=issues + ["requirements extraction returned success=False"],
                metadata=dict(phase_input.input_data),
            )
        # Propagate any data mutations req_input accumulated back to the main
        # phase_input so step 5 and the gate see the enriched context.
        phase_input.input_data.update(req_input.input_data)

        # ── Step 5: integration discovery (non-critical) ──────────────────────
        int_input = _clone_phase_input(phase_input)
        int_result = await self._run_sub_phase(
            "p01b_integration_discovery", int_input, memory_ctx, pm
        )
        if isinstance(int_result, Exception):
            logger.warning(
                "s01: integration discovery failed (non-critical): %s", int_result
            )
            issues.append(f"integration_discovery failed: {int_result}")
        elif isinstance(int_result, TaskResult) and int_result.metadata:
            _merge_metadata_into_context(phase_input.input_data, int_result.metadata)

        return TaskResult(
            output_path=str(output_dir),
            confidence=req_result.confidence,
            success=True,
            issues=issues,
            metadata=dict(phase_input.input_data),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _run_sub_phase(
        self, phase_name: str, phase_input: Any, memory_ctx: list, pm
    ) -> TaskResult:
        """Import and call a legacy phase's task_agent.run()."""
        try:
            mod = importlib.import_module(
                f"aether_os.phases.{phase_name}.task_agent"
            )
            output_dir = pm.get_output_dir(phase_input.project_id, phase_name)
            output_dir.mkdir(parents=True, exist_ok=True)
            return await mod.run(phase_input, memory_ctx, output_dir)
        except Exception as e:
            logger.warning("s01: sub-phase %s raised: %s", phase_name, e)
            raise

    async def validate_gate(
        self, result: TaskResult, phase_input: Any
    ) -> GateOutcome:
        if not result.success:
            return GateOutcome(
                passed=False,
                issues=["Requirements extraction failed — cannot continue"],
            )
        required_keys = ["entities", "project_contract"]
        missing = [
            k for k in required_keys if not phase_input.input_data.get(k)
        ]
        if missing:
            return GateOutcome(
                passed=False,
                issues=[f"Stage 1 missing required outputs: {missing}"],
            )
        return GateOutcome(passed=True, confidence=result.confidence)


# ── Module-level helpers (not part of the class) ─────────────────────────────


def _clone_phase_input(phase_input: Any) -> Any:
    """Shallow-copy phase_input with a deep-copy of input_data.

    Prevents a sub-phase from polluting the shared phase_input when we want
    to run it on an isolated copy and then selectively merge results back.
    """
    cloned = copy.copy(phase_input)
    cloned.input_data = copy.deepcopy(phase_input.input_data)
    return cloned


_METADATA_TO_CONTEXT_MAP: Dict[str, str] = {
    # p00_research metadata keys → accumulated_context keys
    "design_brief": "design_brief",
    "build_profile": "build_profile",
    "domain_knowledge": "domain_knowledge",
    "business_model": "business_model",
    # p00b_data_archaeology metadata keys
    "similar_past_runs": "similar_past_runs",
    "tables_mapped": "migration_tables_mapped",
    # p00c_architecture_planner metadata keys
    "service_count": "service_count",
    "message_bus": "message_bus",
    # p01b_integration_discovery metadata keys
    "integration_map": "integration_map",
    "integrations_count": "integrations_count",
}


def _merge_metadata_into_context(
    context: Dict[str, Any], metadata: Dict[str, Any]
) -> None:
    """Copy well-known metadata keys from a TaskResult into the context dict.

    Only overwrites when the metadata value is truthy so a sub-phase that
    returns an empty/skipped result does not erase a value set by an earlier one.
    """
    for meta_key, ctx_key in _METADATA_TO_CONTEXT_MAP.items():
        value = metadata.get(meta_key)
        if value is not None:
            context[ctx_key] = value
