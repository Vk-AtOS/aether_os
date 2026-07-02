"""
Stage 4: FRONTEND
=================
PURPOSE: Generate a complete React/Vite/TanStack frontend from the Domain IR.
         Produces all UI source: entity CRUD views, auth pages, sidebar navigation,
         dark mode, real-time SSE hooks, and platform-specific variants.

INPUTS:
  - domain_ir           : dict  — entity definitions (from Stage 2)
  - design_tokens       : dict  — colors, fonts, spacing (from Stage 3)
  - backend_output_path : str   — path to FastAPI backend src/ (from Stage 3)
  - user_personas       : list  — target users (from Stage 1)
  - build_profile       : dict  — frontend_framework, build_type flags
  - api_endpoints       : list  — routes to wire in frontend (from Stage 1)

OUTPUTS:
  - frontend_output_path : str   — path to generated React/Vite frontend
  - frontend_framework   : str   — "react" | "react_native" | "electron" | "cli" | "serverless"
  - component_count      : int   — number of React components generated

SUB-STEPS:
  1. [SEQUENTIAL] p05_frontend         — main React/Vite/TanStack output (always runs)
  2. [CONDITIONAL] p05b_mobile        — Expo React Native (only if build_profile.frontend_framework == "react_native")
  3. [CONDITIONAL] p05c_desktop       — Electron (only if frontend_framework == "electron")
  4. [CONDITIONAL] p05d_cli           — Click/Cobra CLI (only if build_type == "cli")
  5. [CONDITIONAL] p05e_serverless    — Knative functions (only if architecture == "serverless")

NOTE: p05_frontend generates 3700+ lines of template code. The task_agent is pre-approved
      at this size. Do NOT attempt to refactor it.

GATE: passes if frontend_output_path exists and contains at least an index.html or App.tsx
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.core.projects import get_project_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Condition checks for platform-specific sub-steps
# ---------------------------------------------------------------------------

def _should_run_mobile(build_profile: Dict[str, Any]) -> bool:
    """Trigger: build_profile.frontend_framework == 'react_native'."""
    return build_profile.get("frontend_framework", "react") == "react_native"


def _should_run_desktop(build_profile: Dict[str, Any]) -> bool:
    """Trigger: build_profile.frontend_framework == 'electron'."""
    return build_profile.get("frontend_framework", "react") == "electron"


def _should_run_cli(build_profile: Dict[str, Any]) -> bool:
    """Trigger: build_profile.build_type == 'cli'."""
    return build_profile.get("build_type", "web_app") == "cli"


def _should_run_serverless(build_profile: Dict[str, Any]) -> bool:
    """Trigger: build_profile.architecture in ('serverless', 'event_driven')."""
    return build_profile.get("architecture", "monolith") in ("serverless", "event_driven")


# ---------------------------------------------------------------------------
# Result merging
# ---------------------------------------------------------------------------

def _merge_metadata(results: List[TaskResult]) -> Dict[str, Any]:
    """Merge metadata from all TaskResult objects; later non-None values win."""
    merged: Dict[str, Any] = {}
    for result in results:
        if not isinstance(result, TaskResult):
            continue
        for key, value in (result.metadata or {}).items():
            if value is not None:
                merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class FrontendStageSupervisor(PhaseBase):
    """
    Stage 4 supervisor: orchestrates p05_frontend plus conditional platform outputs.

    Sub-step 1 (p05_frontend) always runs.
    Sub-steps 2-5 are conditionally dispatched based on build_profile flags.
    """

    phase_name = "s04_frontend"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        pm = get_project_manager()
        data: Dict[str, Any] = phase_input.input_data or {}
        build_profile: Dict[str, Any] = data.get("build_profile") or {}
        all_results: List[TaskResult] = []
        issues: List[str] = []

        # ── Sub-step 1: p05_frontend (always runs) ────────────────────────────
        p05_result = await self._run_sub_phase(
            phase_module="aether_os.phases.p05_frontend.task_agent",
            sub_phase_name="p05_frontend",
            phase_input=phase_input,
            memory_ctx=memory_ctx,
            pm=pm,
        )
        all_results.append(p05_result)
        if p05_result.issues:
            issues.extend(p05_result.issues)

        # Propagate frontend output path so conditionals can reference it
        frontend_output_path = p05_result.metadata.get("frontend_output_path", "")
        if not frontend_output_path and p05_result.output_path:
            frontend_output_path = p05_result.output_path
        if frontend_output_path:
            phase_input.input_data["frontend_output_path"] = frontend_output_path

        # ── Sub-step 2: p05b_mobile (react_native) ────────────────────────────
        if _should_run_mobile(build_profile):
            logger.info("[s04] build_profile.frontend_framework=react_native — running p05b_mobile")
            mobile_result = await self._run_sub_phase(
                phase_module="aether_os.phases.p05b_mobile.task_agent",
                sub_phase_name="p05b_mobile",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            )
            all_results.append(mobile_result)
            if mobile_result.issues:
                issues.extend(mobile_result.issues)
        else:
            logger.debug(
                "[s04] p05b_mobile skipped (frontend_framework=%s)",
                build_profile.get("frontend_framework", "react"),
            )

        # ── Sub-step 3: p05c_desktop (electron) ───────────────────────────────
        if _should_run_desktop(build_profile):
            logger.info("[s04] build_profile.frontend_framework=electron — running p05c_desktop")
            desktop_result = await self._run_sub_phase(
                phase_module="aether_os.phases.p05c_desktop.task_agent",
                sub_phase_name="p05c_desktop",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            )
            all_results.append(desktop_result)
            if desktop_result.issues:
                issues.extend(desktop_result.issues)
        else:
            logger.debug(
                "[s04] p05c_desktop skipped (frontend_framework=%s)",
                build_profile.get("frontend_framework", "react"),
            )

        # ── Sub-step 4: p05d_cli (cli build_type) ────────────────────────────
        if _should_run_cli(build_profile):
            logger.info("[s04] build_profile.build_type=cli — running p05d_cli")
            cli_result = await self._run_sub_phase(
                phase_module="aether_os.phases.p05d_cli.task_agent",
                sub_phase_name="p05d_cli",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            )
            all_results.append(cli_result)
            if cli_result.issues:
                issues.extend(cli_result.issues)
        else:
            logger.debug(
                "[s04] p05d_cli skipped (build_type=%s)",
                build_profile.get("build_type", "web_app"),
            )

        # ── Sub-step 5: p05e_serverless (serverless/event_driven arch) ────────
        if _should_run_serverless(build_profile):
            logger.info(
                "[s04] build_profile.architecture=%s — running p05e_serverless",
                build_profile.get("architecture"),
            )
            serverless_result = await self._run_sub_phase(
                phase_module="aether_os.phases.p05e_serverless.task_agent",
                sub_phase_name="p05e_serverless",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            )
            all_results.append(serverless_result)
            if serverless_result.issues:
                issues.extend(serverless_result.issues)
        else:
            logger.debug(
                "[s04] p05e_serverless skipped (architecture=%s)",
                build_profile.get("architecture", "monolith"),
            )

        # ── Merge metadata from all sub-steps ─────────────────────────────────
        merged_meta = _merge_metadata(all_results)

        # Determine the authoritative framework label for downstream stages
        framework_label = _resolve_framework_label(build_profile)
        merged_meta["frontend_framework"] = framework_label

        # Ensure frontend_output_path is in merged metadata
        if frontend_output_path:
            merged_meta["frontend_output_path"] = frontend_output_path

        # component_count: prefer p05 metadata value, fallback to 0
        merged_meta.setdefault("component_count", p05_result.metadata.get("component_count", 0))

        any_critical_fail = any(
            not r.success and not r.metadata.get("skipped")
            for r in all_results
        )

        logger.info(
            "[s04] completed: framework=%s output=%s components=%d sub_steps=%d",
            framework_label,
            frontend_output_path,
            merged_meta.get("component_count", 0),
            len(all_results),
        )

        return TaskResult(
            output_path=frontend_output_path or p05_result.output_path,
            confidence=p05_result.confidence,
            metadata=merged_meta,
            issues=issues,
            success=not any_critical_fail,
        )

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """
        Gate: passes if frontend_output_path exists and contains index.html or App.tsx.
        """
        if result.status == "failed" if hasattr(result, "status") else not result.success:
            return GateOutcome(
                passed=False,
                issues=["s04_frontend: sub-step reported failure — check p05 logs"],
            )

        frontend_path = result.metadata.get("frontend_output_path", "") or result.output_path
        if not frontend_path:
            return GateOutcome(
                passed=False,
                issues=["s04_frontend: frontend_output_path is empty — no frontend was generated"],
            )

        fp = Path(frontend_path)
        if not fp.exists():
            return GateOutcome(
                passed=False,
                issues=[f"s04_frontend: frontend path does not exist on disk: {frontend_path}"],
            )

        # Check for at least one of the sentinel files that marks a real frontend
        sentinel_found = any(
            (fp / sentinel).exists() or any(fp.rglob(sentinel))
            for sentinel in ("index.html", "App.tsx", "App.jsx")
        )
        if not sentinel_found:
            return GateOutcome(
                passed=False,
                issues=[
                    f"s04_frontend: {frontend_path} exists but contains no index.html or App.tsx "
                    "— frontend generation may have partially failed"
                ],
            )

        return GateOutcome(passed=True, confidence=result.confidence)

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _run_sub_phase(
        self,
        phase_module: str,
        sub_phase_name: str,
        phase_input: Any,
        memory_ctx: List[Dict],
        pm: Any,
    ) -> TaskResult:
        """Import a phase task_agent module by dotted name and call its run()."""
        output_dir = pm.get_output_dir(phase_input.project_id, sub_phase_name)
        try:
            mod = importlib.import_module(phase_module)
            result: TaskResult = await mod.run(phase_input, memory_ctx, output_dir)
            logger.info(
                "[s04] %s: success=%s confidence=%.2f",
                sub_phase_name, result.success, result.confidence,
            )
            return result
        except Exception as e:
            logger.warning("[s04] %s failed (non-critical): %s", sub_phase_name, e)
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                metadata={"skipped": True, "error": str(e)},
                issues=[f"{sub_phase_name} raised: {e}"],
                success=False,
            )


# ---------------------------------------------------------------------------
# Framework label resolution
# ---------------------------------------------------------------------------

def _resolve_framework_label(build_profile: Dict[str, Any]) -> str:
    """
    Determine the canonical frontend_framework string to surface in stage output.

    Priority: explicit frontend_framework > build_type=cli > architecture=serverless > react
    """
    fw = build_profile.get("frontend_framework", "react")
    if fw and fw not in ("react", "none", ""):
        return fw
    build_type = build_profile.get("build_type", "web_app")
    if build_type == "cli":
        return "cli"
    arch = build_profile.get("architecture", "monolith")
    if arch in ("serverless", "event_driven"):
        return "serverless"
    return "react"
