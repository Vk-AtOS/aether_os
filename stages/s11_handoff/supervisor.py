"""
Stage 11: HANDOFF
=================
PURPOSE: Produce the complete delivery package for the client. Full documentation
         suite, a client-facing review portal, Postman collection, deployment
         runbook, and a ZIP archive of the entire generated project.

INPUTS:
  - backend_output_path    : str   — FastAPI src/
  - frontend_output_path   : str   — React src/
  - project_name           : str
  - domain                 : str
  - healing_passed         : bool
  - test_results           : dict
  - compliance_score       : float
  - dimension_critique     : dict
  - governor_report        : dict

OUTPUTS:
  - readme_path              : str — README.md
  - api_reference_path       : str — API reference markdown
  - architecture_doc_path    : str — Architecture decision record
  - deployment_guide_path    : str — Step-by-step deployment guide
  - postman_collection_path  : str
  - client_portal_path       : str — Client review portal HTML
  - export_manifest_path     : str — manifest of the clean export (the download / GitHub push build it on demand)
  - quality_report_path      : str — JSON quality summary

SUB-STEPS:
  1. [SEQUENTIAL] p10_docs_delivery — README + API ref + architecture doc + deployment guide
  2. [PARALLEL]   p14_client_portal — Client review portal HTML + ticket API
  3. [PARALLEL]   p15_handoff       — Postman collection + runbook + checklist + ZIP

CRITICAL: No — handoff failures don't block the run from being marked complete
"""
from __future__ import annotations

import asyncio
import copy
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.core.project_export import ExportError, export_files
from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.phases.failure_reason import failure_issues

logger = logging.getLogger(__name__)

STAGE_CONTRACT = {
    "stage": "s11_handoff",
    "display_name": "Handoff",
    "critical": False,
    "sequential_substeps": ["p10_docs_delivery"],
    "parallel_substeps": ["p14_client_portal", "p15_handoff"],
    "inputs": [
        "backend_output_path",
        "frontend_output_path",
        "project_name",
        "domain",
        "healing_passed",
        "test_results",
        "compliance_score",
        "dimension_critique",
        "governor_report",
    ],
    "outputs": [
        "readme_path",
        "api_reference_path",
        "architecture_doc_path",
        "deployment_guide_path",
        "postman_collection_path",
        "client_portal_path",
        "export_manifest_path",
        "quality_report_path",
    ],
}


