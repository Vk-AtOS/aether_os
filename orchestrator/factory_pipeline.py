"""
AetherOS — 29-Phase Factory Pipeline

Each phase is a completely independent module.
All inter-phase communication goes through the MessageBus only.
The orchestrator routes messages; it never calls phase logic directly.

Phase registry data lives in orchestrator/phase_sequence.py.
Run-state helpers live in orchestrator/run_state.py.
"""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.orchestrator.bus import get_bus, release_bus
from aether_os.orchestrator.messages import PhaseInput, PhaseMessage, PhaseResult
from aether_os.orchestrator.state_machine import (
    PipelineStateMachine, PipelineState, PHASE_TO_STATE,
)
from aether_os.orchestrator.events import (
    ACTIVE_RUN_ID, ACTIVE_PHASE, ACTIVE_ORG_ID, emit,
)
from aether_os.core.pipeline_state import (
    publish_event, get_control, set_control, clear_run,
)
from aether_os.core.projects import get_project_manager
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.project_memory import (
    init_memory as _pm_init,
    update_memory as _pm_update,
    add_changelog_entry as _pm_changelog,
)
from aether_os.orchestrator.phase_sequence import (
    CRITICAL_PHASES,
    INACTIVE_PHASE_DIRS,
    PHASE_SEQUENCE,
    PHASE_SUPERVISORS,
    _load_supervisor,
)
from aether_os.orchestrator.run_state import (
    _extract_project_name,
    _get_pipeline_semaphore,
    update_phase_state,
    save_checkpoint,
)
from aether_os.orchestrator.artifact_collector import (
    embed_artifacts,
    upload_to_s3,
    delivery_council_check,
    extract_learning,
    store_run_memory,
)

logger = logging.getLogger(__name__)


