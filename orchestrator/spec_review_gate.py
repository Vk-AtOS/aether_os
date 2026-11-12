"""
AetherOS — Spec Review Gate helper.

Extracted from factory_pipeline._execute_pipeline to keep that module
under control.  Called after p01_intake_requirements completes when
decision_mode != "autonomous".

Flow:
  1. LLM pre-critique pass (up to 2 rounds via spec_critique.critique_spec)
  2. Emit spec_review_ready SSE event
  3. Poll Redis for human approval (spec_approved | cancel), which arrives only
     through core.spec_approval.decide_spec (dashboard, client portal, Prime; ledgered)
  4. No decision within SPEC_REVIEW_TIMEOUT seconds: the gate EXPIRES and the run
     ends as failed. Silence is never approval.

Why expire rather than wait forever: a waiting run holds one of the few pipeline
concurrency slots (PIPELINE_MAX_CONCURRENT) and an in-process task that a restart
loses anyway. Ending it frees the slot, shows a clear reason, and the run can be
restarted from its checkpoint, which re-asks for review (phase_selector).

The only way past the gate without a person is the organisation's explicit
autonomous_mode setting, read from the database at the gate (apply_spec_review)
and recorded on the run (context, checkpoint, ledger, event).

The critique pass is entirely non-blocking: any failure falls back to
the original spec and the gate continues normally.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import get_session_factory
from aether_os.core.errors import PipelineBlockedError
from aether_os.core.models import Organisation, Run
from aether_os.orchestrator.run_state import save_checkpoint

logger = logging.getLogger(__name__)

# Context key holding how the gate was passed; a checkpoint without it has not passed.
REVIEW_KEY = "spec_review"


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

    # ── Step 2: Report a state the gate did not expect (it still waits afresh) ─
    _ctrl = await get_control_fn(run_id)
    # A leftover "spec_approved" is NOT taken as approval of this spec: only an
    # approval given while this gate waits counts.
    if _ctrl is not None and _ctrl not in ("spec_review", "run", "running"):
        logger.warning(
            "[spec_review_gate] Unexpected gate state '%s' for run %s — waiting for a fresh decision",
            _ctrl, run_id,
        )
        await publish_event_fn(run_id, {
            "type": "gate_error",
            "run_id": run_id,
            "message": "Gate decision not found. It may have been wiped by a system restore.",
        })

    # ── Step 3: Emit spec_review_ready and wait for human decision ────────────
    await set_control_fn(run_id, "spec_review")
    await emit_fn(
        {"type": "spec_review_ready", "run_id": run_id,
         "critique_available": bool(accumulated_context.get("spec_critique_improved"))},
        run_id=run_id,
    )
    logger.info("[spec_review_gate] Waiting for human approval (run=%s)", run_id)

    _spec_timeout = int(os.environ.get("SPEC_REVIEW_TIMEOUT", "600"))
    _deadline = time.monotonic() + _spec_timeout
    while True:
        _ctrl = await get_control_fn(run_id)
        if _ctrl == "spec_approved":
            logger.info("[spec_review_gate] Spec approved — continuing (run=%s)", run_id)
            await set_control_fn(run_id, "running")
            return
        if _ctrl == "cancel":
            logger.warning("[spec_review_gate] Spec review cancelled (run=%s)", run_id)
            raise RuntimeError("Pipeline cancelled at spec review")
        if time.monotonic() >= _deadline:
            break
        await asyncio.sleep(3)

    # Timeout: fail closed. Late approvals now get 409 (the run is no longer waiting).
    await set_control_fn(run_id, "spec_expired")
    logger.warning("[spec_review_gate] No decision within %ds — run %s expires", _spec_timeout, run_id)
    await publish_event_fn(run_id, {
        "type": "spec_review_timeout",
        "run_id": run_id,
        "message": (
            f"Spec review expired: nobody approved the specification within {_spec_timeout}s, "
            "so nothing was built past intake. Restart the run to review it again."
        ),
    })
    raise PipelineBlockedError(
        f"Spec review expired after {_spec_timeout}s with no decision; the run was not approved. "
        "Restart it to review the specification again.")


async def _org_of_run(run_id: str) -> Tuple[Optional[str], bool]:
    """(org_id, autonomous_mode) for the run, read from the database: the setting in
    force now, not a copy in the mutable run context."""
    async with get_session_factory()() as session:
        row = (await session.execute(
            select(Run.org_id, Organisation.autonomous_mode)
            .join(Organisation, Organisation.id == Run.org_id, isouter=True)
            .where(Run.id == run_id))).first()
    if row is None:
        return None, False
    return row[0], bool(row[1])


async def apply_spec_review(
    run_id: str,
    accumulated_context: Dict[str, Any],
    emit_fn: Any,
    get_control_fn: Any,
    set_control_fn: Any,
    publish_event_fn: Any,
) -> None:
    """Pass the spec review gate or raise. Called after s01_intake for every run.

    Skipped only when the run's organisation has autonomous_mode on; that skip is
    recorded on the run. If the setting cannot be read the gate runs (fail closed).
    Either way the outcome is stored under accumulated_context["spec_review"] and
    re-checkpointed, so a resumed run knows the gate was passed.
    """
    org_id, autonomous = None, False
    try:
        org_id, autonomous = await _org_of_run(run_id)
    except Exception as exc:
        logger.warning("[spec_review_gate] could not read autonomous_mode for run %s — "
                       "reviewing: %s", run_id, exc)
    if autonomous:
        record = {"status": "skipped", "reason": "autonomous_mode", "at": time.time()}
        logger.info("[spec_review_gate] run %s: review skipped (organisation autonomous_mode)", run_id)
        await get_ledger().async_log_audit_event(
            org_id=org_id or "-", user_id="system", action="run.spec_review_skipped",
            resource_type="run", resource_id=run_id, metadata={"reason": "autonomous_mode"})
        await publish_event_fn(run_id, {
            "type": "spec_review_skipped", "run_id": run_id,
            "message": "Spec review skipped: the organisation runs in autonomous mode.",
        })
    else:
        await run_spec_review_gate(
            run_id=run_id,
            accumulated_context=accumulated_context,
            emit_fn=emit_fn,
            get_control_fn=get_control_fn,
            set_control_fn=set_control_fn,
            publish_event_fn=publish_event_fn,
        )
        record = {"status": "approved", "at": time.time()}
    accumulated_context[REVIEW_KEY] = record
    await save_checkpoint(run_id, "s01_intake", accumulated_context)