class HandoffStageSupervisor(PhaseBase):
    """Consolidated supervisor for Stage 11 (Handoff).

    Runs p10_docs_delivery sequentially first (it enriches the context with
    doc paths that p14 and p15 may reference), then runs p14_client_portal
    and p15_handoff in parallel via asyncio.gather.

    All failures are non-blocking — the run is marked complete regardless.
    """

    phase_name = "s11_handoff"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        issues: List[str] = []
        results: Dict[str, TaskResult] = {}

        # ── Step 1: Documentation (sequential — enriches context for steps 2+) ──
        docs_result = await self._run_sub_phase_safe(
            "p10_docs_delivery", phase_input, memory_ctx, pm, issues
        )
        if docs_result is not None:
            results["p10_docs_delivery"] = docs_result
            # Propagate doc paths into context so downstream phases can reference them
            if docs_result.metadata:
                self._merge_doc_paths(phase_input.input_data, docs_result)

        # ── Steps 2+3: Portal + Handoff package (parallel) ────────────────────
        portal_task = self._run_sub_phase_safe(
            "p14_client_portal", phase_input, memory_ctx, pm, issues
        )
        handoff_task = self._run_sub_phase_safe(
            "p15_handoff", phase_input, memory_ctx, pm, issues
        )
        portal_result, handoff_result = await asyncio.gather(
            portal_task, handoff_task, return_exceptions=False
        )

        if portal_result is not None:
            results["p14_client_portal"] = portal_result
        if handoff_result is not None:
            results["p15_handoff"] = handoff_result

        # ── Verify the run exports cleanly (the download / GitHub push build the real artifact) ──
        manifest_path = await self._check_export(phase_input, output_dir, issues)
        if manifest_path:
            phase_input.input_data["export_manifest_path"] = str(manifest_path)

        # ── Write quality report ──────────────────────────────────────────────
        quality_report_path = self._write_quality_report(
            phase_input.input_data, output_dir
        )
        if quality_report_path:
            phase_input.input_data["quality_report_path"] = str(quality_report_path)

        # ── Propagate output paths from sub-phase results ─────────────────────
        self._propagate_portal_path(phase_input.input_data, portal_result)
        self._propagate_handoff_paths(phase_input.input_data, handoff_result)

        succeeded = [name for name, r in results.items() if r.success]
        failed = [name for name, r in results.items() if not r.success]
        confidence = len(succeeded) / max(len(results), 1) if results else 0.5

        metadata = {
            "succeeded": succeeded,
            "failed": failed,
            "export_manifest_path": str(manifest_path) if manifest_path else None,
            "quality_report_path": str(quality_report_path) if quality_report_path else None,
            "docs_written": docs_result.metadata.get("files_written", 0) if docs_result else 0,
        }

        logger.info(
            "s11_handoff: complete — %d/%d sub-phases succeeded",
            len(succeeded), len(results),
        )

        return TaskResult(
            output_path=str(output_dir),
            confidence=confidence,
            metadata=metadata,
            issues=issues,
            success=True,  # Never blocks the run being marked complete
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _run_sub_phase_safe(
        self,
        phase_name: str,
        phase_input: Any,
        memory_ctx: list,
        pm: Any,
        issues: List[str],
    ) -> TaskResult | None:
        """Run a sub-phase; catch all exceptions and append to issues list."""
        try:
            mod = importlib.import_module(f"aether_os.phases.{phase_name}.task_agent")
            sub_input = copy.copy(phase_input)
            sub_input.input_data = copy.deepcopy(phase_input.input_data)
            out_dir: Path = pm.get_output_dir(phase_input.project_id, phase_name)
            out_dir.mkdir(parents=True, exist_ok=True)
            result = await mod.run(sub_input, memory_ctx, out_dir)
            if not result.success:
                logger.warning("s11: %s returned success=False", phase_name)
                issues.extend(failure_issues("s11_handoff", phase_name, result))
            return result
        except Exception as e:
            logger.warning("s11: %s failed (non-critical): %s", phase_name, e)
            issues.append(f"{phase_name} failed: {e}")
            return None

    def _merge_doc_paths(self, context: dict, docs_result: TaskResult) -> None:
        """Pull key doc file paths from p10's metadata into the shared context."""
        meta = docs_result.metadata or {}
        # p10 writes a consolidated.json; propagate known path keys
        for key in ("readme_path", "api_ref_path", "docs_dir"):
            if meta.get(key):
                context[key] = meta[key]
        # Also try to infer paths from p10's consolidated output
        out = docs_result.output_path or ""
        if out and not context.get("readme_path"):
            candidate = Path(out).parent / "docs" / "README.md"
            if candidate.exists():
                context["readme_path"] = str(candidate)

    def _propagate_portal_path(self, context: dict, portal_result: TaskResult | None) -> None:
        """Write client_portal_path into context from p14 result."""
        if portal_result and portal_result.output_path:
            context["client_portal_path"] = portal_result.output_path

    def _propagate_handoff_paths(self, context: dict, handoff_result: TaskResult | None) -> None:
        """Write Postman + runbook paths into context from p15 result."""
        if not handoff_result:
            return
        out_dir = Path(handoff_result.output_path) if handoff_result.output_path else None
        if out_dir and out_dir.exists():
            postman = out_dir / "postman" / "collection.json"
            if postman.exists():
                context["postman_collection_path"] = str(postman)
            runbook = out_dir / "docs" / "RUNBOOK.md"
            if runbook.exists():
                context["deployment_guide_path"] = str(runbook)

    async def _check_export(self, phase_input: Any, output_dir: Path, issues: List[str]) -> Path | None:
        """Prove the run can be exported and record the manifest (KAN-270).

        The deliverable is the clean export the download endpoint and the GitHub push build on demand
        (core/project_export). This stage used to zip backend/frontend/docs itself: 87 MB with node_modules, a .env and
        a private key, and nothing served it. It now only runs the same export (including its secret scan) so a
        run that cannot be exported is flagged here, and writes the manifest next to the quality report.
        """
        try:
            data = phase_input.input_data or {}
            ws = Path(data.get("project_dir") or "")
            if not ws.is_dir():
                from aether_os.core.projects import get_project_manager
                ws = get_project_manager().get_project_dir(phase_input.project_id)
            _, manifest = await asyncio.to_thread(export_files, ws, str(data.get("project_name") or "app"))
            path = output_dir / "export_manifest.json"
            path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            logger.info("s11: clean export verified, %d files", manifest["file_count"])
            return path
        except ExportError as e:
            logger.warning("s11: the run cannot be exported: %s", e)
            issues.append(f"Export check failed: {e}")
            return None
        except Exception as e:
            logger.warning("s11: export check crashed (non-critical): %s", e)
            issues.append(f"Export check crashed: {e}")
            return None

    def _write_quality_report(self, context: dict, output_dir: Path) -> Path | None:
        """Write a JSON quality summary from accumulated context keys."""
        try:
            report = {
                "project_name": context.get("project_name", ""),
                "domain": context.get("domain", ""),
                "healing_passed": context.get("healing_passed", None),
                "test_results": context.get("test_results", {}),
                "compliance_score": context.get("compliance_score", None),
                "dimension_critique": context.get("dimension_critique", {}),
                "governor_report": context.get("governor_report", {}),
                "phase_confidence": context.get("phase_confidence", {}),
                "low_confidence_phases": context.get("low_confidence_phases", []),
            }
            report_path = output_dir / "quality_report.json"
            report_path.write_text(
                json.dumps(report, indent=2, default=str), encoding="utf-8"
            )
            logger.info("s11: quality_report.json written")
            return report_path
        except Exception as e:
            logger.warning("s11: quality_report write failed (non-critical): %s", e)
            return None

    async def validate_gate(
        self, result: TaskResult, phase_input: Any
    ) -> GateOutcome:
        # Handoff stage is non-critical: gate always passes.
        if result.issues:
            logger.warning(
                "s11_handoff gate: %d issue(s) noted (non-blocking): %s",
                len(result.issues), result.issues,
            )
        return GateOutcome(
            passed=True,
            issues=result.issues,
            confidence=result.confidence,
        )
