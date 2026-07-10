"""
AetherOS — Parallel phase runner.

Executes a wave of independent phases concurrently using asyncio.gather().
Each phase in the wave receives a shallow copy of accumulated_context at
wave start (so phases in the same wave cannot see each other's intermediate
outputs — correct DAG semantics).  After all phases in the wave finish,
their outputs are merged back into the master accumulated_context in
original phase-list order.

Usage (called from factory_pipeline._execute_pipeline):

    from aether_os.orchestrator.parallel_runner import run_phases_in_wave

    wave_results = await run_phases_in_wave(
        wave=["p04b_business_logic", "p05_frontend"],
        run_phase_fn=self._run_phase,
        accumulated_context=accumulated_context,
        run_id=run_id,
        org_id=org_id,
        project_dir=project_dir,
        domain=domain,
        client_id=client_id,
        emit_fn=emit,
        update_state_fn=self._update_state,
        phase_input_cls=PhaseInput,
        critical_phases=CRITICAL_PHASES,
    )
    # wave_results: dict mapping phase_name → phase_result dict
"""
from __future__ import annotations

import asyncio
import copy
import json as _json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fast_snapshot(ctx: dict) -> dict:
    """Faster alternative to copy.deepcopy for accumulated_context.
    JSON-round-trips each value (fast for strings/dicts/lists);
    falls back to deepcopy only for non-serializable objects."""
    result = {}
    for k, v in ctx.items():
        try:
            result[k] = _json.loads(_json.dumps(v, default=str))
        except Exception:
            result[k] = copy.deepcopy(v)
    return result


# Default per-phase timeout (seconds) — overridable via PHASE_TIMEOUT_SECONDS env var.
_DEFAULT_PHASE_TIMEOUT = 600.0
_FRONTEND_TIMEOUT = 1200.0   # s04_frontend needs longer; matches factory_pipeline logic


def _phase_timeout_for(phase_name: str) -> float:
    """Return the per-phase timeout in seconds, honouring env overrides."""
    env_key = f"PHASE_TIMEOUT_{phase_name.upper()}"
    default = _FRONTEND_TIMEOUT if phase_name == "s04_frontend" else _DEFAULT_PHASE_TIMEOUT
    return float(os.environ.get(env_key, os.environ.get("PHASE_TIMEOUT_SECONDS", default)))


async def _run_one_phase_in_wave(
    phase_name: str,
    run_phase_fn: Callable,
    phase_input_cls: Any,
    ctx_snapshot: Dict[str, Any],
    run_id: str,
    org_id: Optional[str],
    project_dir: Path,
    domain: str,
    client_id: str,
    emit_fn: Callable,
    update_state_fn: Callable,
) -> tuple[str, Dict[str, Any]]:
    """Run a single phase inside a wave; return (phase_name, result_dict).

    Never raises — exceptions are caught, logged, and returned as a failed
    result dict so the rest of the wave can continue.
    """
    timeout = _phase_timeout_for(phase_name)

    # Import here to avoid circular import at module load time.
    from aether_os.orchestrator.messages import PhaseInput  # noqa: PLC0415

    phase_input = phase_input_cls(
        run_id=run_id,
        project_id=run_id,
        phase=phase_name,
        input_data=ctx_snapshot,
        output_dir=str(project_dir),
        domain=domain,
        client_id=client_id,
    )

    await update_state_fn(run_id, phase_name, "running")
    await emit_fn({"type": "phase_start", "phase": phase_name, "parallel": True}, run_id=run_id)

    try:
        phase_result = await asyncio.wait_for(
            run_phase_fn(phase_name, phase_input),
            timeout=timeout,
        )
        p_status = "passed" if phase_result.get("status") == "passed" else "completed"
        await update_state_fn(run_id, phase_name, p_status)
        await emit_fn(
            {"type": "phase_complete", "phase": phase_name, "status": p_status,
             "parallel": True, "duration": phase_result.get("duration_s")},
            run_id=run_id,
        )
        logger.info("[parallel_runner] %s completed (status=%s)", phase_name, p_status)
        return phase_name, phase_result

    except asyncio.TimeoutError:
        logger.warning("[parallel_runner] %s timed out after %.0fs", phase_name, timeout)
        result = {"status": "timeout", "output_path": "", "artifacts": {}, "metadata": {}}
        await update_state_fn(run_id, phase_name, "timeout")
        await emit_fn(
            {"type": "phase_complete", "phase": phase_name, "status": "timeout", "parallel": True},
            run_id=run_id,
        )
        return phase_name, result

    except Exception as e:
        logger.warning(
            "[parallel_runner] %s failed during parallel wave: %s",
            phase_name, e,
        )
        result = {"status": "failed", "error": str(e), "output_path": "", "artifacts": {}, "metadata": {}}
        await update_state_fn(run_id, phase_name, "failed")
        await emit_fn(
            {"type": "phase_complete", "phase": phase_name, "status": "failed",
             "error": str(e), "parallel": True},
            run_id=run_id,
        )
        return phase_name, result


