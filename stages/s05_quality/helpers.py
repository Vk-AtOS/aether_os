"""
Stage 5: QUALITY GATE — shared utilities.

quality_gate_summary() aggregates sub-step results from p06 and p06b
into a single summary dict consumed by the stage supervisor and stored
as stage output metadata.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

# Minimum compliance score to consider the quality gate passed.
# Findings are always forwarded to Stage 7 (SELF-HEALING); this threshold
# only gates the summary flag, not the pipeline continuation.
COMPLIANCE_PASS_THRESHOLD = 0.50


def quality_gate_summary(results: List[TaskResult]) -> Dict[str, Any]:
    """
    Aggregate a list of TaskResult objects (from p06, p06b, dimension critic)
    into a unified quality gate summary dict.

    Args:
        results: TaskResult instances from each quality sub-step.
                 May include None entries (tolerated and skipped).

    Returns:
        A flat dict with the following keys:
          compliance_score      float  0.0–1.0 from p06 compliance sub-task
          compliance_pdf_path   str    path to compliance PDF (may be "")
          verification_report   dict   Z3 report payload from p06b
          dimension_critique    dict   per-dimension scores from critic
          security_findings     list   bandit / LLM findings
          quality_gate_passed   bool   True if all thresholds met
          sub_step_count        int    number of sub-steps that ran
          sub_step_passed       int    number that succeeded
    """
    summary: Dict[str, Any] = {
        "compliance_score": 0.0,
        "compliance_pdf_path": "",
        "verification_report": {},
        "dimension_critique": {},
        "security_findings": [],
        "quality_gate_passed": False,
        "sub_step_count": 0,
        "sub_step_passed": 0,
    }

    for result in results:
        if result is None or not isinstance(result, TaskResult):
            continue

        summary["sub_step_count"] += 1
        if result.success:
            summary["sub_step_passed"] += 1

        meta: Dict[str, Any] = result.metadata or {}

        # Pull compliance score — written by p06 compliance sub-task
        cs = meta.get("compliance_score")
        if cs is not None:
            try:
                summary["compliance_score"] = float(cs) / 100 if float(cs) > 1 else float(cs)
            except (TypeError, ValueError) as e:
                logger.warning("[s05/helpers] compliance_score parse error: %s", e)

        # Pull compliance PDF path
        pdf = meta.get("compliance_pdf_path") or meta.get("output_path", "")
        if pdf and pdf.endswith(".pdf") and not summary["compliance_pdf_path"]:
            summary["compliance_pdf_path"] = pdf

        # Pull Z3 formal verification report
        vr = meta.get("verification_report") or meta.get("phases", {}).get("formal_verification")
        if vr and isinstance(vr, dict) and not summary["verification_report"]:
            summary["verification_report"] = vr

        # Pull bandit / LLM security findings
        findings = meta.get("security_findings") or []
        if not findings:
            # p06 stores them nested inside phases.static_analysis.metadata.findings
            static = meta.get("phases", {}).get("static_analysis", {})
            findings = (static.get("metadata") or {}).get("findings", [])
        if findings:
            summary["security_findings"].extend(findings)

        # Pull dimension critique
        dc = meta.get("dimension_critique")
        if dc and isinstance(dc, dict) and not summary["dimension_critique"]:
            summary["dimension_critique"] = dc

    # Determine overall gate pass
    cs_ok = summary["compliance_score"] >= COMPLIANCE_PASS_THRESHOLD
    dc = summary["dimension_critique"]
    dc_ok = dc.get("overall_score", 1.0) >= 0.50 if dc else True

    summary["quality_gate_passed"] = cs_ok and dc_ok

    logger.info(
        "[s05/helpers] quality_gate_summary: compliance=%.2f dc_score=%.2f passed=%s",
        summary["compliance_score"],
        dc.get("overall_score", 1.0) if dc else 1.0,
        summary["quality_gate_passed"],
    )
    return summary
