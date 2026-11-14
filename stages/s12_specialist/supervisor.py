"""
Stage 12: SPECIALIST OUTPUTS (conditional)
==========================================
PURPOSE: Optional platform-specific outputs beyond the core web app. Each output
         is generated only when the build profile requests it. All run in parallel.

INPUTS:
  - build_profile        : dict  — frontend_framework, build_type, architecture, deployment_target
  - backend_output_path  : str   — FastAPI src/ (for API client generation)
  - domain_ir            : dict  — for generating platform-specific data models

OUTPUTS (each is conditional):
  - mobile_output_path   : str  — Expo React Native app (if frontend_framework == "react_native")
  - desktop_output_path  : str  — Electron app (if frontend_framework == "electron")
  - cli_output_path      : str  — Click/Cobra CLI (if build_type == "cli")
  - serverless_path      : str  — Knative functions (if architecture == "serverless")
  - service_catalog_path : str  — Cloud console + catalog API (if build_type == "cloud_platform")
  - multiregion_path     : str  — Terraform multi-region (if deployment_target == "kubernetes"
                                   AND architecture in ["microservices","event_driven"])
  - specialist_outputs   : list — names of outputs actually generated

SUB-STEPS (all conditional, run in parallel if triggered):
  1. [COND] p05b_mobile         — React Native (Expo)
  2. [COND] p05c_desktop        — Electron + React
  3. [COND] p05d_cli            — Click or Cobra CLI
  4. [COND] p05e_serverless     — Knative function handlers
  5. [COND] p19_service_catalog — Cloud console React app + service catalog API
  6. [COND] p20_multiregion     — LitmusChaos + HPA + Global Accelerator Terraform

If no specialist outputs are triggered, immediately return TaskResult(status="passed")
with a note that no specialist builds were requested.

CRITICAL: No — all conditional, never blocks delivery
"""
from __future__ import annotations

import asyncio
import copy
import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult

logger = logging.getLogger(__name__)

# Architectures that qualify for multi-region output
_MULTIREGION_ARCHITECTURES = {"microservices", "event_driven"}

STAGE_CONTRACT = {
    "stage": "s12_specialist",
    "display_name": "Specialist Outputs",
    "critical": False,
    "conditional_substeps": [
        "p05b_mobile",
        "p05c_desktop",
        "p05d_cli",
        "p05e_serverless",
        "p19_service_catalog",
        "p20_multiregion",
    ],
    "inputs": ["build_profile", "backend_output_path", "domain_ir"],
    "outputs": [
        "mobile_output_path",
        "desktop_output_path",
        "cli_output_path",
        "serverless_path",
        "service_catalog_path",
        "multiregion_path",
        "specialist_outputs",
    ],
}


