"""
What happens after one single-phase stage succeeded (KAN-57; see
docs/design/pipeline_run.md): file events, context merge, confidence trail,
summaries, checkpoint, post-stage hooks, state and memory.

Moved verbatim from the old _execute_pipeline body. Collaborators tests patch
are read as ``run.fp.<name>`` (fp = orchestrator.factory_pipeline).
"""
from __future__ import annotations

import logging

from aether_os.orchestrator.context_schema import assert_context, validate_context_after_stage

logger = logging.getLogger(__name__)

_SKIP_PARTS = ("node_modules/", ".git/", "dist/", "__pycache__/")


async def _emit_file_events(run, phase_name: str) -> None:
    """file_written events for every file produced by this phase."""
    phase_dir = run.project_dir / phase_name
    if not phase_dir.exists():
        return
    for f in phase_dir.rglob("*"):
        if not f.is_file():
            continue
        rel_path = str(f.relative_to(run.project_dir))
        if any(p in rel_path for p in _SKIP_PARTS) or rel_path.endswith(".pyc"):
            continue
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        await run.fp.emit({"type": "file_written", "phase": phase_name,
                           "path": rel_path, "size": size}, run_id=run.run_id)


def _merge_into_context(run, phase_name: str, phase_result: dict) -> None:
    """Phase output, metadata keys, schema checks, confidence trail, summaries."""
    ctx = run.accumulated_context
    ctx[f"{phase_name}_output"] = phase_result.get("artifacts", {})
    ctx[f"{phase_name}_path"] = phase_result.get("output_path", "")

    # Stage metadata keys reach downstream stages without hooks as the only bridge.
    for k, v in (phase_result.get("metadata") or {}).items():
        if k not in ctx or v is not None:
            ctx[k] = v

    # Advisory schema check — logs warnings if expected keys are absent
    assert_context(ctx, phase_name)
    # DC1: structured per-stage required-key validation
    missing = validate_context_after_stage(phase_name, ctx)
    if missing:
        logger.warning("[pipeline] accumulated_context missing expected keys after %s: %s",
                       phase_name, missing)

    # Confidence propagation: every phase's confidence in a central trail
    conf = phase_result.get("confidence", 1.0)
    conf_reason = phase_result.get("confidence_reason", "")
    ctx.setdefault("phase_confidence", {})[phase_name] = {"confidence": conf, "reason": conf_reason}
    # Flag any phase below 0.5 so downstream phases and the UI can surface it
    low = ctx.setdefault("low_confidence_phases", [])
    if conf < 0.5 and phase_name not in low:
        low.append(phase_name)
        logger.warning("[pipeline] Phase %s has low confidence %.2f (%s) — flagging for review",
                       phase_name, conf, conf_reason or "no reason given")

    # Sliding context window: a compact summary so downstream phases get facts, not just paths.
    meta = phase_result.get("metadata", {}) or {}
    artifacts = []
    p_dir = run.project_dir / phase_name
    if p_dir.exists():
        artifacts = [f.name for f in p_dir.rglob("*") if f.is_file()][:10]
    ctx.setdefault("phase_summaries", []).append({
        "phase": phase_name,
        "status": phase_result.get("status", "completed"),
        "output_path": phase_result.get("output_path", ""),
        "key_artifacts": artifacts,
        "decisions": meta.get("decisions", []),
        "open_issues": (phase_result.get("issues") or [])[:5],
        "confidence": meta.get("confidence", phase_result.get("confidence")),
    })


async def after_phase_success(run, phase_name: str, phase_result: dict, phase_input) -> None:
    fp, run_id, ctx = run.fp, run.run_id, run.accumulated_context
    await _emit_file_events(run, phase_name)
    _merge_into_context(run, phase_name, phase_result)

    # Checkpoint after every phase so a crashed run can resume
    await fp.save_checkpoint(run_id, phase_name, ctx)

    # Per-phase post-processing hooks (phase_hooks.py): live_url, intake JSON,
    # architecture, knowledge graph, BackendAuditCouncil, quality gate.
    # They mutate accumulated_context in place.
    await fp.run_phase_hooks(
        phase_name=phase_name,
        phase_result=phase_result,
        run_id=run_id,
        project_dir=run.project_dir,
        accumulated_context=ctx,
        domain=run.domain,
        client_id=run.client_id,
        emit_fn=fp.emit,
        get_control_fn=fp.get_control,
        set_control_fn=fp.set_control,
        publish_event_fn=fp.publish_event,
        run_phase_fn=run.pipeline._run_phase,
        background_tasks=run.pipeline._background_tasks,
        messages_module=fp._messages_module,
        phase_input=phase_input,
    )

    p_status = fp.recorded_status(phase_result)
    await run.pipeline._update_state(run_id, phase_name, p_status)
    # D6: Record phase completion in project memory
    fp._pm_update(run.project_dir, {
        f"phase_{phase_name}": {"status": p_status, "duration_s": phase_result.get("duration_s")}
    })
    await fp.emit({"type": "phase_complete", "phase": phase_name, "status": p_status,
                   "duration": phase_result.get("duration_s")}, run_id=run_id)
    if run.bridge:
        try:
            elapsed = int(phase_result.get("duration_s") or 0)
            run.bridge.report_stage_complete(run_id, phase_name, elapsed, success=p_status != "failed")
        except Exception as exc:
            logger.debug("bridge.report_stage_complete non-fatal: %s", exc)
