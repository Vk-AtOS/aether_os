"""
P02b Task Agent — Domain IR extraction orchestration.

Runs after p02 (architecture). Produces domain_ir.json which all downstream
phases (p04a, p05) consume for deterministic code generation.

Extraction logic (prompts, helpers, IR assembly) lives in ir_extractor.py.
This file contains only the run() entry point and gate logic.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from aether_os.core.llm.client import get_llm_client
from aether_os.core.domain_ir import IRClarifyingQuestion
from aether_os.phases.p02b_domain_ir.ir_extractor import (
    _seed_entities,
    _build_ir_from_passes,
    run_4pass_extraction,
    build_stub_ir,
)

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(phase_input: Any, memory_ctx: list, output_dir: Path) -> TaskResult:
    """Extract Domain IR from requirements. Reads raw_input; writes domain_ir.json."""
    from aether_os.phases.base import TaskResult as _TaskResult

    data = phase_input.input_data
    run_id: str = phase_input.run_id
    ir_path = output_dir / "domain_ir.json"

    requirements: str = data.get("raw_input", "")
    if not requirements:
        req_path = Path(data.get("requirements_path", ""))
        if req_path.exists():
            requirements = req_path.read_text()

    if not requirements:
        return _TaskResult(
            output_path=str(output_dir),
            confidence=0.0,
            success=False,
            issues=["No requirements found — cannot extract Domain IR"],
            metadata={"error": "missing_requirements"},
        )

    # Load architecture.json for entity seeds
    arch_path_str = data.get("p02_architecture_path", "")
    if not arch_path_str:
        arch_path_str = str(output_dir.parent / "p02_architecture" / "architecture.json")
    arch_path = Path(arch_path_str)
    architecture: dict = {}
    # --- Problem 25 fix: handle str architecture output ---
    _arch_raw = data.get("architecture_output")
    if _arch_raw is not None:
        if isinstance(_arch_raw, str):
            try:
                architecture = json.loads(_arch_raw)
            except Exception:
                logger.warning("p02b: architecture_output is a non-JSON string — will extract from spec")
                architecture = {}
        elif isinstance(_arch_raw, dict):
            architecture = _arch_raw
    if not architecture and arch_path.exists():
        try:
            architecture = json.loads(arch_path.read_text())
        except Exception as exc:
            logger.debug("p02b: failed to read architecture from arch_path (non-fatal): %s", exc)
    # If architecture is still not a dict (e.g. came in as something unexpected), reset
    if not isinstance(architecture, dict):
        logger.warning("p02b: architecture resolved to non-dict type %s — resetting to {}", type(architecture))
        architecture = {}

    domain: str = getattr(phase_input, "domain", None) or architecture.get("domain", "general")
    app_name: str = data.get("app_name", data.get("project_name", "App"))
    seed = _seed_entities(architecture)

    llm = get_llm_client()
    errors: list[str] = []

    logger.info("p02b: starting SINGLE-pass Domain IR extraction for run %s", run_id)

    # ── LLM extraction — delegated to ir_extractor.run_4pass_extraction ────────
    # Single combined LLM call (was 4-pass sequential; retired to cut latency from
    # ~720s worst-case to ~60s).  Extracted to ir_extractor.py to keep this file
    # under 350 lines.
    p1, p2, p3, p4, _ext_errors = await run_4pass_extraction(
        requirements=requirements,
        seed=seed,
        llm=llm,
    )
    errors.extend(_ext_errors)
    combined_result = p1  # single-pass: all four are the same dict

    # If the single call produced nothing, build a minimal stub from app_name
    if not combined_result.get("entities"):
        logger.warning("p02b: LLM produced no entities — building stub IR")
        p1 = build_stub_ir(app_name)
        p2 = p3 = p4 = p1
        combined_result = p1

    # Merge all passes into DomainIR
    ir = _build_ir_from_passes(p1, p2, p3, p4, domain=domain, app_name=app_name)

    # Collect any fields with confidence below threshold as clarifying questions
    for entity in ir.entities:
        for f in entity.fields:
            if f.confidence < CONFIDENCE_THRESHOLD:
                # Avoid duplicates from pass 4
                already = any(
                    q.field_path == f"{entity.name}.{f.name}"
                    for q in ir.clarifying_questions
                )
                if not already:
                    ir.clarifying_questions.append(IRClarifyingQuestion(
                        field_path=f"{entity.name}.{f.name}",
                        confidence=f.confidence,
                        question=f"What does '{f.name}' represent on {entity.name}?",
                        options=[],
                    ))

    # ── Domain IR structural validation (dict-level, before DomainIR object) ──
    from aether_os.phases.p02b_domain_ir.validator import apply_validation_to_run as _apply_val
    _raw_ir_dict = combined_result if combined_result.get("entities") else (p1 or {})
    _domain_report, _fatal = _apply_val(_raw_ir_dict, combined_result, p1, data, errors, output_dir)
    if _fatal is not None:
        return _fatal

    # Validate and auto-fix IR before saving
    from aether_os.core.ir_validator import validate as _validate_ir
    val = _validate_ir(ir, fix=True)
    if not val.valid:
        logger.warning("p02b IR validation failed: %s", val.errors)
        errors.extend(val.errors)
    for w in val.warnings:
        logger.debug("p02b IR validator warning: %s", w)

    # --- Problem 25 fix: validate IR is not empty before saving ---
    if not ir.entities:
        raise ValueError(
            f"p02b: DomainIR is incomplete — no entities were extracted for app '{app_name}' "
            f"(domain={domain}). Check requirements input and LLM availability."
        )

    # Save IR to disk
    output_dir.mkdir(parents=True, exist_ok=True)
    ir.save(ir_path)
    logger.info("p02b: domain_ir.json written to %s", ir_path)

    has_questions = bool(ir.clarifying_questions)
    entity_count = len(ir.entities)
    field_count = sum(len(e.fields) for e in ir.entities)

    summary = (
        f"Domain IR extracted: {entity_count} entities, {field_count} fields, "
        f"{len(ir.relationships)} relationships, {len(ir.dashboard_metrics)} KPI metrics"
    )
    if has_questions:
        summary += f"\n{len(ir.clarifying_questions)} clarifying questions need answers before continuing"
    if errors:
        summary += f"\nWarnings: {', '.join(errors)}"

    return _TaskResult(
        output_path=str(ir_path),
        confidence=1.0 if not errors else 0.85,
        success=True,
        issues=[],
        metadata={
            "domain": domain,
            "entity_count": entity_count,
            "field_count": field_count,
            "relationship_count": len(ir.relationships),
            "metric_count": len(ir.dashboard_metrics),
            "clarifying_questions": len(ir.clarifying_questions),
            "has_questions": has_questions,
            "pass_errors": errors,
            "domain_ir_path": str(ir_path),
            "domain_validation": _domain_report.as_dict(),
            "output": summary,
        },
    )
