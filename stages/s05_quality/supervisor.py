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

CRITICAL: No for ordinary findings (they go to self-healing); unresolved High/Critical security
         findings and a Z3 FAIL fail the gate, which ends the run.
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
from aether_os.phases.utils import get_domain_ir
from aether_os.core.projects import get_project_manager
from aether_os.core.quality.axe_live import live_axe_violations
from aether_os.core.quality.frontend_tools import collect as collect_frontend_tools
from aether_os.stages.s05_quality.helpers import quality_gate_summary
from aether_os.stages.s05_quality.gate_functions import blocking_findings, detect_critical_issues, regenerate_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class QualityGateSupervisor(PhaseBase):
    """
    Stage 5 supervisor: runs p06 + p06b in parallel, then dimension critic sequentially.

    Findings are surfaced as metadata; only unresolved High/Critical security findings and a
    Z3 FAIL block the run (validate_gate). The rest flow to Stage 7 (SELF-HEALING).
    """

    phase_name = "s05_quality"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        pm = get_project_manager()
        data: Dict[str, Any] = phase_input.input_data or {}
        issues: List[str] = []

        # Resolve run_id for stage feedback tracking
        run_id = str(getattr(phase_input, "project_id", "") or data.get("run_id", "unknown"))

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
        critic_reports: list = []
        backend_path = merged_data.get("backend_output_path", "")
        try:
            from aether_os.core.quality.dimension_critic import critique_directory
            if backend_path:
                critic_reports = critique_directory(backend_path, root=merged_data.get("project_dir"))
                failed = [r.artifact_path for r in critic_reports if not r.passed]
                dimension_critique = {
                    "total": len(critic_reports),
                    "failed": len(failed),
                    "failed_artifacts": failed,
                    "overall_score": (
                        sum(r.overall_score for r in critic_reports) / max(len(critic_reports), 1)
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
            # Frontend: regex scorers plus the real tsc/eslint results (and axe-core's count when the
            # a11y phase already produced one); tools that did not run are reported, never assumed clean.
            fe_path = merged_data.get("frontend_output_path", "")
            if fe_path and Path(fe_path).is_dir():
                a11y = merged_data.get("accessibility_results") or {}
                # The a11y stage's own count when it ran; else axe-core now, in the browser sandbox (when a
                # build and the sandbox exist); else None plus a note: not run is never "zero violations".
                axe_count = a11y.get("violations") if a11y.get("ran_axe") else None
                axe_note = ""
                if axe_count is None:
                    axe_count, axe_note = await live_axe_violations(Path(fe_path))
                tools = await asyncio.to_thread(collect_frontend_tools, fe_path, axe_count)
                if axe_note:
                    tools.notes.append(axe_note)
                fe_reports = critique_directory(fe_path, tools=tools, root=merged_data.get("project_dir"))
                critic_reports += fe_reports
                dimension_critique["frontend"] = {
                    "files": len(fe_reports), "failed": sum(1 for r in fe_reports if not r.passed),
                    "tsc_ran": tools.tsc_ran, "eslint_ran": tools.eslint_ran,
                    "axe_violations": tools.axe_violations, "notes": tools.notes,
                }
        except Exception as e:
            logger.warning("Dimension critique failed (non-critical): %s", e)

        # ── Record stage output for feedback tracker ─────────────────────────
        try:
            from aether_os.core.stage_feedback import record_stage_output
            quality_scores = {
                "compliance_score": merged_data.get("compliance_score", 0.0),
                "dimension_overall": dimension_critique.get("overall_score", 0.0),
            }
            output_files = [r.artifact_path for r in critic_reports]
            record_stage_output("s05_quality", run_id, output_files, quality_scores)
        except Exception as e:
            logger.warning("[s05] stage_feedback record_stage_output failed (non-critical): %s", e)

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

        # ── Critical issue detection + per-file regeneration ─────────────────
        security_findings = gate_summary.get("security_findings", [])
        backend_src = Path(backend_path) if backend_path else None
        # Resolve LLM for regeneration
        llm = getattr(phase_input, "llm", None) or data.get("llm")
        domain_ir = get_domain_ir(data)
        project_name = data.get("project_name", run_id)

        output_data: Dict[str, Any] = gate_summary
        critical_issues = detect_critical_issues(backend_src, security_findings, dimension_critique)
        resolved = 0
        unresolved: list = []  # issues no regeneration attempt fixed (the old code assumed the first N were)

        if critical_issues and llm is not None:
            for issue in critical_issues:
                fixed = False
                for attempt in range(2):
                    success = await regenerate_file(
                        issue["file"], issue, domain_ir, project_name, llm
                    )
                    if success:
                        resolved += 1
                        fixed = True
                        # Record fix in stage feedback
                        try:
                            from aether_os.core.stage_feedback import record_stage_fix
                            record_stage_fix(
                                "s05_quality", run_id,
                                issue["description"], issue["issue_type"],
                            )
                        except Exception as e:
                            logger.warning("[s05] stage_feedback record_stage_fix failed: %s", e)
                        break
                    logger.warning(
                        "[s05] attempt %d failed to fix %s in %s",
                        attempt + 1, issue["issue_type"],
                        issue["file"].name if hasattr(issue["file"], "name") else issue["file"],
                    )
                if not fixed:
                    unresolved.append(issue)
        elif critical_issues and llm is None:
            unresolved = list(critical_issues)
            logger.warning(
                "[s05] %d critical issue(s) found but no LLM available for regeneration",
                len(critical_issues),
            )

        remaining = len(unresolved)
        if remaining > 0:
            # Escalate to healing stage with priority flag
            output_data["healing_priority"] = "critical"
            output_data["unresolved_critical_issues"] = [
                i["description"] for i in unresolved
            ]
            output_data["blocking_findings"] = blocking_findings(unresolved)
            logger.warning(
                "[s05] %d critical issue(s) remain after regeneration — escalated to healing",
                remaining,
            )

        if (p06_result.metadata or {}).get("skipped"):
            # Fail closed: no security review means nothing was checked, not that nothing was found.
            output_data["blocking_findings"] = output_data.get("blocking_findings", []) + [
                "security review could not run: " + str(p06_result.metadata.get("error", "unknown error"))
            ]

        logger.info(
            "[s05] quality gate: %d critical issues found, %d resolved, %d remaining",
            len(critical_issues), resolved, remaining,
        )

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
        if gate_summary.get("healing_priority"):
            phase_input.input_data["healing_priority"] = gate_summary["healing_priority"]
        if gate_summary.get("unresolved_critical_issues"):
            phase_input.input_data["unresolved_critical_issues"] = gate_summary[
                "unresolved_critical_issues"
            ]

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
            success=True,  # the gate (validate_gate) decides blocking, not this flag
        )

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """Fail closed: a High/Critical security finding that regeneration could not fix, or a
        Z3 FAIL verdict, stops delivery (the base class escalates and the run ends at this stage).
        Every other finding still flows on to Stage 7 (SELF-HEALING) as a repair target.
        """
        if not result.output_path:
            logger.warning("[s05] quality gate: no output_path — report write may have failed")

        meta = result.metadata or {}
        blockers = list(meta.get("blocking_findings") or [])
        if (meta.get("verification_report") or {}).get("overall_verdict") == "FAIL":
            blockers.append("Z3 formal verification verdict FAIL")
        if blockers:
            return GateOutcome(
                passed=False, confidence=0.0,
                issues=[f"BLOCKED: {b}" for b in blockers] + list(result.issues or []),
            )
        return GateOutcome(passed=True, issues=result.issues, confidence=result.confidence)

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