class SpecialistStageSupervisor(PhaseBase):
    """Consolidated supervisor for Stage 12 (Specialist Outputs).

    Inspects build_profile to determine which specialist phases to run,
    then fires all triggered phases in parallel via asyncio.gather.
    If no phases are triggered, returns immediately with status="passed".
    All failures are non-blocking.
    """

    phase_name = "s12_specialist"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        data: dict = phase_input.input_data or {}
        build_profile: dict = data.get("build_profile") or {}

        frontend_framework = build_profile.get("frontend_framework", "")
        build_type = build_profile.get("build_type", "")
        architecture = build_profile.get("architecture", "")
        deployment_target = build_profile.get("deployment_target", "")

        # ── Determine which specialist phases to trigger ───────────────────────
        triggered: List[Tuple[str, str]] = []  # (phase_name, output_context_key)

        if frontend_framework == "react_native":
            triggered.append(("p05b_mobile", "mobile_output_path"))

        if frontend_framework == "electron":
            triggered.append(("p05c_desktop", "desktop_output_path"))

        if build_type == "cli":
            triggered.append(("p05d_cli", "cli_output_path"))

        if architecture == "serverless":
            triggered.append(("p05e_serverless", "serverless_path"))

        if build_type == "cloud_platform":
            triggered.append(("p19_service_catalog", "service_catalog_path"))

        if (
            deployment_target == "kubernetes"
            and architecture in _MULTIREGION_ARCHITECTURES
        ):
            triggered.append(("p20_multiregion", "multiregion_path"))

        # s04 already generated these (same folder, same inputs): do not generate twice.
        _already = set(phase_input.input_data.get("specialist_phases_run") or [])
        triggered = [(p, k) for p, k in triggered if p not in _already]

        # ── Early exit: nothing to do ─────────────────────────────────────────
        if not triggered:
            logger.info(
                "s12_specialist: no specialist builds triggered "
                "(frontend_framework=%r, build_type=%r, architecture=%r, "
                "deployment_target=%r)",
                frontend_framework, build_type, architecture, deployment_target,
            )
            return TaskResult(
                output_path=str(output_dir),
                confidence=1.0,
                metadata={
                    "triggered": [],
                    "specialist_outputs": [],
                    "note": "No specialist builds were requested for this build profile.",
                },
                issues=[],
                success=True,
            )

        logger.info(
            "s12_specialist: triggering %d specialist phase(s): %s",
            len(triggered),
            [p for p, _ in triggered],
        )

        # ── Run all triggered phases in parallel ──────────────────────────────
        issues: List[str] = []
        tasks = [
            self._run_sub_phase(phase_name, phase_input, memory_ctx, pm)
            for phase_name, _ in triggered
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        succeeded: List[str] = []
        failed: List[str] = []

        for (phase_name, ctx_key), result in zip(triggered, raw_results):
            if isinstance(result, Exception):
                logger.warning(
                    "s12: %s raised exception (non-critical): %s", phase_name, result
                )
                issues.append(f"{phase_name} failed: {result}")
                failed.append(phase_name)
            elif isinstance(result, TaskResult):
                if result.metadata.get("skipped"):
                    # Phase ran its own internal skip guard — treat as non-issue
                    logger.info("s12: %s self-skipped: %s", phase_name, result.metadata.get("reason"))
                elif result.success:
                    succeeded.append(phase_name)
                    if result.output_path:
                        phase_input.input_data[ctx_key] = result.output_path
                else:
                    logger.warning("s12: %s returned success=False", phase_name)
                    issues.append(f"{phase_name} reported success=False")
                    failed.append(phase_name)
            else:
                logger.warning(
                    "s12: %s returned unexpected type %s", phase_name, type(result)
                )
                failed.append(phase_name)

        phase_input.input_data["specialist_outputs"] = succeeded
        confidence = len(succeeded) / max(len(triggered), 1)

        metadata = {
            "triggered": [p for p, _ in triggered],
            "succeeded": succeeded,
            "failed": failed,
            "specialist_outputs": succeeded,
            "build_profile_summary": {
                "frontend_framework": frontend_framework,
                "build_type": build_type,
                "architecture": architecture,
                "deployment_target": deployment_target,
            },
        }

        logger.info(
            "s12_specialist: complete — %d/%d specialist phases succeeded",
            len(succeeded), len(triggered),
        )

        return TaskResult(
            output_path=str(output_dir),
            confidence=confidence,
            metadata=metadata,
            issues=issues,
            success=True,  # Never blocks delivery
        )

    async def _run_sub_phase(
        self, phase_name: str, phase_input: Any, memory_ctx: list, pm: Any
    ) -> TaskResult:
        """Import and call a legacy phase's task_agent.run() in its own output dir."""
        mod = importlib.import_module(f"aether_os.phases.{phase_name}.task_agent")
        sub_input = copy.copy(phase_input)
        sub_input.input_data = copy.deepcopy(phase_input.input_data)
        out_dir: Path = pm.get_output_dir(phase_input.project_id, phase_name)
        out_dir.mkdir(parents=True, exist_ok=True)
        return await mod.run(sub_input, memory_ctx, out_dir)

    async def validate_gate(
        self, result: TaskResult, phase_input: Any
    ) -> GateOutcome:
        # Specialist stage is non-critical: gate always passes.
        if result.issues:
            logger.warning(
                "s12_specialist gate: %d issue(s) noted (non-blocking): %s",
                len(result.issues), result.issues,
            )
        return GateOutcome(
            passed=True,
            issues=result.issues,
            confidence=result.confidence,
        )
