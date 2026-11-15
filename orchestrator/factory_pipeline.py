"""
AetherOS — 29-Phase Factory Pipeline

Each phase is a completely independent module.
All inter-phase communication goes through the MessageBus only.
The orchestrator routes messages; it never calls phase logic directly.

Phase registry data lives in orchestrator/phase_sequence.py.
Run-state helpers live in orchestrator/run_state.py.
"""
from __future__ import annotations
import secrets
import json as _json
from sqlalchemy import update as _sa_update
from sqlalchemy import select as _sel, update as _upd
from aether_os.integrations.aether2_bridge import ExternalMonitorBridge
from aether_os.core.services.learning_service import get_user_context
from aether_os.core.questionnaire.stage_questions import get_stage_questions
from aether_os.core.models import Run as _Run_canc
from aether_os.core.models import Run as _Run
from aether_os.core.models import QuestionnaireSession, Run
from aether_os.core.models import Organisation
from aether_os.core.llm.client import init_org_llm_context
from aether_os.core.identity.zero_trust import issue_ticket as _zt_issue
from aether_os.core.db_utils import create_run as _create_run
from aether_os.core.db import get_session_factory as _gsf_q
from aether_os.core.db import get_session_factory as _gsf_canc
from aether_os.core.db import get_session_factory as _gsf
from aether_os.core.db import get_session_factory
import asyncio
import logging
import time
import uuid
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.orchestrator.context_schema import assert_context, validate_context_after_stage
from aether_os.orchestrator.messages import PhaseInput
from aether_os.orchestrator.events import (
    ACTIVE_RUN_ID, ACTIVE_PHASE, ACTIVE_ORG_ID, emit, publish_event,
)
from aether_os.core.pipeline_state import get_control, set_control, clear_run
from aether_os.core.security.redact import redact_secrets
from aether_os.core.projects import get_project_manager
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.project_memory import (
    init_memory as _pm_init,
    update_memory as _pm_update,
    add_changelog_entry as _pm_changelog,
)
from aether_os.orchestrator.phase_sequence import (
    CRITICAL_PHASES,
    PHASE_SEQUENCE,
    PHASE_SUPERVISORS,  # noqa: F401  re-exported: tests and tooling import it from here
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
from aether_os.orchestrator.phase_dag import get_execution_waves
from aether_os.orchestrator.parallel_runner import run_phases_in_wave
from aether_os.orchestrator.phase_selector import (
    select_phases,
    resolve_change_request_phase,
    restore_from_checkpoint,
)
from aether_os.orchestrator.phase_hooks import run_phase_hooks
from aether_os.orchestrator.stage_gate import (
    apply_stage_toggles,
    gate_block_reason,
    load_disabled_stages,
    recorded_status,
    record_run_timeout,
    summarize_stage_outcomes,
    timeout_reason,
)
from aether_os.orchestrator.phase_hooks_helpers import hook_persist_live_url
from aether_os.orchestrator import messages as _messages_module
from aether_os.orchestrator.bus import release_bus
from aether_os.orchestrator.pipeline_completion import (
    persist_finished_at,
    schedule_completion_tasks,
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
                  existing_schema: Optional[Dict[str, Any]] = None,
                  # Q1 / Q4: enrichment fields
                  user_personas: Optional[List[Dict[str, Any]]] = None,
                  has_customer_portal: Optional[bool] = None,
                  has_landing_page: bool = False,
                  app_brand: Optional[Dict[str, Any]] = None,
                  realtime_features: Optional[List[str]] = None,
                  seed_vocabulary: Optional[Dict[str, Any]] = None,
                  multi_tenancy: Optional[bool] = None,
                  mode: str = "autonomous",
                  intake_answers: Optional[Dict[str, Any]] = None,
                  respondent_email: Optional[str] = None,
                  agency_name: Optional[str] = None,
                  agency_logo_url: Optional[str] = None) -> dict:

        timeout = float(os.environ.get("PIPELINE_TIMEOUT_MINUTES", "30")) * 60
        sem = _get_pipeline_semaphore()
        logger.info("Pipeline %s waiting for concurrency slot (%d/%d in use)", run_id, sem._value ^ int(os.environ.get("PIPELINE_MAX_CONCURRENT", "2")) - sem._value, int(os.environ.get("PIPELINE_MAX_CONCURRENT", "2")))
        async with sem:
            logger.info("Pipeline %s acquired concurrency slot", run_id)
            # Store sem on the instance so _pause_for_questionnaire can release it
            # during guided-mode waits without holding the concurrency slot for up to 7 days.
            self._pipeline_sem = sem
            try:
                return await asyncio.wait_for(self._execute_pipeline(
                    client_id, raw_input, domain, project_name, start_phase,
                    run_id, org_id, org_slug, plan, is_change_request, memory_context,
                    council_preflight, github_url, designer_spec or {},
                    tech_preferences, model_preference, priority, codebase_mode, existing_schema,
                    user_personas, has_customer_portal, has_landing_page,
                    app_brand, realtime_features, seed_vocabulary, multi_tenancy,
                    mode=mode, intake_answers=intake_answers,
                    respondent_email=respondent_email, agency_name=agency_name,
                    agency_logo_url=agency_logo_url,
                ), timeout=timeout)
            except asyncio.TimeoutError:
                logger.error("Pipeline %s timed out after %s minutes", run_id, timeout / 60)
                reason = await record_run_timeout(self.ledger, run_id, timeout) if run_id else None
                if run_id:
                    await publish_event(run_id, {"type": "pipeline_complete", "status": "timeout", "error": reason, "ts": time.time()})
                return {"run_id": run_id, "status": "timeout", "error": reason}

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
                  existing_schema: Optional[Dict[str, Any]] = None,
                  # Q1 / Q4: enrichment fields
                  user_personas: Optional[List[Dict[str, Any]]] = None,
                  has_customer_portal: Optional[bool] = None,
                  has_landing_page: bool = False,
                  app_brand: Optional[Dict[str, Any]] = None,
                  realtime_features: Optional[List[str]] = None,
                  seed_vocabulary: Optional[Dict[str, Any]] = None,
                  multi_tenancy: Optional[bool] = None,
                  mode: str = "autonomous",
                  intake_answers: Optional[Dict[str, Any]] = None,
                  respondent_email: Optional[str] = None,
                  agency_name: Optional[str] = None,
                  agency_logo_url: Optional[str] = None) -> dict:

        run_id = run_id or str(uuid.uuid4())

        # Pre-warm per-org LLM API key cache so synchronous client getters
        # can resolve org-specific keys without an await.
        if org_id:
            try:

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
            # Decision log: each phase appends {"key", "value", "reason", "phase", "timestamp"}
            # so downstream phases know WHY architectural choices were made.
            # Use core.context_helpers.record_decision() to append entries.
            "decisions": [],
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
            # ── Q1 / Q4: Enrichment fields — available to every downstream phase ──
            # Dual-persona: list of user persona dicts (name, type, key_actions)
            "user_personas": user_personas or [],
            # Explicit portal flag; None means auto-detect from user_personas
            "has_customer_portal": has_customer_portal,
            # Whether to generate a public marketing/landing page
            "has_landing_page": has_landing_page,
            # Brand tokens (tagline, primary_color, logo_text)
            "app_brand": app_brand or {},
            # Entities that need live/realtime updates (WebSocket / SSE)
            "realtime_features": realtime_features or [],
            # Domain-specific vocabulary examples for seeding LLM prompts
            "seed_vocabulary": seed_vocabulary or {},
            # Multi-tenancy flag promoted to top-level (also in designer_spec.features
            # for backwards compat — both are kept in sync below)
            "multi_tenancy": multi_tenancy if multi_tenancy is not None else False,
            # ── Interactive questionnaire fields ──────────────────────────────
            # "autonomous" (default) runs without pausing; "guided" pauses after
            # each stage for respondent input via a shareable questionnaire link.
            "mode": mode or "autonomous",
            # Pre-filled answers for autonomous mode (keyed by question id)
            "intake_answers": intake_answers or {},
            # Per-stage questionnaire answers collected during guided mode
            "questionnaire_answers": {},
            # White-label branding for questionnaire pages
            "respondent_email": respondent_email or None,
            "agency_name": agency_name or None,
            "agency_logo_url": agency_logo_url or None,
        }
        _ds = dict(designer_spec or {})
        _tp = tech_preferences or {}
        if _tp and not _ds.get("frontend", {}).get("framework"):
            _ds.setdefault("frontend", {})["framework"] = _tp.get("frontend", "")
            _ds.setdefault("backend", {})["framework"] = _tp.get("backend", "")
            _ds.setdefault("backend", {})["database"] = _tp.get("database", "")
        # Keep multi_tenancy in sync: if caller passed it top-level, reflect into
        # designer_spec.features so older phase code that reads that path still works.
        if multi_tenancy is not None:
            _ds.setdefault("features", {})["multi_tenancy"] = multi_tenancy
        elif _ds.get("features", {}).get("multi_tenancy"):
            # Promote designer_spec value to top-level context key
            accumulated_context["multi_tenancy"] = bool(_ds["features"]["multi_tenancy"])
        accumulated_context["designer_spec"] = _ds

        # Inject per-user learning patterns so every phase can tailor its prompts
        if org_id and client_id:
            try:

                _sf = get_session_factory()
                async with _sf() as _sess:
                    _learned = await get_user_context(org_id, client_id, _sess)
                if _learned:
                    accumulated_context["user_learning"] = _learned
                    logger.info("Injected %d learning pattern type(s) for %s",
                                len(_learned), client_id)
            except Exception as _le:
                logger.warning("Learning context unavailable — phases will run without personalisation (run=%s): %s", run_id, _le)

        # Phase selection: honour start_phase override, then restore from checkpoint.
        try:
            phases_to_run = select_phases(PHASE_SEQUENCE, start_phase)
        except ValueError as _sel_exc:
            # An unknown start stage must not silently become a full rebuild.
            return await self._abort_run(run_id, str(_sel_exc))
        phases_to_run, accumulated_context = await restore_from_checkpoint(
            run_id=run_id,
            phase_sequence=PHASE_SEQUENCE,
            phases_to_run=phases_to_run,
            accumulated_context=accumulated_context,
            emit_fn=emit,
        )
        results = {}

        # Per-org stage toggles (Settings → phase_configs): a disabled optional stage
        # is recorded as skipped and left out of the waves; a disable on a mandatory
        # stage is ignored, and why is recorded on the run's event stream and context.
        phases_to_run, _toggled_off, _toggle_ignored = apply_stage_toggles(
            phases_to_run, await load_disabled_stages(org_id))
        accumulated_context["stage_toggles"] = {"skipped": _toggled_off, "ignored": _toggle_ignored}
        for _sk in _toggled_off:
            logger.info("[pipeline] Skipping %s: disabled in this org's settings", _sk)
            results[_sk] = {"status": "skipped", "output_path": "", "artifacts": {},
                            "metadata": {"skipped_reason": "disabled_in_settings"},
                            "confidence": 1.0, "issues": []}
            await self._update_state(run_id, _sk, "skipped")
            await emit({"type": "phase_complete", "phase": _sk, "status": "skipped",
                        "reason": "disabled_in_settings"}, run_id=run_id)
        for _ig, _why in _toggle_ignored.items():
            logger.warning("[pipeline] %s is disabled in settings but mandatory (%s): running it", _ig, _why)
            await emit({"type": "stage_toggle_ignored", "phase": _ig,
                        "reason": f"{_ig} cannot be switched off: {_why}"}, run_id=run_id)

        # ExternalMonitorBridge — optional external telemetry hook (failure here never blocks pipeline)
        _bridge = None
        _monitor_url = os.environ.get("MONITOR_URL", "")
        if _monitor_url:
            try:

                _bridge = ExternalMonitorBridge()
                _bridge.connect(_monitor_url, os.environ.get("MONITOR_API_KEY", ""))
                _bridge.register_pipeline(run_id, list(phases_to_run))
                logger.info("ExternalMonitorBridge connected to %s, monitoring %d phases", _monitor_url, len(phases_to_run))
            except Exception as _br_exc:
                logger.warning("ExternalMonitorBridge init failed — telemetry callbacks will be dropped for run %s: %s", run_id, _br_exc)
                _bridge = None

        pipeline_start = time.time()

        # ── DAG-based execution: compute waves of parallelisable phases ──
        # Phases within a wave have no dependencies on each other and run
        # concurrently via asyncio.gather().  Single-phase waves use the
        # existing sequential path with no asyncio overhead.
        try:
            _execution_waves = get_execution_waves(list(phases_to_run))
        except Exception as _dag_exc:
            logger.warning(
                "[pipeline] DAG wave computation failed (%s) — falling back to sequential",
                _dag_exc,
            )
            _execution_waves = [[p] for p in phases_to_run]

        for _wave in _execution_waves:
            # ── Multi-phase wave: run concurrently, then merge results ────
            if len(_wave) > 1:
                try:
                    _wave_results = await run_phases_in_wave(
                        wave=_wave,
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
                except Exception as _wave_exc:
                    logger.error(
                        "[pipeline] Parallel wave %s raised unexpectedly: %s — aborting",
                        _wave, _wave_exc,
                    )
                    return await self._abort_run(
                        run_id, f"Stages {', '.join(_wave)} crashed: {_wave_exc}")

                for _wp in _wave:
                    _wr = _wave_results.get(_wp, {})
                    results[_wp] = _wr
                    # s09 only ever runs in a parallel wave, and it is the only
                    # parallel stage with a post-stage hook: persist Run.live_url.
                    await hook_persist_live_url(_wp, _wr, run_id, accumulated_context)
                    # D6: record in project memory
                    _pm_update(project_dir, {
                        f"phase_{_wp}": {
                            "status": _wr.get("status"),
                            "duration_s": _wr.get("duration_s"),
                        }
                    })

                # A failed gate (any stage) or a failed critical stage ends the run
                # here. Checked before the checkpoint, so a restart re-runs this wave
                # instead of resuming after it.
                for _wp in _wave:
                    _block = gate_block_reason(_wp, results[_wp], CRITICAL_PHASES)
                    if _block:
                        logger.error("[pipeline] %s blocked run %s in a parallel wave", _wp, run_id)
                        return await self._abort_run(run_id, _block, failed_stage=_wp)

                # Checkpoint the wave once, on its earliest phase in run order.
                # Resume restarts at index(last_completed)+1, so checkpointing a
                # later phase (e.g. s12 in [s05, s12]) would skip s06-s11.
                _run_order = list(phases_to_run)
                await save_checkpoint(
                    run_id, min(_wave, key=_run_order.index), accumulated_context
                )

                # Control signal check after every wave
                _wave_control = await get_control(run_id)
                if _wave_control == "cancel":
                    logger.info("Pipeline %s cancelled after wave %s", run_id, _wave)
                    await self.ledger.async_update_run_status(run_id, "cancelled")
                    await publish_event(run_id, {"type": "pipeline_complete", "status": "cancelled",
                                                 "ts": time.time()})
                    return {"run_id": run_id, "status": "cancelled",
                            "phases": results, "output_dir": str(project_dir)}
                continue  # advance to the next wave

            # ── Single-phase wave: existing sequential path (no overhead) ──
            phase_name = _wave[0]
            # Original per-phase loop body below — unchanged from before DAG wiring.
            # Set context vars so LLM calls in this phase can emit to the queue
            run_token   = ACTIVE_RUN_ID.set(run_id)
            phase_token = ACTIVE_PHASE.set(phase_name)
            org_token   = ACTIVE_ORG_ID.set(org_id)

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
                if phase_name == "s04_frontend":
                    # Skip s04 only when frontend is EXPLICITLY disabled; empty means "use default React"
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
                            "[pipeline] Skipping s04_frontend — frontend=%r (no UI requested)",
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
                    _default_timeout = "1200"  # frontend needs longer; matches parallel_runner logic
                elif phase_name == "s09_devops":
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

                # Gates block: a gate that still fails after retries, or a failed
                # critical stage, ends the run here. Nothing below (context merge,
                # checkpoint, hooks, later stages) runs, so a restart resumes at
                # this stage.
                _block = gate_block_reason(phase_name, phase_result, CRITICAL_PHASES)
                if _block:
                    logger.error("[pipeline] %s blocked run %s: %s", phase_name, run_id, redact_secrets(_block))
                    await self._update_state(run_id, phase_name, "failed")
                    await emit({"type": "phase_complete", "phase": phase_name, "status": "failed",
                                "error": _block}, run_id=run_id)
                    if _bridge:
                        try:
                            _bridge.report_failure(run_id, phase_name, redact_secrets(_block))
                            _bridge.report_stage_complete(run_id, phase_name, 0, success=False)
                        except Exception as _bbe:
                            logger.debug("bridge.report_failure(block) non-fatal: %s", _bbe)
                    return await self._abort_run(run_id, _block, failed_stage=phase_name)

                # ── Guided mode: pause and wait for questionnaire answers ──
                # If the run was started with mode="guided" we pause here after
                # every phase so an external respondent can fill in a per-stage
                # questionnaire before the pipeline continues.
                _run_mode = accumulated_context.get("mode", "autonomous")
                if _run_mode == "guided":
                    await _pause_for_questionnaire(
                        run_id=run_id,
                        stage_id=phase_name,
                        stage_result=phase_result,
                        accumulated_context=accumulated_context,
                        sem=getattr(self, "_pipeline_sem", None),
                    )

                # Emit file_written events for every file produced by this phase
                _phase_dir = project_dir / phase_name
                if _phase_dir.exists():
                    # Patterns to exclude

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

                # Merge stage metadata keys into accumulated_context so downstream
                # stages receive produced keys without relying on hooks as the only bridge.
                _meta_merge = phase_result.get("metadata") or {}
                for _mk, _mv in _meta_merge.items():
                    if _mk not in accumulated_context or _mv is not None:
                        accumulated_context[_mk] = _mv

                # Advisory schema check — logs warnings if expected keys are absent
                assert_context(accumulated_context, phase_name)

                # DC1: structured per-stage required-key validation
                # Checks REQUIRED_AFTER_STAGE for the current stage and logs any
                # missing keys so downstream phases can diagnose gaps early.
                _missing_keys = validate_context_after_stage(phase_name, accumulated_context)
                if _missing_keys:
                    logger.warning(
                        "[pipeline] accumulated_context missing expected keys after %s: %s",
                        phase_name, _missing_keys,
                    )

                # Confidence propagation: record every phase's confidence in a central trail
                _phase_conf = phase_result.get("confidence", 1.0)
                _phase_conf_reason = phase_result.get("confidence_reason", "")
                _conf_trail = accumulated_context.setdefault("phase_confidence", {})
                _conf_trail[phase_name] = {
                    "confidence": _phase_conf,
                    "reason": _phase_conf_reason,
                }
                # Flag any phase below 0.5 so downstream phases and the UI can surface it
                _low_conf = accumulated_context.setdefault("low_confidence_phases", [])
                if _phase_conf < 0.5 and phase_name not in _low_conf:
                    _low_conf.append(phase_name)
                    logger.warning(
                        "[pipeline] Phase %s has low confidence %.2f (%s) — flagging for review",
                        phase_name, _phase_conf, _phase_conf_reason or "no reason given",
                    )

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

                # Per-phase post-processing hooks (extracted to phase_hooks.py).
                # Includes: live_url persistence, intake JSON extraction, architecture
                # loading, knowledge graph build, BackendAuditCouncil, quality gate.
                # Mutates accumulated_context in-place.
                await run_phase_hooks(
                    phase_name=phase_name,
                    phase_result=phase_result,
                    run_id=run_id,
                    project_dir=project_dir,
                    accumulated_context=accumulated_context,
                    domain=domain,
                    client_id=client_id,
                    emit_fn=emit,
                    get_control_fn=get_control,
                    set_control_fn=set_control,
                    publish_event_fn=publish_event,
                    run_phase_fn=self._run_phase,
                    background_tasks=self._background_tasks,
                    messages_module=_messages_module,
                    phase_input=phase_input,
                )

                # Update state
                p_status = recorded_status(phase_result)
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
                        _bridge.report_stage_complete(
                            run_id, phase_name, _elapsed, success=p_status != "failed")
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
                    return await self._abort_run(
                        run_id, timeout_reason(_phase_timeout, phase_name), failed_stage=phase_name)

            except Exception as e:
                logger.error("%s failed: %s", phase_name, redact_secrets(e))
                await self._update_state(run_id, phase_name, "failed")
                results[phase_name] = {"status": "failed", "error": redact_secrets(e), "output_path": ""}
                await emit({"type": "phase_complete", "phase": phase_name, "status": "failed",
                            "error": str(e)}, run_id=run_id)
                if _bridge:
                    try:
                        _bridge.report_failure(run_id, phase_name, redact_secrets(e))
                        _bridge.report_stage_complete(run_id, phase_name, 0, success=False)
                    except Exception as _bfe:
                        logger.debug("bridge.report_failure non-fatal: %s", _bfe)
                if phase_name in CRITICAL_PHASES:
                    logger.error("Critical phase %s failed — aborting pipeline %s", phase_name, run_id)
                    return await self._abort_run(
                        run_id, f"Stage {phase_name} failed: {e}", failed_stage=phase_name)

            finally:
                # Reset context vars after each phase — must reset all three to
                # prevent ContextVar leaks between concurrent pipeline runs.
                ACTIVE_RUN_ID.reset(run_token)
                ACTIVE_PHASE.reset(phase_token)
                ACTIVE_ORG_ID.reset(org_token)

            # ── Control signal check after each phase ──────────────────────
            control = await get_control(run_id)
            if control == "cancel":
                logger.info("Pipeline %s cancelled after phase %s", run_id, phase_name)
                await self.ledger.async_update_run_status(run_id, "cancelled")
                # Fix 62: persist finished_at on cancel (ORM, SQLite-safe)
                try:

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

        duration = time.time() - pipeline_start

        # Persist finished_at inline (fast ORM write — not background)
        await persist_finished_at(run_id)

        # Emit pipeline_complete immediately so SSE clients are not blocked.
        # Status is "council_review" until the DeliveryCouncil background task completes.
        await publish_event(run_id, {
            "type": "pipeline_complete",
            "status": "council_review",
            "duration": round(duration, 1),
            "stage_summary": summarize_stage_outcomes(results),
            "ts": time.time(),
        })

        # Schedule all background completion tasks (notifications, webhooks, learning,
        # S3 upload, etc.) via pipeline_completion.schedule_completion_tasks().
        schedule_completion_tasks(
            run_id=run_id,
            org_id=org_id,
            client_id=client_id,
            domain=domain,
            raw_input=raw_input,
            project_name=project_name,
            project_dir=project_dir,
            duration=duration,
            results=results,
            phases_to_run=list(phases_to_run),
            accumulated_context=accumulated_context,
            background_tasks=self._background_tasks,
            publish_event_fn=publish_event,
            clear_run_fn=clear_run,
            delivery_council_check_fn=delivery_council_check,
            extract_learning_fn=extract_learning,
            store_run_memory_fn=store_run_memory,
            embed_artifacts_fn=embed_artifacts,
            upload_to_s3_fn=upload_to_s3,
            pm_update_fn=_pm_update,
            pm_changelog_fn=_pm_changelog,
        )

        # Release the in-process message bus for this run so its bounded queue
        # is freed and doesn't accumulate across long-lived server processes.
        release_bus(run_id)

        return {
            "run_id": run_id,
            "project_id": run_id,
            "status": "complete",
            "phases": results,
            "output_dir": str(project_dir),
            "duration_seconds": round(duration, 2),
            "phase_count": len(phases_to_run),
            "stage_summary": summarize_stage_outcomes(results),
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

        # Issue a zero-trust ticket that authorises this phase to act on its
        # designated output directory within the current run.  The ticket is
        # embedded in phase_input so the supervisor can verify it before
        # executing privileged operations.
        try:

            _zt_ticket = _zt_issue(
                project_path=phase_input.run_id,
                resource_path=phase_input.output_dir,
                action=phase_name,
            )
            phase_input = phase_input.model_copy(
                update={"input_data": {**phase_input.input_data, "_zt_ticket": _zt_ticket}}
            )
        except Exception as _zt_exc:
            logger.warning("[pipeline] Zero-trust ticket issuance failed for %s (non-fatal): %s",
                           phase_name, _zt_exc)

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
                "confidence_reason": task_result.confidence_reason,
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
            return {"status": "failed", "error": redact_secrets(f"{type(e).__name__}: {e}"),
                    "output_path": "", "guess_dir": guess_dir}

    async def _abort_run(self, run_id: str, message: str,
                         failed_stage: Optional[str] = None) -> dict:
        """End the run as failed: store the redacted reason, tell the live view, stop.

        Every abort goes through here so the reason on Run.message, in the event
        stream and in the returned result is the same redacted text.
        """
        reason = redact_secrets(message)
        await self.ledger.async_update_run_status(run_id, "failed", message=reason)
        await persist_finished_at(run_id)
        try:
            await publish_event(run_id, {"type": "pipeline_complete", "status": "failed",
                                         "error": reason, "failed_stage": failed_stage,
                                         "ts": time.time()})
            release_bus(run_id)
        except Exception as exc:
            # The run is already stored as failed; a lost event must not un-stop it.
            logger.warning("[pipeline] could not publish the failure of run %s: %s", run_id, exc)
        return {"run_id": run_id, "status": "failed", "error": reason,
                "failed_stage": failed_stage}

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
        # Resolve affected area names to the earliest phase that must re-run.
        first_phase = resolve_change_request_phase(
            affected_areas=affected_areas,
            phase_sequence=PHASE_SEQUENCE,
            default_phase="s03_backend",
        )

        # Load original run's context so downstream phases have prior outputs.
        # Carry plan, domain, org_slug from the original run so change-request
        # runs don't silently default to "trial"/"general" and bypass quota checks.
        original_context: Dict[str, Any] = {}
        _orig_plan: Optional[str] = None
        _orig_domain: str = "general"
        _orig_org_slug: Optional[str] = None
        try:
            original_dir = Path.home() / ".aether_os" / "projects" / project_id
            if original_dir.exists():

                mem_path = original_dir / "project_memory.json"
                if mem_path.exists():
                    original_context = _json.loads(mem_path.read_text())
                # Expose original project dir so phases can read existing code
                original_context["original_project_dir"] = str(original_dir)
                original_context["base_project_id"] = project_id
                _orig_plan = original_context.get("plan")
                _orig_domain = original_context.get("domain", "general")
                _orig_org_slug = original_context.get("org_slug")
        except Exception as _e:
            logger.debug("[change_request] Could not load original context: %s", _e)

        return await self.run(
            client_id=client_id,
            raw_input=change_description,
            project_name=f"cr-{project_id[:8]}",
            start_phase=first_phase,
            is_change_request=True,
            org_id=org_id,
            org_slug=_orig_org_slug,
            plan=_orig_plan,
            domain=_orig_domain,
            run_id=run_id,
            memory_context=json.dumps(original_context) if original_context else None,
        )

# ── Guided-mode questionnaire pause / poll ────────────────────────────────────

async def _pause_for_questionnaire(
    run_id: str,
    stage_id: str,
    stage_result: dict,
    accumulated_context: dict,
    sem: Optional[asyncio.Semaphore] = None,
) -> None:
    """Create a QuestionnaireSession for this stage and poll until completed or expired.

    Called from _execute_pipeline when mode == "guided".  Sets the run status to
    "waiting_for_input" so the frontend can show a waiting state, then polls the
    DB every 30 seconds.  On completion, merges answers into accumulated_context.
    Timeout: 7 days (604800 s) — matches the default token TTL.

    H1 — semaphore release during wait: if *sem* is provided, the pipeline
    concurrency slot is released before each sleep interval and re-acquired
    after.  This prevents guided-mode runs from holding a concurrency slot for
    up to 7 days and starving all other pipeline users.
    """
    try:

        _TOKEN_TTL_DAYS = 7
        _POLL_INTERVAL = 30          # seconds between DB polls
        _MAX_WAIT = 604800           # 7 days in seconds

        questions = get_stage_questions(stage_id)
        if not questions:
            # No questions for this stage — skip the pause
            logger.debug(
                "questionnaire: no questions for stage %s, skipping pause (run=%s)",
                stage_id, run_id,
            )
            return

        _sf = _gsf_q()
        # Check if a session already exists for this run + stage
        async with _sf() as _db:
            existing = (await _db.execute(
                _sel(QuestionnaireSession)
                .where(
                    QuestionnaireSession.run_id == run_id,
                    QuestionnaireSession.stage_id == stage_id,
                )
            )).scalar_one_or_none()

            if existing and existing.status == "completed":
                # Already answered — merge and move on immediately
                if existing.answers:
                    qs_answers = accumulated_context.get("questionnaire_answers", {})
                    qs_answers[stage_id] = existing.answers
                    accumulated_context["questionnaire_answers"] = qs_answers
                logger.info(
                    "questionnaire: stage %s already completed for run %s — continuing",
                    stage_id, run_id,
                )
                return

            if not existing:
                # Create session with the agency branding from accumulated_context
                token = secrets.token_urlsafe(32)
                expires_at = datetime.now(timezone.utc) + timedelta(days=_TOKEN_TTL_DAYS)
                _qs = QuestionnaireSession(
                    run_id=run_id,
                    stage_id=stage_id,
                    status="pending",
                    access_token=token,
                    token_expires_at=expires_at,
                    respondent_email=accumulated_context.get("respondent_email") or None,
                    agency_name=accumulated_context.get("agency_name") or None,
                    agency_logo_url=accumulated_context.get("agency_logo_url") or None,
                    questions=questions,
                )
                _db.add(_qs)
                await _db.commit()
                session_id = _qs.id
                logger.info(
                    "[questionnaire] share link: /questionnaire/%s (stage=%s, run=%s)",
                    token, stage_id, run_id,
                )
            else:
                session_id = existing.id

            # Set run status to waiting_for_input
            await _db.execute(
                _upd(Run).where(Run.id == run_id).values(status="waiting_for_input")
            )
            await _db.commit()

        # ── Polling loop ────────────────────────────────────────────────────
        waited = 0
        while waited < _MAX_WAIT:
            logger.debug(
                "questionnaire: waiting for stage %s input (run %s, waited=%ds)",
                stage_id, run_id, waited,
            )
            # H1: Release the pipeline concurrency slot during the sleep so
            # other users' runs are not blocked while we wait for questionnaire
            # input (which can take up to 7 days).  Re-acquire after waking.
            if sem is not None:
                sem.release()
            try:
                await asyncio.sleep(_POLL_INTERVAL)
                waited += _POLL_INTERVAL
            finally:
                if sem is not None:
                    await sem.acquire()

            async with _sf() as _db_poll:
                row = (await _db_poll.execute(
                    _sel(QuestionnaireSession).where(QuestionnaireSession.id == session_id)
                )).scalar_one_or_none()

                if not row:
                    logger.warning(
                        "questionnaire: session %s disappeared — resuming without answers",
                        session_id,
                    )
                    break

                if row.status == "completed":
                    if row.answers:
                        qs_answers = accumulated_context.get("questionnaire_answers", {})
                        qs_answers[stage_id] = row.answers
                        accumulated_context["questionnaire_answers"] = qs_answers
                    logger.info(
                        "questionnaire: stage %s completed for run %s — pipeline resuming",
                        stage_id, run_id,
                    )
                    # Restore run status to running
                    await _db_poll.execute(
                        _upd(Run).where(Run.id == run_id).values(status="running")
                    )
                    await _db_poll.commit()
                    return

                # Check for expiry
                expires = row.token_expires_at
                if expires:
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > expires:
                        await _db_poll.execute(
                            _upd(QuestionnaireSession)
                            .where(QuestionnaireSession.id == session_id)
                            .values(status="expired")
                        )
                        await _db_poll.commit()
                        logger.warning(
                            "questionnaire: session %s expired for run %s — resuming without answers",
                            session_id, run_id,
                        )
                        break

        # Timed out or expired — set run back to running so pipeline continues
        try:
            async with _sf() as _db_end:
                await _db_end.execute(
                    _upd(Run).where(Run.id == run_id).values(status="running")
                )
                await _db_end.commit()
        except Exception as _end_exc:
            logger.warning("questionnaire: failed to restore run status: %s", _end_exc)

    except Exception as e:
        logger.warning(
            "questionnaire: _pause_for_questionnaire failed (non-fatal, run=%s stage=%s): %s",
            run_id, stage_id, e,
        )

# B5: Strong references to background tasks prevent GC from silently killing them.

_factory: Optional[FactoryPipeline] = None

def get_factory() -> FactoryPipeline:
    global _factory
    if _factory is None:
        _factory = FactoryPipeline()
    return _factory