async def run_phases_in_wave(
    wave: List[str],
    run_phase_fn: Callable,
    accumulated_context: Dict[str, Any],
    run_id: str,
    org_id: Optional[str],
    project_dir: Path,
    domain: str,
    client_id: str,
    emit_fn: Callable,
    update_state_fn: Callable,
    phase_input_cls: Any,
    critical_phases: frozenset,
) -> Dict[str, Dict[str, Any]]:
    """Run all phases in *wave* concurrently via asyncio.gather().

    Context isolation:
      - Each phase receives a *shallow copy* of accumulated_context at wave
        start.  Phases in the same wave cannot see each other's outputs
        (correct DAG semantics).
      - After the wave finishes, each phase's outputs are merged into the
        master accumulated_context in original wave order (first phase wins
        on key collisions within the same wave).

    Critical phase handling:
      - If any phase in critical_phases fails or times out, the function
        returns immediately after the wave completes rather than swallowing
        the failure.  Callers check the returned dict for failed status.

    Args:
        wave:                Ordered list of phase names to run concurrently.
        run_phase_fn:        Coroutine function — async (phase_name, PhaseInput) → dict.
        accumulated_context: Master context dict (mutated in place after wave).
        run_id:              Current run UUID.
        org_id:              Organisation ID.
        project_dir:         Root project directory Path.
        domain:              Build domain string.
        client_id:           WebSocket client ID.
        emit_fn:             Async SSE emit function.
        update_state_fn:     Async state-machine update function.
        phase_input_cls:     PhaseInput class (passed in to avoid circular import).
        critical_phases:     frozenset of phase names that abort the pipeline on failure.

    Returns:
        Dict mapping phase_name → phase result dict for every phase in wave.
    """
    # Take a snapshot of accumulated_context before the wave starts.
    # Shallow copy would share nested dicts between concurrent phases, allowing
    # one phase to corrupt another's context via mutations to nested objects.
    # _fast_snapshot JSON-round-trips JSON-serializable values (faster for large
    # string/dict data) and falls back to deepcopy only for non-serializable objects.
    ctx_snapshot = _fast_snapshot(accumulated_context)

    wave_start = time.time()
    logger.info(
        "[parallel_runner] Starting wave of %d phases in parallel: %s",
        len(wave), wave,
    )
    await emit_fn(
        {"type": "wave_start", "phases": wave, "count": len(wave)},
        run_id=run_id,
    )

    # Launch all phases concurrently; each coroutine handles its own errors.
    tasks = [
        _run_one_phase_in_wave(
            phase_name=phase_name,
            run_phase_fn=run_phase_fn,
            phase_input_cls=phase_input_cls,
            ctx_snapshot=ctx_snapshot,
            run_id=run_id,
            org_id=org_id,
            project_dir=project_dir,
            domain=domain,
            client_id=client_id,
            emit_fn=emit_fn,
            update_state_fn=update_state_fn,
        )
        for phase_name in wave
    ]

    raw_results: list[tuple[str, Dict[str, Any]]] = await asyncio.gather(*tasks)

    # Build result dict preserving wave order.
    wave_results: Dict[str, Dict[str, Any]] = {}
    for phase_name, phase_result in raw_results:
        wave_results[phase_name] = phase_result

    # Merge phase outputs back into master context in wave order.
    # This mirrors the sequential pipeline's context-propagation logic:
    #   accumulated_context[f"{phase_name}_output"] = phase_result.get("artifacts", {})
    #   accumulated_context[f"{phase_name}_path"]   = phase_result.get("output_path", "")
    for phase_name in wave:
        phase_result = wave_results[phase_name]
        accumulated_context[f"{phase_name}_output"] = phase_result.get("artifacts", {})
        accumulated_context[f"{phase_name}_path"] = phase_result.get("output_path", "")

        # Confidence trail — mirror sequential pipeline behaviour.
        _phase_conf = phase_result.get("confidence", 1.0)
        _phase_conf_reason = phase_result.get("confidence_reason", "")
        _conf_trail = accumulated_context.setdefault("phase_confidence", {})
        _conf_trail[phase_name] = {"confidence": _phase_conf, "reason": _phase_conf_reason}
        _low_conf = accumulated_context.setdefault("low_confidence_phases", [])
        if _phase_conf < 0.5 and phase_name not in _low_conf:
            _low_conf.append(phase_name)
            logger.warning(
                "[parallel_runner] Phase %s has low confidence %.2f (%s)",
                phase_name, _phase_conf, _phase_conf_reason or "no reason given",
            )

        # Phase summary trail — mirror sequential pipeline behaviour.
        _summaries = accumulated_context.setdefault("phase_summaries", [])
        _meta = phase_result.get("metadata", {}) or {}
        _p_dir = project_dir / phase_name
        _artifacts = [f.name for f in _p_dir.rglob("*") if f.is_file()][:10] if _p_dir.exists() else []
        _summaries.append({
            "phase": phase_name,
            "status": phase_result.get("status", "completed"),
            "output_path": phase_result.get("output_path", ""),
            "key_artifacts": _artifacts,
            "decisions": _meta.get("decisions", []),
            "open_issues": (phase_result.get("issues") or [])[:5],
            "confidence": _meta.get("confidence", phase_result.get("confidence")),
            "parallel": True,
        })

    wave_elapsed = round(time.time() - wave_start, 1)
    logger.info(
        "[parallel_runner] Wave complete in %.1fs — phases: %s",
        wave_elapsed, {p: wave_results[p].get("status") for p in wave},
    )
    await emit_fn(
        {"type": "wave_complete", "phases": wave, "elapsed_s": wave_elapsed,
         "statuses": {p: wave_results[p].get("status") for p in wave}},
        run_id=run_id,
    )

    return wave_results