class FactoryPipeline:
    """
    26-phase factory pipeline.
    Routes entirely via the message bus.
    No phase imports another phase.
    """

    def __init__(self) -> None:
        self.ledger = get_ledger()
        self.pm = get_project_manager()
        self._background_tasks = set()

    async def run(self,
                  client_id: str,
                  raw_input: str,
                  domain: str = "general",
                  project_name: Optional[str] = None,
                  start_phase: Optional[str] = None,
                  run_id: Optional[str] = None,
                  org_id: Optional[str] = None,
                  org_slug: Optional[str] = None,
                  plan: Optional[str] = None,
                  is_change_request: bool = False,
                  memory_context: Optional[str] = None,
                  council_preflight: Optional[Dict[str, Any]] = None,
                  github_url: Optional[str] = None,
                  designer_spec: Optional[Dict[str, Any]] = None,
                  tech_preferences: Optional[Dict[str, Any]] = None,
                  model_preference: Optional[str] = None,
                  priority: Optional[str] = None,
                  codebase_mode: Optional[str] = None,
                  existing_schema: Optional[Dict[str, Any]] = None) -> dict:

        timeout = float(os.environ.get("PIPELINE_TIMEOUT_MINUTES", "30")) * 60
        sem = _get_pipeline_semaphore()
        logger.info("Pipeline %s waiting for concurrency slot (%d/%d in use)", run_id, sem._value ^ int(os.environ.get("PIPELINE_MAX_CONCURRENT", "2")) - sem._value, int(os.environ.get("PIPELINE_MAX_CONCURRENT", "2")))
        async with sem:
            logger.info("Pipeline %s acquired concurrency slot", run_id)
            try:
                return await asyncio.wait_for(self._execute_pipeline(
                    client_id, raw_input, domain, project_name, start_phase,
                    run_id, org_id, org_slug, plan, is_change_request, memory_context,
                    council_preflight, github_url, designer_spec or {},
                    tech_preferences, model_preference, priority, codebase_mode, existing_schema,
                ), timeout=timeout)
            except asyncio.TimeoutError:
                logger.error("Pipeline %s timed out after %s minutes", run_id, timeout / 60)
                if run_id:
                    await self.ledger.async_update_run_status(run_id, "timeout")
                    await publish_event(run_id, {"type": "pipeline_complete", "status": "timeout", "ts": time.time()})
                return {"run_id": run_id, "status": "timeout"}

    async def _execute_pipeline(self,
                  client_id: str,
                  raw_input: str,
                  domain: str = "general",
                  project_name: Optional[str] = None,
                  start_phase: Optional[str] = None,
                  run_id: Optional[str] = None,
                  org_id: Optional[str] = None,
                  org_slug: Optional[str] = None,
                  plan: Optional[str] = None,
                  is_change_request: bool = False,
                  memory_context: Optional[str] = None,
                  council_preflight: Optional[Dict[str, Any]] = None,
                  github_url: Optional[str] = None,
                  designer_spec: Optional[Dict[str, Any]] = None,
                  tech_preferences: Optional[Dict[str, Any]] = None,
                  model_preference: Optional[str] = None,
                  priority: Optional[str] = None,
                  codebase_mode: Optional[str] = None,
                  existing_schema: Optional[Dict[str, Any]] = None) -> dict:

        run_id = run_id or str(uuid.uuid4())

        # Pre-warm per-org LLM API key cache so synchronous client getters
        # can resolve org-specific keys without an await.
        if org_id:
            try:
                from aether_os.core.llm.client import init_org_llm_context
                await init_org_llm_context(org_id)
            except Exception as _key_exc:
                logger.debug("init_org_llm_context non-fatal: %s", _key_exc)

        # Create project directory
        project_dir = Path.home() / ".aether_os" / "projects" / run_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # D6: Initialize project living memory
        _pm_init(
            project_dir,
            project_name=project_name or _extract_project_name(raw_input, run_id),
            requirement=raw_input,
            domain=domain,
            run_id=run_id,
        )

        if not org_id:
            logger.error("[pipeline] org_id is required to create a run — aborting (run=%s)", run_id)
            raise ValueError("org_id is required: runs without an org bypass quota tracking and billing")

        try:
            from aether_os.core.db_utils import create_run as _create_run
            await _create_run(
                run_id=run_id,
                command=f"factory: {raw_input[:60]}",
                org_id=org_id,
                project_name=project_name or _extract_project_name(raw_input, run_id),
                domain=domain,
                client_id=client_id,
                raw_input=raw_input,
            )
        except Exception as _cr_exc:
            logger.warning("create_run failed, falling back to async_save_run: %s", _cr_exc)
            await self.ledger.async_save_run(run_id, f"factory: {raw_input[:60]}", org_id=org_id, status="running")

        # Persist pre-flight council result to the run record
        if council_preflight:
            try:
                from aether_os.core.db import get_session_factory as _gsf
                from aether_os.core.models import Run as _Run
                from sqlalchemy import update as _sa_update
                _sf = _gsf()
                async with _sf() as _s:
                    await _s.execute(
                        _sa_update(_Run)
                        .where(_Run.id == run_id)
                        .values(council_preflight=council_preflight)
                    )
                    await _s.commit()
            except Exception as _exc:
                logger.warning("Failed to persist council_preflight: %s", _exc)

        # Load org settings (autonomous_mode, decision_mode) so pipeline behaves correctly
        _org_autonomous = False
        if org_id:
            try:
                from aether_os.core.db import get_session_factory
                from aether_os.core.models import Organisation
                from sqlalchemy import select as _sel
                async with get_session_factory()() as _os:
                    _org = (await _os.execute(_sel(Organisation).where(Organisation.id == org_id))).scalar_one_or_none()
                    if _org:
                        _org_autonomous = bool(getattr(_org, "autonomous_mode", False))
            except Exception as _oe:
                logger.debug("Could not load org autonomous_mode: %s", _oe)

        # Accumulated context passed between phases
        accumulated_context = {
            "run_id": run_id,
            "org_id": org_id,
            "org_slug": org_slug or "",
            "plan": plan or "trial",
            "client_id": client_id,
            "raw_input": raw_input,
            "domain": domain,
            "project_name": project_name or _extract_project_name(raw_input, run_id),
            "project_dir": str(project_dir),
            "is_change_request": is_change_request,
            # Cross-run memory context injected from MemoryService (may be "")
            "memory_context": memory_context or "",
            # Optional GitHub repo to fork/clone instead of generating from scratch
            "github_url": github_url or "",
            # Pipeline flow control: "autonomous" skips human approval gates
            "decision_mode": "autonomous" if _org_autonomous else "approval_required",
            # Designer panel selections — forwarded to p04b + p05 for theme/layout
            # Merge tech_preferences into designer_spec if designer_spec has no frontend framework set
            "tech_preferences": tech_preferences or {},
            "model_preference": model_preference or "",
            "priority": priority or "normal",
            "codebase_mode": codebase_mode or "new",
            "existing_schema": existing_schema or {},
        }
        _ds = dict(designer_spec or {})
        _tp = tech_preferences or {}
        if _tp and not _ds.get("frontend", {}).get("framework"):
            _ds.setdefault("frontend", {})["framework"] = _tp.get("frontend", "")
            _ds.setdefault("backend", {})["framework"] = _tp.get("backend", "")
            _ds.setdefault("backend", {})["database"] = _tp.get("database", "")
        accumulated_context["designer_spec"] = _ds

        # Inject per-user learning patterns so every phase can tailor its prompts
        if org_id and client_id:
            try:
                from aether_os.core.services.learning_service import get_user_context
                from aether_os.core.db import get_session_factory
                _sf = get_session_factory()
                async with _sf() as _sess:
                    _learned = await get_user_context(org_id, client_id, _sess)
                if _learned:
                    accumulated_context["user_learning"] = _learned
                    logger.info("Injected %d learning pattern type(s) for %s",
                                len(_learned), client_id)
            except Exception as _le:
                logger.warning("Learning context unavailable — phases will run without personalisation (run=%s): %s", run_id, _le)
        
        # 10-phase consolidated pipeline
        ACTIVE_PHASES = PHASE_SEQUENCE  # All 10 consolidated phases

        phases_to_run = ACTIVE_PHASES
        if start_phase:
            all_phases = PHASE_SEQUENCE
            if start_phase in all_phases:
                phases_to_run = all_phases[all_phases.index(start_phase):]

        # ── Checkpoint restore — resume a failed run from the last completed phase ──
        # If checkpoint_data exists on the Run record, we restore accumulated_context
        # and skip phases that have already completed, so the pipeline continues from
        # the next unfinished phase rather than restarting from p01.
        try:
            from aether_os.core.db import get_session_factory as _gsf_ckpt
            from aether_os.core.models import Run as _Run_ckpt
            _sf_ckpt = _gsf_ckpt()
            async with _sf_ckpt() as _sess_ckpt:
                _run_rec = await _sess_ckpt.get(_Run_ckpt, run_id)
                _ckpt = _run_rec.checkpoint_data if _run_rec else None
            # Schema validation: checkpoint must have both required keys or we ignore it
            # to prevent silent resume-logic breakage on schema drift ([21]).
            if _ckpt and not isinstance(_ckpt, dict):
                logger.warning("[pipeline] Ignoring malformed checkpoint_data (not a dict) for run %s", run_id)
                _ckpt = None
            if _ckpt and not ("last_completed_phase" in _ckpt and "accumulated_context" in _ckpt):
                logger.warning(
                    "[pipeline] Ignoring checkpoint_data with unexpected schema for run %s "
                    "(got keys: %s — expected last_completed_phase + accumulated_context)",
                    run_id, list(_ckpt.keys()),
                )
                _ckpt = None
            if _ckpt and _ckpt.get("last_completed_phase"):
                _last_done = _ckpt["last_completed_phase"]
                _saved_ctx = _ckpt.get("accumulated_context") or {}
                if _last_done in PHASE_SEQUENCE and _saved_ctx:
                    # Restore accumulated_context from checkpoint (overwrite the freshly-built one)
                    accumulated_context.update(_saved_ctx)
                    # Ensure mutable run-level keys stay current
                    accumulated_context["run_id"] = run_id
                    # Slice phases_to_run to start from the phase AFTER last_completed_phase
                    _resume_idx = PHASE_SEQUENCE.index(_last_done) + 1
                    phases_to_run = PHASE_SEQUENCE[_resume_idx:]
                    logger.info(
                        "[pipeline] Resuming run %s from checkpoint after phase %s (%d phases remaining)",
                        run_id, _last_done, len(phases_to_run),
                    )
                    await emit(
                        {"type": "pipeline_resumed", "resumed_after": _last_done,
                         "phases_remaining": len(phases_to_run)},
                        run_id=run_id,
                    )
                else:
                    logger.debug("[pipeline] Checkpoint found but phase %r not in sequence — ignoring", _last_done)
        except Exception as _ckpt_exc:
            logger.warning("[pipeline] Checkpoint restore failed (non-fatal): %s", _ckpt_exc)

        # Aether2Bridge — optional DCSP integration (failure here never blocks pipeline)
        _bridge = None
        _dcsp_url = os.environ.get("DCSP_URL", "")
        if _dcsp_url:
            try:
                from aether_os.integrations.aether2_bridge import Aether2Bridge
                _bridge = Aether2Bridge()
                _bridge.connect(_dcsp_url, os.environ.get("DCSP_API_KEY", ""))
                _bridge.register_pipeline(run_id, list(phases_to_run))
                logger.info("Aether2Bridge connected to %s, monitoring %d phases", _dcsp_url, len(phases_to_run))
            except Exception as _br_exc:
                logger.warning("Aether2Bridge init failed — DCSP callbacks will be dropped for run %s: %s", run_id, _br_exc)
                _bridge = None

        results = {}
        pipeline_start = time.time()

        for phase_name in phases_to_run:
            # Set context vars so LLM calls in this phase can emit to the queue
            run_token   = ACTIVE_RUN_ID.set(run_id)
            phase_token = ACTIVE_PHASE.set(phase_name)
            org_token   = ACTIVE_ORG_ID.set(org_id)
            # Fix 12: also set os.environ for code paths that use os.environ["ACTIVE_ORG_ID"]
            os.environ["ACTIVE_ORG_ID"] = org_id or ""

            # Update state machine
            await self._update_state(run_id, phase_name, "running")
            await emit({"type": "phase_start", "phase": phase_name}, run_id=run_id)

            try:
                # Build phase input with accumulated context
                phase_input = PhaseInput(
                    run_id=run_id,
                    project_id=run_id,
                    phase=phase_name,
                    input_data=accumulated_context,
                    output_dir=str(project_dir),
                    domain=domain,
                    client_id=client_id
                )
                
                # Run phase with timeout (configurable per phase)
                # Look for PHASE_TIMEOUT_<PHASE_NAME> or fallback to PHASE_TIMEOUT_SECONDS/600
                _env_key = f"PHASE_TIMEOUT_{phase_name.upper()}"
                _default_timeout = "600"
                if phase_name == "p05_frontend":
                    # Skip p05 only when frontend is EXPLICITLY disabled; empty means "use default React"
                    _ds = accumulated_context.get("designer_spec") or {}
                    _tp = accumulated_context.get("tech_preferences") or {}
                    _frontend_selection = (
                        (_ds.get("frontend") or {}).get("framework", "")
                        or _tp.get("frontend", "")
                        or accumulated_context.get("frontend", "")
                        or ""
                    )
                    if str(_frontend_selection).lower() in ("none", "no", "n/a"):
                        logger.info(
                            "[pipeline] Skipping p05_frontend — frontend=%r (no UI requested)",
                            _frontend_selection,
                        )
                        results[phase_name] = {
                            "status": "skipped",
                            "output_path": "",
                            "artifacts": {},
                            "metadata": {"skipped_reason": "no_frontend_selected"},
                            "confidence": 1.0,
                            "issues": [],
                        }
                        await self._update_state(run_id, phase_name, "skipped")
                        await emit(
                            {"type": "phase_complete", "phase": phase_name, "status": "skipped"},
                            run_id=run_id,
                        )
                        continue  # finally block handles token reset
                    _default_timeout = "1200"  # BUG-H2: Increase p05 timeout to 20 mins
                elif phase_name == "p11_deployment":
                    _default_timeout = "1800"  # Docker build + vite + pip can exceed 600s on small VPS

                _phase_timeout = float(os.environ.get(
                    _env_key,
                    os.environ.get("PHASE_TIMEOUT_SECONDS", _default_timeout)
                ))

                if _bridge:
                    try:
                        _bridge.report_stage_start(run_id, phase_name)
                    except Exception as _bse:
                        logger.debug("bridge.report_stage_start non-fatal: %s", _bse)
                phase_result = await asyncio.wait_for(
                    self._run_phase(phase_name, phase_input),
                    timeout=_phase_timeout)
                
                results[phase_name] = phase_result

                # FIX-020: If phase escalated, wait for human approval before continuing
                if (
                    phase_result.get("status") == "escalated"
                    and accumulated_context.get("decision_mode") != "autonomous"
                ):
                    _escalation_reason = str((phase_result.get("issues") or ["unknown"])[:1][0])
                    # Fix 16 + Fix 28: notify run owner of phase escalation + set deadline in metadata
                    if org_id:
                        async def _notify_escalation(_rid=run_id, _oid=org_id, _pn=phase_name, _reason=_escalation_reason, _pname=accumulated_context.get("project_name") or f"run-{run_id[:8]}"):
                            try:
                                from aether_os.core.db import get_session_factory as _gsf_esc
                                from aether_os.core.models import Notification as _Notif_esc, Run as _Run_esc
                                _notif_esc = _Notif_esc(
                                    org_id=_oid,
                                    type="phase_escalation_required",
                                    title=f"🔔 Approval required: {_pn} in {_pname}",
                                    message=f"Phase {_pn} escalated: {_reason[:200]}. Auto-approves in 10 minutes.",
                                    link=f"/dashboard/runs/{_rid}",
                                )
                                async with _gsf_esc()() as _s_esc:
                                    _s_esc.add(_notif_esc)
                                    # Previously tried to write a pending_escalations dict to
                                    # _run_esc.metadata — but Run has no metadata column.
                                    # The notification + SSE event already carry the deadline,
                                    # so we skip the (broken) persistence here.
                                    await _s_esc.commit()
                            except Exception as _ne_esc:
                                logger.debug("[pipeline] escalation notification failed: %s", _ne_esc)
                        _esc_t = asyncio.create_task(_notify_escalation())
                        self._background_tasks.add(_esc_t)
                        _esc_t.add_done_callback(self._background_tasks.discard)
                    await self._await_human_approval(
                        run_id=run_id,
                        org_id=org_id or "",
                        phase_name=phase_name,
                        reason=_escalation_reason,
                    )

                # Emit file_written events for every file produced by this phase
                _phase_dir = project_dir / phase_name
                if _phase_dir.exists():
                    # Patterns to exclude
                    exclude_patterns = [
                        "**/node_modules/**", "**/dist/**", "**/.git/**", 
                        "**/__pycache__/**", "**/*.pyc",
                    ]
                    
                    for _f in _phase_dir.rglob("*"):
                        if _f.is_file():
                            rel_path = str(_f.relative_to(project_dir))
                            
                            # Simple filter
                            if any(p in rel_path for p in ["node_modules/", ".git/", "dist/", "__pycache__/"]) or rel_path.endswith(".pyc"):
                                continue

                            try:
                                _sz = _f.stat().st_size
                            except OSError:
                                _sz = 0
                            await emit({
                                "type": "file_written",
                                "phase": phase_name,
                                "path": rel_path,
                                "size": _sz,
                            }, run_id=run_id)

                # Add phase output to context for next phase to use
                accumulated_context[f"{phase_name}_output"] = phase_result.get("artifacts", {})
                accumulated_context[f"{phase_name}_path"] = phase_result.get("output_path", "")

                # Sliding context window: append a compact phase summary so every
                # downstream phase receives structured facts, not just raw paths.
                _summaries = accumulated_context.setdefault("phase_summaries", [])
                _meta = phase_result.get("metadata", {}) or {}
                _artifacts = []
                _p_dir = project_dir / phase_name
                if _p_dir.exists():
                    _artifacts = [f.name for f in _p_dir.rglob("*") if f.is_file()][:10]
                _summaries.append({
                    "phase": phase_name,
                    "status": phase_result.get("status", "completed"),
                    "output_path": phase_result.get("output_path", ""),
                    "key_artifacts": _artifacts,
                    "decisions": _meta.get("decisions", []),
                    "open_issues": (phase_result.get("issues") or [])[:5],
                    "confidence": _meta.get("confidence", phase_result.get("confidence")),
                })

                # Persist checkpoint after every phase so a crashed run can resume
                await save_checkpoint(run_id, phase_name, accumulated_context)

                # After p07_testing: Quality Gate (Fix 9)
                if phase_name == "p07_testing":
                    from aether_os.core.quality.metrics import score_project
                    from aether_os.core.errors import PipelineBlockedError
                    
                    for attempt in range(1, 4):
                        quality = score_project(project_dir)
                        if quality.total >= 80:
                            logger.info("[quality] Gate passed: %.1f%%", quality.total)
                            await emit({"type": "quality_gate_passed", "score": quality.total}, run_id=run_id)
                            break
                        
                        if attempt < 3:
                            msg = f"Quality score {quality.total:.1f}% < 80% — running self-healing attempt {attempt}/3"
                            logger.info("[quality] %s", msg)
                            await emit({"type": "llm_chunk", "phase": "quality_gate", "text": msg}, run_id=run_id)
                            # Re-run p07b_self_healing to try and improve quality
                            await self._run_phase("p07b_self_healing", phase_input)
                        else:
                            logger.error("[quality] Gate failed after 3 attempts. Final score: %.1f%%", quality.total)
                            # Fix 16: notify run owner — self_healing_exhausted
                            if org_id:
                                async def _notify_self_healing_exhausted(_rid=run_id, _oid=org_id, _pname=accumulated_context.get("project_name") or f"run-{run_id[:8]}"):
                                    try:
                                        from aether_os.core.db import get_session_factory as _gsf_she
                                        from aether_os.core.models import Notification as _Notif_she
                                        _notif_she = _Notif_she(
                                            org_id=_oid,
                                            type="self_healing_exhausted",
                                            title=f"⚠ Self-healing exhausted for {_pname}",
                                            message="All 3 self-healing attempts failed. Quality gate not met.",
                                            link=f"/dashboard/runs/{_rid}",
                                        )
                                        async with _gsf_she()() as _s_she:
                                            _s_she.add(_notif_she)
                                            await _s_she.commit()
                                    except Exception as _ne_she:
                                        logger.debug("[pipeline] self_healing_exhausted notification failed: %s", _ne_she)
                                _she_t = asyncio.create_task(_notify_self_healing_exhausted())
                                self._background_tasks.add(_she_t)
                                _she_t.add_done_callback(self._background_tasks.discard)
                            raise PipelineBlockedError(
                                f"Quality gate failed after 3 improvement attempts. Final score: {quality.total:.1f}%"
                            )

                # If p11_deployment produced a live_url, persist it to the runs table
                if phase_name == "p11_deployment":
                    _live_url = phase_result.get("metadata", {}).get("live_url")
                    if _live_url:
                        try:
                            from aether_os.core.db import get_session_factory as _gsf_fp
                            from aether_os.core.models import Run as _Run_fp
                            from sqlalchemy import update as _sa_upd_fp
                            async with _gsf_fp()() as _sess_fp:
                                await _sess_fp.execute(
                                    _sa_upd_fp(_Run_fp).where(_Run_fp.id == run_id).values(live_url=_live_url)
                                )
                                await _sess_fp.commit()
                            accumulated_context["live_url"] = _live_url
                        except Exception as _e:
                            logger.warning("Could not persist live_url: %s", _e)

                # After p01 completes, extract project name from intake JSON
                if phase_name == "p01_intake_requirements":
                    import json as _json_p01
                    _intake_path = project_dir / "p01_intake_requirements" / "intake" / "intake.json"
                    try:
                        if _intake_path.exists():
                            _intake = _json_p01.loads(_intake_path.read_text())
                            _client_id = _intake.get("client_id", "")
                            if _client_id and _client_id != "unknown":
                                from aether_os.core.db import get_session_factory as _gsf_p01
                                from aether_os.core.models import Run as _Run_p01
                                from sqlalchemy import update as _sa_up_p01
                                async with _gsf_p01()() as _s_p01:
                                    await _s_p01.execute(
                                        _sa_up_p01(_Run_p01)
                                        .where(_Run_p01.id == run_id)
                                        .values(project_name=_client_id.replace("-", " ").replace("_", " ").title())
                                    )
                                    await _s_p01.commit()
                                accumulated_context["project_name"] = _client_id
                                logger.info("[pipeline] project_name updated from p01: %s", _client_id)
                    except Exception as _exc_p01:
                        logger.debug("[pipeline] Could not extract project name from p01: %s", _exc_p01)

                    # Spec review gate: pause here if decision_mode != "autonomous"
                    # Gate logic + LLM pre-critique extracted to spec_review_gate.py
                    if accumulated_context.get("decision_mode") != "autonomous":
                        try:
                            from aether_os.orchestrator.spec_review_gate import run_spec_review_gate
                            await run_spec_review_gate(
                                run_id=run_id,
                                accumulated_context=accumulated_context,
                                emit_fn=emit,
                                get_control_fn=get_control,
                                set_control_fn=set_control,
                                publish_event_fn=publish_event,
                            )
                        except RuntimeError:
                            raise
                        except Exception as _sr_exc:
                            logger.warning("[pipeline] Spec review gate error (non-fatal): %s", _sr_exc)

                # After p00_research: read build_profile from design_brief.json
                # and store in accumulated_context so all downstream phases
                # receive the stack selection without re-running classification.
                if phase_name == "p00_research":
                    import json as _json_p00
                    _brief_path = project_dir / "p00_research" / "design_brief.json"
                    if _brief_path.exists():
                        try:
                            _brief = _json_p00.loads(_brief_path.read_text())
                            _bp = _brief.get("build_profile")
                            if _bp:
                                accumulated_context["build_profile"] = _bp
                                logger.info(
                                    "[pipeline] build_profile loaded: %s (backend=%s, arch=%s)",
                                    _bp.get("name"), _bp.get("backend_lang"),
                                    _bp.get("architecture"),
                                )
                        except Exception as _e:
                            logger.warning("[pipeline] Failed to load build_profile from design_brief: %s", _e)

                # After p00c: read service_map.json and store in accumulated_context.
                # go_generator and node_generator use this to produce N service dirs
                # instead of a single monolith when architecture == "microservices".
                if phase_name == "p00c_architecture_planner":
                    import json as _json_p00c
                    _sm_path = project_dir / "p00c_architecture_planner" / "service_map.json"
                    if _sm_path.exists():
                        try:
                            _sm = _json_p00c.loads(_sm_path.read_text())
                            if _sm.get("services"):
                                accumulated_context["service_map"] = _sm
                                logger.info(
                                    "[pipeline] service_map loaded: %d services, bus=%s",
                                    len(_sm["services"]),
                                    _sm.get("message_bus", ""),
                                )
                        except Exception as _e:
                            logger.warning("[pipeline] Failed to load service_map: %s", _e)

                # Eagerly load architecture.json after p02 so all downstream
                # phases receive it via data.get("architecture_json", {}).
                if phase_name == "p02_architecture":
                    import json as _json
                    # Try the explicit output_path first, then scan the phase dir
                    _arch_candidates = []
                    _op = phase_result.get("output_path", "")
                    if _op:
                        _arch_candidates.append(Path(_op))
                    _phase_dir = project_dir / "p02_architecture"
                    _arch_candidates.append(_phase_dir / "architecture.json")
                    for _cand in _arch_candidates:
                        if _cand.exists():
                            try:
                                accumulated_context["architecture_json"] = _json.loads(
                                    _cand.read_text()
                                )
                                accumulated_context["p02_architecture_path"] = str(_cand)
                                logger.info("[pipeline] architecture_json loaded from %s", _cand)
                                break
                            except Exception as _e:
                                logger.warning("[pipeline] Failed to load architecture_json from %s: %s",
                                               _cand, _e)
                    else:
                        logger.warning("[pipeline] architecture.json not found after p02 — "
                                       "downstream phases will use their own fallbacks")

                # Load integration_map.json after p01b so all downstream phases receive it
                if phase_name == "p01b_integration_discovery":
                    import json as _json_p01b
                    _p01b_dir = project_dir / "p01b_integration_discovery"
                    _imap_path = _p01b_dir / "integration_map.json"
                    if _imap_path.exists():
                        try:
                            accumulated_context["integration_map"] = _json_p01b.loads(_imap_path.read_text())
                            logger.info("[pipeline] integration_map loaded from %s", _imap_path)
                        except Exception as _e:
                            logger.warning("[pipeline] Failed to load integration_map: %s", _e)

                # Load permission_model.json after p02c so all downstream phases receive it
                if phase_name == "p02c_permission_modeling":
                    import json as _json_p02c
                    _p02c_dir = project_dir / "p02c_permission_modeling"
                    _perm_path = _p02c_dir / "permission_model.json"
                    if _perm_path.exists():
                        try:
                            accumulated_context["permission_model"] = _json_p02c.loads(_perm_path.read_text())
                            logger.info("[pipeline] permission_model loaded from %s", _perm_path)
                        except Exception as _e:
                            logger.warning("[pipeline] Failed to load permission_model: %s", _e)

                # Load domain_ir.json after p02b so all downstream phases receive it
                if phase_name == "p02b_domain_ir":
                    import json as _json
                    _ir_path_str = (
                        phase_result.get("metadata", {}).get("domain_ir_path", "")
                        or phase_result.get("output_path", "")
                    )
                    _ir_candidates = []
                    if _ir_path_str:
                        _ir_candidates.append(Path(_ir_path_str))
                    _ir_candidates.append(project_dir / "p02b_domain_ir" / "domain_ir.json")
                    for _cand in _ir_candidates:
                        if _cand.exists():
                            try:
                                accumulated_context["domain_ir_path"] = str(_cand)
                                logger.info("[pipeline] domain_ir_path loaded from %s", _cand)
                                break
                            except Exception as _e:
                                logger.warning("[pipeline] Failed to load domain_ir from %s: %s", _cand, _e)

                # GraphRAG: build knowledge graph from architecture JSON after p02
                if phase_name == "p02_architecture":
                    try:
                        from aether_os.core.memory.knowledge_graph import KnowledgeGraph as _KG
                        _arch = accumulated_context.get("architecture_json", {})
                        _kg = _KG()
                        _domain = accumulated_context.get("domain", "general")
                        _kg.add_node("domain", "Domain", {"name": _domain})
                        _ts = _arch.get("tech_stack", {})
                        for _k, _v in _ts.items():
                            _nid = f"tech:{_k}:{_v}"
                            _kg.add_node(_nid, "Technology", {"layer": _k, "choice": _v})
                            _kg.add_edge("domain", _nid, "USES")
                        for _ep in _arch.get("api_endpoints", [])[:20]:
                            _eid = f"endpoint:{_ep.get('method','GET')}:{_ep.get('path','/')}"
                            _kg.add_node(_eid, "Endpoint", {"method": _ep.get("method"), "path": _ep.get("path"), "auth": _ep.get("auth")})
                            _kg.add_edge("domain", _eid, "IMPLEMENTS")
                        for _tbl in _arch.get("database_schema", [])[:15]:
                            _mid = f"model:{_tbl.get('table', _tbl.get('name',''))}"
                            _kg.add_node(_mid, "Model", {"table": _tbl.get("table", _tbl.get("name")), "columns": len(_tbl.get("columns", []))})
                            _kg.add_edge("domain", _mid, "DEPENDS_ON")
                        # Store compact graph context for downstream phases
                        _endpoints = [f"{e.get('method')} {e.get('path')}" for e in _arch.get("api_endpoints", [])[:10]]
                        _models = [t.get("table", t.get("name")) for t in _arch.get("database_schema", [])[:8]]
                        accumulated_context["graph_context"] = {
                            "domain": _domain,
                            "tech_stack": _ts,
                            "endpoints": _endpoints,
                            "models": _models,
                            "graph_stats": _kg.stats(),
                        }
                        # Persist graph for this run
                        _kg_path = str(project_dir / "knowledge_graph.gpickle")
                        _kg.persist(_kg_path)
                        accumulated_context["knowledge_graph_path"] = _kg_path
                        logger.info("[RAG] Knowledge graph built: %d nodes, %d endpoints, %d models",
                                    _kg.stats()["node_count"], len(_endpoints), len(_models))
                    except Exception as _kg_exc:
                        logger.warning("[RAG] Knowledge graph build failed: %s", _kg_exc)

                # After p04_backend: merge generated code into p03 scaffolding tree (S11 fix)
                if phase_name == "p04_backend":
                    import shutil as _shutil
                    _p04_src = project_dir / "p04_backend" / "backend_codegen" / "src"
                    # Find the scaffolding directory (first subdir of p03_scaffolding)
                    _p03_dir = project_dir / "p03_scaffolding"
                    _scaffold_dirs = [d for d in _p03_dir.iterdir() if d.is_dir()] if _p03_dir.exists() else []
                    if _p04_src.exists() and _scaffold_dirs:
                        _scaffold_root = _scaffold_dirs[0]
                        _dest_src = _scaffold_root / "src"
                        _dest_src.mkdir(parents=True, exist_ok=True)
                        # Copy entire tree (including routers/, middleware/ subdirs)
                        _shutil.copytree(str(_p04_src), str(_dest_src), dirs_exist_ok=True,
                                         ignore=_shutil.ignore_patterns("__pycache__", "*.pyc"))
                        logger.info("[pipeline] S11: merged p04 src tree → %s", _dest_src)
                        # Also expose the merged src path for downstream phases
                        accumulated_context["backend_src_dir"] = str(_dest_src)
                        accumulated_context["backend_main_py"] = str(_dest_src / "main.py")
                    else:
                        # Fallback: expose p04 src directly
                        if _p04_src.exists():
                            accumulated_context["backend_src_dir"] = str(_p04_src)
                            accumulated_context["backend_main_py"] = str(_p04_src / "main.py")

                    # Propagate api_routes.json path so p05 can wire real endpoints
                    _routes_candidate = project_dir / "p04_backend" / "backend_codegen" / "api_routes.json"
                    if not _routes_candidate.exists():
                        _routes_candidate = project_dir / "p04_backend" / "api_routes.json"
                    if _routes_candidate.exists():
                        accumulated_context["api_routes_path"] = str(_routes_candidate)
                        logger.info("[pipeline] api_routes_path → %s", _routes_candidate)

                    # Pattern library injection — apply matching code patterns
                    # (WebSocket, file upload, Stripe, RBAC) based on domain IR
                    try:
                        from aether_os.phases.patterns import PatternSelector as _PS
                        _ir_for_patterns = accumulated_context.get("domain_ir", {})
                        if not _ir_for_patterns:
                            _ir_path_for_patterns = accumulated_context.get("domain_ir_path", "")
                            if _ir_path_for_patterns:
                                import json as _j
                                from pathlib import Path as _P
                                try:
                                    _ir_for_patterns = _j.loads(_P(_ir_path_for_patterns).read_text())
                                except Exception as exc:
                                    logger.debug("Pattern library: failed to read domain_ir file (non-fatal): %s", exc)
                        if _ir_for_patterns:
                            _ps = _PS(_ir_for_patterns)
                            _applied = _ps.apply_all(project_dir)
                            if _applied:
                                accumulated_context["applied_patterns"] = list(_applied.keys())
                                logger.info("[pipeline] Pattern library: applied %s", list(_applied.keys()))
                    except Exception as _pat_exc:
                        logger.warning("[pipeline] Pattern library injection failed (non-fatal): %s", _pat_exc)

                    # BackendAuditCouncil — blocking re-generation feedback loop.
                    # If avg_score < threshold, council issues are injected into
                    # accumulated_context and p04_backend re-runs (max 2 retries).
                    _BAC_THRESHOLD = float(os.environ.get("COUNCIL_THRESHOLD", "0.70"))
                    _bac_main_candidates = [
                        project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
                        project_dir / "p04_backend" / "src" / "main.py",
                        project_dir / "src" / "main.py",
                    ]
                    _bac_main_py = next((p for p in _bac_main_candidates if p.exists()), None)
                    if _bac_main_py:
                        for _bac_attempt in range(3):  # initial review + max 2 re-gens
                            try:
                                from aether_os.core.council.council_reviewer import run_council
                                import json as _bac_cj
                                from dataclasses import asdict as _bac_asdict
                                _bac_src = _bac_main_py.read_text()
                                _bac_report = await asyncio.wait_for(
                                    run_council(
                                        _bac_src, run_id,
                                        accumulated_context.get("project_name", "Project"),
                                        domain or "general",
                                    ),
                                    timeout=90.0,
                                )
                                _bac_report_dict = _bac_asdict(_bac_report)
                                (project_dir / "council_review.json").write_text(
                                    _bac_cj.dumps(_bac_report_dict, indent=2)
                                )
                                accumulated_context["council_review"] = _bac_report_dict
                                await emit({
                                    "type": "council_review_complete",
                                    "score": _bac_report.average_score,
                                    "issues": len(_bac_report.consensus_issues),
                                    "attempt": _bac_attempt + 1,
                                }, run_id=run_id)
                                logger.info(
                                    "[BackendAuditCouncil] run %s attempt %d: avg_score=%.2f issues=%d",
                                    run_id, _bac_attempt + 1,
                                    _bac_report.average_score, len(_bac_report.consensus_issues),
                                )

                                if _bac_report.average_score >= _BAC_THRESHOLD or _bac_attempt >= 2:
                                    break  # score acceptable or retry cap reached

                                # Score below threshold — inject issues and re-run p04_backend
                                _bac_issues_text = "\n".join(
                                    f"- {iss}" for iss in (_bac_report.consensus_issues or [])
                                )
                                accumulated_context["council_feedback"] = (
                                    f"BackendAuditCouncil scored {_bac_report.average_score:.2f}/1.0 "
                                    f"(attempt {_bac_attempt + 1}). Fix before generating:\n"
                                    f"{_bac_issues_text}"
                                )
                                await emit({
                                    "type": "council_p04_retry",
                                    "attempt": _bac_attempt + 1,
                                    "score": _bac_report.average_score,
                                }, run_id=run_id)
                                logger.info(
                                    "[BackendAuditCouncil] score %.2f < %.2f — re-running p04_backend (retry %d/2)",
                                    _bac_report.average_score, _BAC_THRESHOLD, _bac_attempt + 1,
                                )
                                _bac_retry_input = PhaseInput(
                                    run_id=run_id,
                                    project_id=run_id,
                                    phase="p04_backend",
                                    input_data=accumulated_context,
                                    output_dir=str(project_dir),
                                    domain=domain,
                                    client_id=client_id,
                                )
                                try:
                                    _bac_retry_result = await asyncio.wait_for(
                                        self._run_phase("p04_backend", _bac_retry_input),
                                        timeout=600.0,
                                    )
                                    results["p04_backend"] = _bac_retry_result
                                    # Re-do S11 merge so downstream phases see improved code
                                    import shutil as _bac_shutil
                                    _bac_p04_src = project_dir / "p04_backend" / "backend_codegen" / "src"
                                    _bac_p03_dir = project_dir / "p03_scaffolding"
                                    _bac_scaffold_dirs = (
                                        [d for d in _bac_p03_dir.iterdir() if d.is_dir()]
                                        if _bac_p03_dir.exists() else []
                                    )
                                    if _bac_p04_src.exists() and _bac_scaffold_dirs:
                                        _bac_dest = _bac_scaffold_dirs[0] / "src"
                                        _bac_dest.mkdir(parents=True, exist_ok=True)
                                        _bac_shutil.copytree(
                                            str(_bac_p04_src), str(_bac_dest),
                                            dirs_exist_ok=True,
                                            ignore=_bac_shutil.ignore_patterns("__pycache__", "*.pyc"),
                                        )
                                        accumulated_context["backend_src_dir"] = str(_bac_dest)
                                        accumulated_context["backend_main_py"] = str(_bac_dest / "main.py")
                                        logger.info("[BackendAuditCouncil] S11 re-merge → %s", _bac_dest)
                                    # Refresh main.py reference for next council pass
                                    _bac_main_py = next(
                                        (p for p in _bac_main_candidates if p.exists()), None
                                    )
                                    if not _bac_main_py:
                                        logger.warning("[BackendAuditCouncil] main.py missing after retry")
                                        break
                                except Exception as _bac_retry_exc:
                                    logger.warning(
                                        "[BackendAuditCouncil] p04 retry failed: %s — stopping loop",
                                        _bac_retry_exc,
                                    )
                                    break
                            except Exception as _bac_exc:
                                logger.warning("[BackendAuditCouncil] council failed (non-fatal): %s", _bac_exc)
                                break
                    else:
                        logger.debug("[BackendAuditCouncil] main.py not found, skipping")

                # Update state
                p_status = "passed" if (phase_result.get("status") == "passed") else "completed"
                await self._update_state(run_id, phase_name, p_status)
                # D6: Record phase completion in project memory
                _pm_update(project_dir, {
                    f"phase_{phase_name}": {
                        "status": p_status,
                        "duration_s": phase_result.get("duration_s"),
                    }
                })
                await emit({
                    "type": "phase_complete",
                    "phase": phase_name,
                    "status": p_status,
                    "duration": phase_result.get("duration_s"),
                }, run_id=run_id)
                if _bridge:
                    try:
                        _elapsed = int(phase_result.get("duration_s") or 0)
                        _bridge.report_stage_complete(run_id, phase_name, _elapsed, success=True)
                    except Exception as _bce:
                        logger.debug("bridge.report_stage_complete non-fatal: %s", _bce)

            except asyncio.TimeoutError:
                logger.warning(f"{phase_name} timed out, continuing")
                await self._update_state(run_id, phase_name, "timeout")
                results[phase_name] = {"status": "timeout", "output_path": ""}
                await emit({"type": "phase_complete", "phase": phase_name, "status": "timeout"}, run_id=run_id)
                if _bridge:
                    try:
                        _bridge.report_failure(run_id, phase_name, "Phase timed out")
                        _bridge.report_stage_complete(run_id, phase_name, int(_phase_timeout), success=False)
                    except Exception as _btoe:
                        logger.debug("bridge.report_failure(timeout) non-fatal: %s", _btoe)
                if phase_name in CRITICAL_PHASES:
                    logger.error("Critical phase %s timed out — aborting pipeline %s", phase_name, run_id)
                    await self.ledger.async_update_run_status(run_id, "failed")
                    # Fix 62: persist finished_at on pipeline abort
                    try:
                        from aether_os.core.db import get_session_factory as _gsf_fa
                        from aether_os.core.models import Run as _Run_fa
                        async with _gsf_fa()() as _s_fa:
                            _r_fa = await _s_fa.get(_Run_fa, run_id)
                            if _r_fa:
                                _r_fa.finished_at = time.time()
                                await _s_fa.commit()
                    except Exception as exc:
                        logger.debug("finished_at persist failed on timeout (non-fatal): %s", exc)
                    await publish_event(run_id, {"type": "pipeline_complete", "status": "failed",
                                                      "error": f"Critical phase {phase_name} timed out", "ts": time.time()})

                    return {"run_id": run_id, "status": "failed", "error": f"Critical phase {phase_name} timed out"}

            except Exception as e:
                logger.error(f"{phase_name} failed: {e}")
                await self._update_state(run_id, phase_name, "failed")
                results[phase_name] = {"status": "failed", "error": str(e), "output_path": ""}
                await emit({"type": "phase_complete", "phase": phase_name, "status": "failed",
                            "error": str(e)}, run_id=run_id)
                if _bridge:
                    try:
                        _bridge.report_failure(run_id, phase_name, str(e))
                        _bridge.report_stage_complete(run_id, phase_name, 0, success=False)
                    except Exception as _bfe:
                        logger.debug("bridge.report_failure non-fatal: %s", _bfe)
                if phase_name in CRITICAL_PHASES:
                    logger.error("Critical phase %s failed — aborting pipeline %s", phase_name, run_id)
                    await self.ledger.async_update_run_status(run_id, "failed")
                    # Fix 62: persist finished_at on pipeline abort
                    try:
                        from aether_os.core.db import get_session_factory as _gsf_fb
                        from aether_os.core.models import Run as _Run_fb
                        async with _gsf_fb()() as _s_fb:
                            _r_fb = await _s_fb.get(_Run_fb, run_id)
                            if _r_fb:
                                _r_fb.finished_at = time.time()
                                await _s_fb.commit()
                    except Exception as exc:
                        logger.debug("finished_at persist failed on phase abort (non-fatal): %s", exc)
                    await publish_event(run_id, {"type": "pipeline_complete", "status": "failed",
                                                  "error": f"Critical phase {phase_name} failed: {e}", "ts": time.time()})

                    return {"run_id": run_id, "status": "failed", "error": f"Critical phase {phase_name} failed: {e}"}

            finally:
                # Reset context vars after each phase
                ACTIVE_RUN_ID.reset(run_token)
                ACTIVE_PHASE.reset(phase_token)

            # ── Control signal check after each phase ──────────────────────
            control = await get_control(run_id)
            if control == "cancel":
                logger.info("Pipeline %s cancelled after phase %s", run_id, phase_name)
                await self.ledger.async_update_run_status(run_id, "cancelled")
                # Fix 62: persist finished_at on cancel (ORM, SQLite-safe)
                try:
                    from aether_os.core.db import get_session_factory as _gsf_canc
                    from aether_os.core.models import Run as _Run_canc
                    async with _gsf_canc()() as _s_canc:
                        _r_canc = await _s_canc.get(_Run_canc, run_id)
                        if _r_canc:
                            _r_canc.finished_at = time.time()
                            await _s_canc.commit()
                except Exception as exc:
                    logger.debug("finished_at persist failed on cancel (non-fatal): %s", exc)
                await publish_event(run_id, {"type": "pipeline_complete", "status": "cancelled", "ts": time.time()})
                return {
                    "run_id": run_id, "status": "cancelled",
                    "phases": results, "output_dir": str(project_dir),
                }
            if control == "pause":
                logger.info("Pipeline %s paused after phase %s", run_id, phase_name)
                await self.ledger.async_update_run_status(run_id, "paused")
                while await get_control(run_id) == "pause":
                    await asyncio.sleep(2)
                if await get_control(run_id) == "cancel":
                    await self.ledger.async_update_run_status(run_id, "cancelled")
                    return {
                        "run_id": run_id, "status": "cancelled",
                        "phases": results, "output_dir": str(project_dir),
                    }
                await self.ledger.async_update_run_status(run_id, "running")

        # Mark run as complete — use "council_review" so the DeliveryCouncil background
        # task (below) writes the real final status ("completed" or "needs_review").
        await self._update_state(run_id, "pipeline", "complete")
        await self.ledger.async_update_run_status(run_id, "council_review")

        # Auto-start the generated app via the HTTP layer.
        # Import the router function via a service shim so the orchestrator does not
        # directly depend on the HTTP router module (architectural fix [14]).
        async def _auto_start_app():
            try:
                from aether_os.core.services.run_app_service import _launch_generated_app
                _system_user = {"org_id": org_id, "user_id": "system", "role": "admin", "email": "system@aetheros.internal"}
                result = await _launch_generated_app(run_id=run_id, user=_system_user)
                logger.info("Auto-started generated app for run %s: %s", run_id, result)
                await publish_event(run_id, {
                    "type": "app_started",
                    "run_id": run_id,
                    "port": result.get("port"),
                    "mode": result.get("mode", "backend"),
                    "preview_url": "/app-preview/",
                })
            except Exception as _e:
                logger.warning("Auto-start generated app failed for run %s: %s", run_id, _e)
        _ast = asyncio.create_task(_auto_start_app())
        self._background_tasks.add(_ast)
        _ast.add_done_callback(self._background_tasks.discard)

        duration = time.time() - pipeline_start

        # LLM Council delivery check (background — stores result and flags run if quality fails)
        _dc_task = asyncio.create_task(delivery_council_check(
            run_id=run_id,
            project_name=project_name,
            raw_input=raw_input,
            domain=domain,
            results=results,
            org_id=org_id,
            accumulated_context=accumulated_context,
        ))
        self._background_tasks.add(_dc_task)
        _dc_task.add_done_callback(self._background_tasks.discard)

        # Emit pipeline_complete immediately so SSE clients are not blocked.
        # Status is "council_review" until the DeliveryCouncil background task completes.
        # Fix 62: persist finished_at at pipeline completion (ORM, SQLite-safe)
        try:
            from aether_os.core.db import get_session_factory as _gsf_fin
            from aether_os.core.models import Run as _Run_fin
            async with _gsf_fin()() as _s_fin:
                _r_fin = await _s_fin.get(_Run_fin, run_id)
                if _r_fin:
                    _r_fin.finished_at = time.time()
                    await _s_fin.commit()
        except Exception as exc:
            logger.debug("finished_at persist failed on pipeline completion (non-fatal): %s", exc)
        _complete_event = {
            "type": "pipeline_complete",
            "status": "council_review",
            "duration": round(duration, 1),
            "ts": time.time(),
        }
        await publish_event(run_id, _complete_event)

        # Create in-app notification for org members
        if org_id:
            async def _create_completion_notification():
                try:
                    from aether_os.core.db import get_session_factory as _gsf_n
                    from aether_os.core.models import Notification as _Notif
                    _pname = accumulated_context.get("project_name") or f"run-{run_id[:8]}"
                    _notif = _Notif(
                        org_id=org_id,
                        type="pipeline_complete",
                        title=f"✅ {_pname} is ready",
                        message=f"Factory run completed in {round(duration, 1)}s across {len(phases_to_run)} phases.",
                        link=f"/dashboard/runs/{run_id}",
                    )
                    async with _gsf_n()() as _s:
                        _s.add(_notif)
                        await _s.commit()
                except Exception as _ne:
                    logger.debug("[pipeline] notification creation failed: %s", _ne)
            _n_task = asyncio.create_task(_create_completion_notification())
            self._background_tasks.add(_n_task)
            _n_task.add_done_callback(self._background_tasks.discard)

        # T5-01: Deliver webhook to org subscribers (background, non-blocking)
        if org_id:
            async def _fire_completion_webhook():
                try:
                    from aether_os.core.webhooks.delivery import deliver_event as _wh_deliver
                    await _wh_deliver(
                        org_id=org_id,
                        event_type="pipeline.complete",
                        payload={
                            "run_id": run_id,
                            "status": "completed",
                            "duration_s": round(duration, 1),
                            "phases": list(results.keys()),
                        },
                    )
                except Exception as _wh_exc:
                    logger.debug("[pipeline] webhook delivery skipped: %s", _wh_exc)
            _wh_t = asyncio.create_task(_fire_completion_webhook())
            self._background_tasks.add(_wh_t)
            _wh_t.add_done_callback(self._background_tasks.discard)

        # ── Extract and persist learning patterns (background, non-blocking) ────
        _lt = asyncio.create_task(extract_learning(
            run_id=run_id,
            org_id=org_id,
            client_id=client_id,
            domain=domain,
            results=results,
            accumulated_context=accumulated_context,
        ))
        self._background_tasks.add(_lt)
        _lt.add_done_callback(self._background_tasks.discard)

        # D6: Finalize project living memory
        _pm_update(project_dir, {"tech_stack": accumulated_context.get("architecture_json", {}).get("tech_stack", {})})
        _pm_changelog(project_dir, f"Pipeline completed in {round(duration, 1)}s — {len(phases_to_run)} phases", author="system")

        # Schedule Redis key cleanup after 5 minutes (B3 + B5: store task ref)
        async def _cleanup():
            await asyncio.sleep(300)
            await clear_run(run_id)
            self._background_tasks.discard(asyncio.current_task())
        _t = asyncio.create_task(_cleanup())
        self._background_tasks.add(_t)
        _t.add_done_callback(self._background_tasks.discard)

        # ── Store outcome in cross-run memory for future learning (background) ──
        _t2 = asyncio.create_task(store_run_memory(
            run_id=run_id,
            org_id=org_id,
            raw_input=raw_input,
            domain=domain,
            results=results,
        ))
        self._background_tasks.add(_t2)
        _t2.add_done_callback(self._background_tasks.discard)

        # ── PART 2: Embed artifacts for semantic search (background, non-blocking)
        _t3 = asyncio.create_task(embed_artifacts(
            run_id=run_id,
            project_dir=project_dir,
            results=results,
            org_id=org_id,
        ))
        self._background_tasks.add(_t3)
        _t3.add_done_callback(self._background_tasks.discard)

        # ── PART 3: Upload artifacts to S3 (background, non-blocking)
        _t4 = asyncio.create_task(upload_to_s3(run_id=run_id, project_dir=project_dir))
        self._background_tasks.add(_t4)
        _t4.add_done_callback(self._background_tasks.discard)

        return {
            "run_id": run_id,
            "project_id": run_id,  # In this refactored version, run_id is used for project_dir
            "status": "complete",
            "phases": results,
            "output_dir": str(project_dir),
            "duration_seconds": round(duration, 2),
            "phase_count": len(phases_to_run)
        }

    async def _run_phase(self, phase_name: str, phase_input: PhaseInput) -> dict:
        """Execute a single phase via its supervisor."""
        supervisor = _load_supervisor(phase_name)
        if not supervisor:
            logger.warning(
                "[pipeline] No supervisor mapped for phase %r — skipping. "
                "Check PHASE_SUPERVISORS in factory_pipeline.py.",
                phase_name,
            )
            return {"status": "skipped", "output_path": "", "artifacts": {}, "metadata": {},
                    "warning": f"No supervisor mapped for phase {phase_name!r}"}

        start_t = time.time()
        try:
            logger.info("[pipeline] %s starting (project_id=%s)", phase_name, phase_input.project_id)
            task_result = await supervisor.run(phase_input)
            dur = round(time.time() - start_t, 2)
            logger.info("[pipeline] %s done in %.1fs success=%s", phase_name, dur, task_result.success)
            if task_result.escalated:
                phase_status = "escalated"
            elif task_result.success:
                phase_status = "passed"
            else:
                phase_status = "failed"
            return {
                "phase": phase_name,
                "status": phase_status,
                "output_path": task_result.output_path,
                "confidence": task_result.confidence,
                "issues": task_result.issues,
                "metadata": task_result.metadata,
                "artifacts": task_result.metadata.get("artifacts", {}),
                "duration_s": dur,
            }
        except asyncio.CancelledError:
            # CancelledError is BaseException — re-raise so wait_for converts to TimeoutError
            logger.warning("[pipeline] %s cancelled (likely parent timeout)", phase_name)
            raise
        except BaseException as e:
            dur = round(time.time() - start_t, 2)
            logger.error("[pipeline] %s crashed after %.1fs: %s: %s",
                         phase_name, dur, type(e).__name__, e)
            # Determine a best-guess output_path so downstream phases aren't starved
            guess_dir = str(
                Path.home() / ".aether_os" / "projects"
                / phase_input.run_id / phase_name
            )
            return {"status": "failed", "error": str(e), "output_path": "", "guess_dir": guess_dir}

    async def _await_human_approval(
        self, run_id: str, org_id: str, phase_name: str, reason: str
    ) -> None:
        """Register a decision ticket and block until approved/denied or timeout."""
        try:
            from aether_os.core.decisions.decision_engine import Decision, get_decision_engine
            engine = get_decision_engine()
            decision = Decision(
                run_id=run_id,
                org_id=org_id,
                decision_type="phase_escalation",
                title=f"Phase {phase_name} requires approval",
                what=f"Phase {phase_name} escalated: {reason[:200]}",
                why="Phase exhausted all retries and requires human sign-off to continue.",
                phase=phase_name,
                timeout_seconds=int(os.environ.get("HUMAN_APPROVAL_TIMEOUT", "300")),
            )
            decision = await engine.request_approval(decision)
            await emit(
                {"type": "approval_required", "phase": phase_name, "decision_id": decision.id},
                run_id=run_id,
            )
            logger.info("[pipeline] Waiting for human approval: run=%s phase=%s decision=%s",
                        run_id, phase_name, decision.id)
            resolved = await engine.await_decision(decision.id)
            if resolved.status == "denied":
                logger.warning("[pipeline] Approval denied for %s/%s — stopping pipeline", run_id, phase_name)
                await set_control(run_id, "cancel")
            elif resolved.status == "timeout":
                logger.warning("[pipeline] Approval timed out for %s/%s — continuing", run_id, phase_name)
        except Exception as exc:
            logger.error("[pipeline] Human approval gate failed (%s) — continuing pipeline", exc)

    async def _update_state(self, run_id: str, phase: str, status: str):
        """Persist phase status via ORM — delegates to run_state.update_phase_state."""
        await update_phase_state(run_id, phase, status)

    async def run_change_request(
        self,
        project_id: str,
        client_id: str,
        change_description: str,
        affected_areas: List[str],
        org_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trigger a partial re-run from the first affected phase.

        Loads the original run's accumulated context so downstream phases
        receive prior phase outputs (architecture, scaffolding, etc.)
        and only the affected subset is re-executed.
        """
        # Map affected area names → concrete phase names
        _AREA_TO_PHASE: Dict[str, str] = {
            "intake":          "p01_intake_requirements",
            "requirements":    "p01_intake_requirements",
            "architecture":    "p02_architecture",
            "scaffolding":     "p03_scaffolding",
            "backend":         "p04_backend",
            "api":             "p04_backend",
            "database":        "p04_backend",
            "frontend":        "p05_frontend",
            "ui":              "p05_frontend",
            "ux":              "p05_frontend",
            "security":        "p06_review_security",
            "review":          "p06_review_security",
            "testing":         "p07_testing",
            "tests":           "p07_testing",
            "healing":         "p07b_self_healing",
            "cicd":            "p08_cicd_deployment",
            "ci":              "p08_cicd_deployment",
            "cd":              "p08_cicd_deployment",
            "observability":   "p09_observability",
            "monitoring":      "p09_observability",
            "docs":            "p10_docs_delivery",
            "documentation":   "p10_docs_delivery",
            "deployment":      "p11_deployment",
            "deploy":          "p11_deployment",
        }

        # Resolve areas → phase names; keep only phases in PHASE_SEQUENCE
        candidate_phases = []
        for area in (affected_areas or []):
            mapped = _AREA_TO_PHASE.get(area.lower().strip())
            if mapped and mapped in PHASE_SEQUENCE:
                candidate_phases.append(PHASE_SEQUENCE.index(mapped))

        if candidate_phases:
            first_phase = PHASE_SEQUENCE[min(candidate_phases)]
        else:
            # Default: re-run from backend if no areas specified
            first_phase = "p04_backend"

        # Load original run's context so downstream phases have prior outputs
        original_context: Dict[str, Any] = {}
        try:
            original_dir = Path.home() / ".aether_os" / "projects" / project_id
            if original_dir.exists():
                import json as _json
                mem_path = original_dir / "project_memory.json"
                if mem_path.exists():
                    original_context = _json.loads(mem_path.read_text())
                # Expose original project dir so phases can read existing code
                original_context["original_project_dir"] = str(original_dir)
                original_context["base_project_id"] = project_id
        except Exception as _e:
            logger.debug("[change_request] Could not load original context: %s", _e)

        return await self.run(
            client_id=client_id,
            raw_input=change_description,
            project_name=f"cr-{project_id[:8]}",
            start_phase=first_phase,
            is_change_request=True,
            org_id=org_id,
            run_id=run_id,
            memory_context=json.dumps(original_context) if original_context else None,
        )


# B5: Strong references to background tasks prevent GC from silently killing them.

_factory: Optional[FactoryPipeline] = None


def get_factory() -> FactoryPipeline:
    global _factory
    if _factory is None:
        _factory = FactoryPipeline()
    return _factory
