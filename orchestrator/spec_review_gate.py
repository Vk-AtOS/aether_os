"""
AetherOS — Spec Review Gate helper.

Extracted from factory_pipeline._execute_pipeline to keep that module
under control.  Called after p01_intake_requirements completes when
decision_mode != "autonomous".

Flow:
  1. LLM pre-critique pass (up to 2 rounds via spec_critique.critique_spec)
  2. Emit spec_review_ready SSE event
  3. Poll Redis for human approval (spec_approved | cancel)
  4. Auto-approve after SPEC_REVIEW_TIMEOUT seconds if no decision arrives

The critique pass is entirely non-blocking: any failure falls back to
the original spec and the gate continues normally.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def _run_spec_critique(accumulated_context: Dict[str, Any], run_id: str) -> None:
    """
    Run the LLM pre-critique loop and store the result in accumulated_context.

    Stores the improved spec under accumulated_context["spec_critique_improved"]
    if the spec was changed.  On any error, logs and returns silently.
    """
    try:
        from aether_os.phases.p01_intake_requirements.spec_critique import critique_spec
        from aether_os.core.llm.client import get_llm_client as _get_llm

        _spec_llm = _get_llm()
        _p01_artifacts = accumulated_context.get("p01_intake_requirements_output") or {}
        _req_doc = _p01_artifacts.get("requirements_doc") or {}
        _intake = _p01_artifacts.get("intake") or {}

        _spec_lines = [
            f"Project: {_intake.get('project_name', accumulated_context.get('project_name', ''))}",
            f"Domain: {_intake.get('domain', accumulated_context.get('domain', ''))}",
            f"Summary: {_intake.get('summary', accumulated_context.get('raw_input', '')[:500])}",
        ]
        _func_reqs = _req_doc.get("functional_requirements") or []
        if _func_reqs:
            _spec_lines.append("Functional Requirements:")
            _spec_lines.extend(f"  - {r}" for r in _func_reqs)
        _nfunc_reqs = _req_doc.get("non_functional_requirements") or []
        if _nfunc_reqs:
            _spec_lines.append("Non-Functional Requirements:")
            _spec_lines.extend(f"  - {r}" for r in _nfunc_reqs)
        _entities = _req_doc.get("entities") or []
        if _entities:
            _spec_lines.append("Entities:")
            _spec_lines.extend(
                f"  - {e.get('name', '')} ({e.get('table', '')}): {e.get('fields', [])}"
                for e in _entities
            )
        _raw_spec_text = "\n".join(_spec_lines) or accumulated_context.get("raw_input", "")

        _improved_spec = await critique_spec(_raw_spec_text, _spec_llm)
        if _improved_spec and _improved_spec != _raw_spec_text:
            accumulated_context["spec_critique_improved"] = _improved_spec
            logger.info(
                "[spec_review_gate] Spec improved from %d → %d chars (run=%s)",
                len(_raw_spec_text), len(_improved_spec), run_id,
            )
        else:
            logger.info("[spec_review_gate] No spec changes needed (run=%s)", run_id)

    except Exception as _critique_exc:
        logger.warning(
            "[spec_review_gate] Pre-critique failed (non-fatal — original spec kept, run=%s): %s",
            run_id, _critique_exc,
        )


async def run_spec_review_gate(
    run_id: str,
    accumulated_context: Dict[str, Any],
    emit_fn: Any,
    get_control_fn: Any,
    set_control_fn: Any,
    publish_event_fn: Any,
) -> None:
    """
    Run the full spec review gate flow including LLM pre-critique.

    Args:
        run_id:             Current pipeline run ID.
        accumulated_context: Mutable context dict shared across phases.
        emit_fn:            Bound emit() from orchestrator.events.
        get_control_fn:     Bound get_control() from core.pipeline_state.
        set_control_fn:     Bound set_control() from core.pipeline_state.
        publish_event_fn:   Bound publish_event() from core.pipeline_state.

    Raises:
        RuntimeError: if the pipeline is cancelled at the spec review gate.
    """
    # ── Step 1: LLM pre-critique (non-blocking) ───────────────────────────────
    await _run_spec_critique(accumulated_context, run_id)

    # ── Step 2: Check for pre-existing control signal ─────────────────────────
    _ctrl = await get_control_fn(run_id)
    if _ctrl == "spec_approved":
        logger.info("[spec_review_gate] Spec already approved — skipping gate (run=%s)", run_id)
        return
    if _ctrl is None or _ctrl not in ("spec_review", "spec_approved"):
        logger.error(
            "[spec_review_gate] Gate decision not found for run %s — emitting gate_error",
            run_id,
        )
        await publish_event_fn(run_id, {
            "type": "gate_error",
            "run_id": run_id,
            "message": "Gate decision not found. It may have been wiped by a system restore.",
        })
        # Do not abort — the gate_error SSE is enough for the UI to warn the user.
        # We continue and set the gate state below.

    # ── Step 3: Emit spec_review_ready and wait for human decision ────────────
    await set_control_fn(run_id, "spec_review")
    await emit_fn(
        {"type": "spec_review_ready", "run_id": run_id,
         "critique_available": bool(accumulated_context.get("spec_critique_improved"))},
        run_id=run_id,
    )
    logger.info("[spec_review_gate] Waiting for human approval (run=%s)", run_id)

    _spec_timeout = int(os.environ.get("SPEC_REVIEW_TIMEOUT", "600"))
    _spec_waited = 0
    while _spec_waited < _spec_timeout:
        _ctrl = await get_control_fn(run_id)
        if _ctrl == "spec_approved":
            logger.info("[spec_review_gate] Spec approved — continuing (run=%s)", run_id)
            await set_control_fn(run_id, "running")
            return
        if _ctrl == "cancel":
            logger.warning("[spec_review_gate] Spec review cancelled (run=%s)", run_id)
            raise RuntimeError("Pipeline cancelled at spec review")
        await asyncio.sleep(3)
        _spec_waited += 3

    # Timeout: auto-approve (better UX than silently aborting for unmonitored runs)
    logger.warning(
        "[spec_review_gate] Timed out after %ds — auto-approving run %s",
        _spec_timeout, run_id,
    )
    await set_control_fn(run_id, "running")
    await publish_event_fn(run_id, {
        "type": "spec_review_timeout",
        "run_id": run_id,
        "message": (
            f"Spec review auto-approved after {_spec_timeout}s. "
            "Pipeline continuing. Enable autonomous mode to skip this gate."
        ),
    })
