"""
Execution steps of a factory run, on a PipelineRun (KAN-57; design in
docs/design/pipeline_run.md).

Each step returns None to carry on, or the terminal result dict when the run
ended (aborted / cancelled). ``run_phase`` may also return SKIPPED, which keeps
the old behaviour of a skipped stage not reaching the control-signal check.
Collaborators that tests patch are read as ``fp.<name>`` (fp = factory_pipeline).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from aether_os.core.models import Run as _Run
from aether_os.orchestrator.events import ACTIVE_RUN_ID, ACTIVE_PHASE, ACTIVE_ORG_ID
from aether_os.orchestrator.messages import PhaseInput
from aether_os.orchestrator.pipeline_run import PipelineRun
from aether_os.orchestrator.pipeline_phase_post import after_phase_success

logger = logging.getLogger(__name__)

SKIPPED = object()


def _terminal(run: PipelineRun, status: str) -> dict:
    return {"run_id": run.run_id, "status": status, "phases": run.results,
            "output_dir": str(run.project_dir)}


async def run_wave(run: PipelineRun, wave: list) -> Optional[dict]:
    """A multi-phase wave: run concurrently, then merge results."""
    fp, run_id, results = run.fp, run.run_id, run.results
    ctx = run.accumulated_context
    try:
        wave_results = await fp.run_phases_in_wave(
            wave=wave,
            run_phase_fn=run.pipeline._run_phase,
            accumulated_context=ctx,
            run_id=run_id,
            org_id=run.org_id,
            project_dir=run.project_dir,
            domain=run.domain,
            client_id=run.client_id,
            emit_fn=fp.emit,
            update_state_fn=run.pipeline._update_state,
            phase_input_cls=PhaseInput,
            critical_phases=fp.CRITICAL_PHASES,
        )
    except Exception as _wave_exc:
        logger.error("[pipeline] Parallel wave %s raised unexpectedly: %s — aborting", wave, _wave_exc)
        return await run.pipeline._abort_run(
            run_id, f"Stages {', '.join(wave)} crashed: {_wave_exc}")

    for wp in wave:
        wr = wave_results.get(wp, {})
        results[wp] = wr
        # s09 only ever runs in a parallel wave, and it is the only
        # parallel stage with a post-stage hook: persist Run.live_url.
        await fp.hook_persist_live_url(wp, wr, run_id, ctx)
        # D6: record in project memory
        fp._pm_update(run.project_dir, {
            f"phase_{wp}": {"status": wr.get("status"), "duration_s": wr.get("duration_s")}
        })

    # A failed gate (any stage) or a failed critical stage ends the run here.
    # Checked before the checkpoint, so a restart re-runs this wave instead of
    # resuming after it.
    for wp in wave:
        block = fp.gate_block_reason(wp, results[wp], fp.CRITICAL_PHASES)
        if block:
            logger.error("[pipeline] %s blocked run %s in a parallel wave", wp, run_id)
            return await run.pipeline._abort_run(run_id, block, failed_stage=wp)

    # Checkpoint the wave once, on its earliest phase in run order. Resume
    # restarts at index(last_completed)+1, so checkpointing a later phase
    # (e.g. s12 in [s05, s12]) would skip s06-s11.
    run_order = list(run.phases_to_run)
    await fp.save_checkpoint(run_id, min(wave, key=run_order.index), ctx)

    # Control signal check after every wave
    if await fp.get_control(run_id) == "cancel":
        logger.info("Pipeline %s cancelled after wave %s", run_id, wave)
        await run.pipeline.ledger.async_update_run_status(run_id, "cancelled")
        await fp.publish_event(run_id, {"type": "pipeline_complete", "status": "cancelled",
                                        "ts": time.time()})
        return _terminal(run, "cancelled")
    return None


def _no_frontend_selected(ctx: dict):
    """The explicit 'no UI' selection, or None. Empty means 'use default React'."""
    ds = ctx.get("designer_spec") or {}
    tp = ctx.get("tech_preferences") or {}
    selection = ((ds.get("frontend") or {}).get("framework", "")
                 or tp.get("frontend", "")
                 or ctx.get("frontend", "")
                 or "")
    return selection if str(selection).lower() in ("none", "no", "n/a") else None


def _bridge_call(run: PipelineRun, label: str, *calls) -> None:
    """Optional telemetry; never fails the run."""
    if not run.bridge:
        return
    try:
        for name, args, kwargs in calls:
            getattr(run.bridge, name)(run.run_id, *args, **kwargs)
    except Exception as exc:
        logger.debug("bridge.%s non-fatal: %s", label, exc)


async def _skip_frontend(run: PipelineRun, phase_name: str, selection) -> None:
    logger.info("[pipeline] Skipping s04_frontend — frontend=%r (no UI requested)", selection)
    run.results[phase_name] = {
        "status": "skipped", "output_path": "", "artifacts": {},
        "metadata": {"skipped_reason": "no_frontend_selected"},
        "confidence": 1.0, "issues": [],
    }
    await run.pipeline._update_state(run.run_id, phase_name, "skipped")
    await run.fp.emit({"type": "phase_complete", "phase": phase_name, "status": "skipped"},
                      run_id=run.run_id)


async def _phase_body(run: PipelineRun, phase_name: str, timeout_box: list):
    """The try body of one phase. Returns SKIPPED, a terminal dict, or None."""
    fp, run_id, results = run.fp, run.run_id, run.results
    ctx = run.accumulated_context
    phase_input = PhaseInput(
        run_id=run_id, project_id=run_id, phase=phase_name, input_data=ctx,
        output_dir=str(run.project_dir), domain=run.domain, client_id=run.client_id,
    )
    # PHASE_TIMEOUT_<PHASE_NAME>, else PHASE_TIMEOUT_SECONDS, else a per-stage default.
    default_timeout = "600"
    if phase_name == "s04_frontend":
        # Skip s04 only when frontend is EXPLICITLY disabled.
        selection = _no_frontend_selected(ctx)
        if selection is not None:
            await _skip_frontend(run, phase_name, selection)
            return SKIPPED
        default_timeout = "1200"  # frontend needs longer; matches parallel_runner logic
    elif phase_name == "s09_devops":
        default_timeout = "1800"  # Docker build + vite + pip can exceed 600s on small VPS
    phase_timeout = float(os.environ.get(
        f"PHASE_TIMEOUT_{phase_name.upper()}",
        os.environ.get("PHASE_TIMEOUT_SECONDS", default_timeout)))
    timeout_box.append(phase_timeout)

    _bridge_call(run, "report_stage_start", ("report_stage_start", (phase_name,), {}))
    phase_result = await asyncio.wait_for(
        run.pipeline._run_phase(phase_name, phase_input), timeout=phase_timeout)
    results[phase_name] = phase_result

    # Gates block: a gate that still fails after retries, or a failed critical
    # stage, ends the run here. Nothing below (context merge, checkpoint, hooks,
    # later stages) runs, so a restart resumes at this stage.
    block = fp.gate_block_reason(phase_name, phase_result, fp.CRITICAL_PHASES)
    if block:
        logger.error("[pipeline] %s blocked run %s: %s", phase_name, run_id, fp.redact_secrets(block))
        await run.pipeline._update_state(run_id, phase_name, "failed")
        await fp.emit({"type": "phase_complete", "phase": phase_name, "status": "failed",
                       "error": block}, run_id=run_id)
        redacted = fp.redact_secrets(block)
        _bridge_call(run, "report_failure(block)",
                     ("report_failure", (phase_name, redacted), {}),
                     ("report_stage_complete", (phase_name, 0), {"success": False}))
        return await run.pipeline._abort_run(run_id, block, failed_stage=phase_name)

    # Guided mode: pause after every phase so a respondent can fill in the
    # per-stage questionnaire before the pipeline continues.
    if ctx.get("mode", "autonomous") == "guided":
        await fp._pause_for_questionnaire(
            run_id=run_id, stage_id=phase_name, stage_result=phase_result,
            accumulated_context=ctx, sem=getattr(run.pipeline, "_pipeline_sem", None),
        )
    await after_phase_success(run, phase_name, phase_result, phase_input)
    return None


async def run_phase(run: PipelineRun, phase_name: str):
    """A single-phase wave. Returns None, SKIPPED or a terminal dict."""
    fp, run_id = run.fp, run.run_id
    # Context vars so LLM calls in this phase can emit to the queue
    run_token = ACTIVE_RUN_ID.set(run_id)
    phase_token = ACTIVE_PHASE.set(phase_name)
    org_token = ACTIVE_ORG_ID.set(run.org_id)

    await run.pipeline._update_state(run_id, phase_name, "running")
    await fp.emit({"type": "phase_start", "phase": phase_name}, run_id=run_id)

    timeout_box: list = []
    try:
        return await _phase_body(run, phase_name, timeout_box)
    except asyncio.TimeoutError:
        logger.warning(f"{phase_name} timed out, continuing")
        phase_timeout = timeout_box[0] if timeout_box else 0
        await run.pipeline._update_state(run_id, phase_name, "timeout")
        run.results[phase_name] = {"status": "timeout", "output_path": ""}
        await fp.emit({"type": "phase_complete", "phase": phase_name, "status": "timeout"}, run_id=run_id)
        _bridge_call(run, "report_failure(timeout)",
                     ("report_failure", (phase_name, "Phase timed out"), {}),
                     ("report_stage_complete", (phase_name, int(phase_timeout)), {"success": False}))
        if phase_name in fp.CRITICAL_PHASES:
            logger.error("Critical phase %s timed out — aborting pipeline %s", phase_name, run_id)
            return await run.pipeline._abort_run(
                run_id, fp.timeout_reason(phase_timeout, phase_name), failed_stage=phase_name)
    except Exception as e:
        logger.error("%s failed: %s", phase_name, fp.redact_secrets(e))
        await run.pipeline._update_state(run_id, phase_name, "failed")
        run.results[phase_name] = {"status": "failed", "error": fp.redact_secrets(e), "output_path": ""}
        await fp.emit({"type": "phase_complete", "phase": phase_name, "status": "failed",
                       "error": str(e)}, run_id=run_id)
        _bridge_call(run, "report_failure",
                     ("report_failure", (phase_name, fp.redact_secrets(e)), {}),
                     ("report_stage_complete", (phase_name, 0), {"success": False}))
        if phase_name in fp.CRITICAL_PHASES:
            logger.error("Critical phase %s failed — aborting pipeline %s", phase_name, run_id)
            return await run.pipeline._abort_run(
                run_id, f"Stage {phase_name} failed: {e}", failed_stage=phase_name)
    finally:
        # Reset all three to prevent ContextVar leaks between concurrent pipeline runs.
        ACTIVE_RUN_ID.reset(run_token)
        ACTIVE_PHASE.reset(phase_token)
        ACTIVE_ORG_ID.reset(org_token)
    return None


async def check_control(run: PipelineRun, phase_name: str) -> Optional[dict]:
    """Control signal check after each single phase: cancel or pause."""
    fp, run_id = run.fp, run.run_id
    ledger = run.pipeline.ledger
    control = await fp.get_control(run_id)
    if control == "cancel":
        logger.info("Pipeline %s cancelled after phase %s", run_id, phase_name)
        await ledger.async_update_run_status(run_id, "cancelled")
        # Fix 62: persist finished_at on cancel (ORM, SQLite-safe)
        try:
            async with fp._gsf_canc()() as s:
                r = await s.get(_Run, run_id)
                if r:
                    r.finished_at = time.time()
                    await s.commit()
        except Exception as exc:
            logger.debug("finished_at persist failed on cancel (non-fatal): %s", exc)
        await fp.publish_event(run_id, {"type": "pipeline_complete", "status": "cancelled", "ts": time.time()})
        return _terminal(run, "cancelled")
    if control == "pause":
        logger.info("Pipeline %s paused after phase %s", run_id, phase_name)
        await ledger.async_update_run_status(run_id, "paused")
        while await fp.get_control(run_id) == "pause":
            await asyncio.sleep(2)
        if await fp.get_control(run_id) == "cancel":
            await ledger.async_update_run_status(run_id, "cancelled")
            return _terminal(run, "cancelled")
        await ledger.async_update_run_status(run_id, "running")
    return None


async def finish(run: PipelineRun) -> dict:
    """Mark the run complete and schedule the background completion tasks."""
    fp, run_id, results = run.fp, run.run_id, run.results
    # "council_review": the DeliveryCouncil background task writes the real final
    # status ("completed" or "needs_review").
    await run.pipeline._update_state(run_id, "pipeline", "complete")
    await run.pipeline.ledger.async_update_run_status(run_id, "council_review")
    duration = time.time() - run.pipeline_start

    # finished_at inline (fast ORM write, not background)
    await fp.persist_finished_at(run_id)

    # pipeline_complete immediately so SSE clients are not blocked.
    await fp.publish_event(run_id, {
        "type": "pipeline_complete",
        "status": "council_review",
        "duration": round(duration, 1),
        "stage_summary": fp.summarize_stage_outcomes(results),
        "ts": time.time(),
    })

    # Notifications, webhooks, learning, S3 upload, etc. run in the background.
    fp.schedule_completion_tasks(
        run_id=run_id,
        org_id=run.org_id,
        client_id=run.client_id,
        domain=run.domain,
        raw_input=run.raw_input,
        project_name=run.project_name,
        project_dir=run.project_dir,
        duration=duration,
        results=results,
        phases_to_run=list(run.phases_to_run),
        accumulated_context=run.accumulated_context,
        background_tasks=run.pipeline._background_tasks,
        publish_event_fn=fp.publish_event,
        clear_run_fn=fp.clear_run,
        delivery_council_check_fn=fp.delivery_council_check,
        extract_learning_fn=fp.extract_learning,
        store_run_memory_fn=fp.store_run_memory,
        embed_artifacts_fn=fp.embed_artifacts,
        upload_to_s3_fn=fp.upload_to_s3,
        pm_update_fn=fp._pm_update,
        pm_changelog_fn=fp._pm_changelog,
    )

    # Free this run's bounded in-process message bus on long-lived servers.
    fp.release_bus(run_id)

    return {
        "run_id": run_id,
        "project_id": run_id,
        "status": "complete",
        "phases": results,
        "output_dir": str(run.project_dir),
        "duration_seconds": round(duration, 2),
        "phase_count": len(run.phases_to_run),
        "stage_summary": fp.summarize_stage_outcomes(results),
    }


async def execute(run: PipelineRun) -> dict:
    """Run every wave in order, then finish."""
    for wave in run.waves:
        if len(wave) > 1:
            done = await run_wave(run, wave)
            if done is not None:
                return done
            continue
        phase_name = wave[0]
        outcome = await run_phase(run, phase_name)
        if outcome is SKIPPED:
            continue  # a skipped stage never reached the control check
        if outcome is not None:
            return outcome
        done = await check_control(run, phase_name)
        if done is not None:
            return done
    return await finish(run)
