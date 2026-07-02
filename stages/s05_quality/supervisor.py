"""
Stage 5: QUALITY GATE
=====================
PURPOSE: Multi-layer quality validation of all generated artifacts before they reach
         the testing stage. Catches security vulnerabilities, formal correctness violations,
         and per-dimension quality issues before any test runner runs.

INPUTS:
  - backend_output_path  : str  — FastAPI src/ path (from Stage 3)
  - frontend_output_path : str  — React src/ path (from Stage 4)
  - domain_ir            : dict — entity spec (for security invariant proofs)
  - permission_model     : dict — ABAC model (for Z3 auth proofs)

OUTPUTS:
  - compliance_score     : float — 0.0–1.0 overall compliance
  - compliance_pdf_path  : str  — path to generated PDF report
  - verification_report  : dict — Z3 SMT proof results
  - dimension_critique   : dict — per-artifact dimension scores
  - security_findings    : list — specific security issues found
  - quality_gate_passed  : bool — True if all dimensions pass threshold

SUB-STEPS:
  1. [PARALLEL] p06_review_security   — LLM security review + compliance PDF generation
  2. [PARALLEL] p06b_formal_verification — Z3 SMT proofs of auth/SQL/state-machine invariants
  3. [SEQUENTIAL] Dimension Critic    — 8-dimension static scoring on all .py files

CRITICAL: No — pipeline continues even if quality gate has findings (findings go to self-healing)
NOTE: Findings from this stage are fed into Stage 7 (SELF-HEALING) as repair targets.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.core.projects import get_project_manager
from stages.s05_quality.helpers import quality_gate_summary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class QualityGateSupervisor(PhaseBase):
    """
    Stage 5 supervisor: runs p06 + p06b in parallel, then dimension critic sequentially.

    Findings are surfaced as metadata even when quality gate does not pass;
    the pipeline is never blocked here — findings flow to Stage 7 (SELF-HEALING).
    """

    phase_name = "s05_quality"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        pm = get_project_manager()
        data: Dict[str, Any] = phase_input.input_data or {}
        issues: List[str] = []

        # ── Sub-steps 1 & 2: run p06 + p06b in parallel ─────────────────────
        logger.info("[s05] launching p06_review_security and p06b_formal_verification in parallel")
        p06_task = asyncio.create_task(
            self._run_sub_phase(
                phase_module="aether_os.phases.p06_review_security.task_agent",
                sub_phase_name="p06_review_security",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            )
        )
        p06b_task = asyncio.create_task(
            self._run_sub_phase(
                phase_module="aether_os.phases.p06b_formal_verification.task_agent",
                sub_phase_name="p06b_formal_verification",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            )
        )

        p06_result, p06b_result = await asyncio.gather(p06_task, p06b_task)

        if p06_result.issues:
            issues.extend(p06_result.issues)
        if p06b_result.issues:
            issues.extend(p06b_result.issues)

        # ── Sub-step 3: Dimension Critic (sequential, after parallel steps) ──
        merged_data: Dict[str, Any] = {**data}
        # Pull values that dimension critic needs from p06 result
        _merge_p06_into_data(p06_result, merged_data, phase_input)

        dimension_critique: Dict[str, Any] = {}
        try:
            from aether_os.core.quality.dimension_critic import critique_directory
            backend_path = merged_data.get("backend_output_path", "")
            if backend_path:
                reports = critique_directory(backend_path)
                failed = [r.artifact_path for r in reports if not r.passed]
                dimension_critique = {
                    "total": len(reports),
                    "failed": len(failed),
                    "failed_artifacts": failed,
                    "overall_score": (
                        sum(r.overall_score for r in reports) / max(len(reports), 1)
                    ),
                }
                logger.info(
                    "[s05] dimension critique: total=%d failed=%d score=%.2f",
                    dimension_critique["total"],
                    dimension_critique["failed"],
                    dimension_critique["overall_score"],
                )
            else:
                logger.info("[s05] dimension critic: backend_output_path empty — skipping")
        except Exception as e:
            logger.warning("Dimension critique failed (non-critical): %s", e)

        # ── Build Z3 verification report dict from p06b metadata ─────────────
        verification_report = _extract_verification_report(p06b_result)

        # ── Aggregate all results ─────────────────────────────────────────────
        all_results = [p06_result, p06b_result]
        gate_summary = quality_gate_summary(all_results)

        # Overlay dimension critique from sub-step 3 (runs after gather)
        if dimension_critique:
            gate_summary["dimension_critique"] = dimension_critique

        # Overlay verification_report from p06b
        if verification_report:
            gate_summary["verification_report"] = verification_report

        # Write consolidated quality report to the stage output dir
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "quality_gate_report.json"
        try:
            report_path.write_text(
                json.dumps(gate_summary, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("[s05] quality_gate_report.json write failed: %s", e)

        # Propagate findings back to phase_input.input_data for Stage 7
        phase_input.input_data["quality_gate_passed"] = gate_summary["quality_gate_passed"]
        phase_input.input_data["security_findings"] = gate_summary["security_findings"]
        phase_input.input_data["compliance_score"] = gate_summary["compliance_score"]
        phase_input.input_data["dimension_critique"] = gate_summary.get("dimension_critique", {})
        phase_input.input_data["verification_report"] = gate_summary.get("verification_report", {})
        if gate_summary.get("compliance_pdf_path"):
            phase_input.input_data["compliance_pdf_path"] = gate_summary["compliance_pdf_path"]

        logger.info(
            "[s05] quality gate complete: passed=%s compliance=%.2f findings=%d",
            gate_summary["quality_gate_passed"],
            gate_summary["compliance_score"],
            len(gate_summary["security_findings"]),
        )

        return TaskResult(
            output_path=str(report_path),
            confidence=_compute_confidence(gate_summary),
            metadata=gate_summary,
            issues=issues,
            # Always success=True: findings go to self-healing, not a pipeline block
            success=True,
        )

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """
        Stage 5 gate always passes — quality findings go to Stage 7 (SELF-HEALING).

        If the quality report itself could not be written (output_path empty or missing),
        we still pass but log a warning so operators can investigate.
        """
        if not result.output_path:
            logger.warning("[s05] quality gate: no output_path — report write may have failed")

        return GateOutcome(
            passed=True,
            issues=result.issues,
            confidence=result.confidence,
        )

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
                "[s05] %s: success=%s confidence=%.2f",
                sub_phase_name, result.success, result.confidence,
            )
            return result
        except Exception as e:
            logger.warning("[s05] %s failed (non-critical): %s", sub_phase_name, e)
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                metadata={"skipped": True, "error": str(e)},
                issues=[f"{sub_phase_name} raised: {e}"],
                success=False,
            )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _merge_p06_into_data(
    p06_result: TaskResult,
    merged_data: Dict[str, Any],
    phase_input: Any,
) -> None:
    """
    Pull compliance_pdf_path and compliance_score from p06 metadata
    and write them back to phase_input.input_data so downstream sub-steps
    (dimension critic, Stage 7) see them without a separate DB read.
    """
    meta = p06_result.metadata or {}

    pdf = meta.get("compliance_pdf_path") or ""
    if pdf:
        merged_data["compliance_pdf_path"] = pdf
        phase_input.input_data["compliance_pdf_path"] = pdf

    cs = meta.get("compliance_score")
    if cs is not None:
        merged_data["compliance_score"] = cs
        phase_input.input_data["compliance_score"] = cs


def _extract_verification_report(p06b_result: TaskResult) -> Dict[str, Any]:
    """
    Build a compact verification_report dict from p06b TaskResult metadata.
    Returns {} if the result carries no meaningful Z3 data.
    """
    meta = p06b_result.metadata or {}
    verdict = meta.get("overall_verdict", "")
    if not verdict:
        return {}

    return {
        "overall_verdict": verdict,
        "confidence_score": meta.get("confidence_score", meta.get("confidence", 0.0)),
        "z3_version": meta.get("z3_version", "unavailable"),
        "files_scanned": meta.get("files_scanned", 0),
        "invariants_verified_count": meta.get("invariants_verified_count", 0),
        "invariants_failed_count": meta.get("invariants_failed_count", 0),
        "invariants_unverifiable_count": meta.get("invariants_unverifiable_count", 0),
        "z3_solver_time_ms": meta.get("z3_solver_time_ms", 0),
        "report_path": meta.get("report_path", p06b_result.output_path),
    }


def _compute_confidence(gate_summary: Dict[str, Any]) -> float:
    """
    Derive an overall confidence score for Stage 5 from the gate summary.

    Weighted: 50% compliance score, 30% Z3 confidence, 20% dimension score.
    """
    compliance = gate_summary.get("compliance_score", 0.0)

    vr = gate_summary.get("verification_report") or {}
    z3_confidence = float(vr.get("confidence_score", 1.0))

    dc = gate_summary.get("dimension_critique") or {}
    dim_score = float(dc.get("overall_score", 1.0))

    return round(0.50 * compliance + 0.30 * z3_confidence + 0.20 * dim_score, 3)
