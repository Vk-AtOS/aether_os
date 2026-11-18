"""
PipelineRun: the state one factory run shares between its steps (KAN-57).

This used to be ~30 arguments and a dozen locals of one 700 line method. The
steps live in pipeline_steps.py; see docs/design/pipeline_run.md.

Every collaborator that tests patch on orchestrator.factory_pipeline is read as
``fp.<name>`` (fp is that module) at call time, so those patches keep working.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

from sqlalchemy import select as _sel
from sqlalchemy import update as _sa_update

from aether_os.core.models import Organisation
from aether_os.core.models import Run as _Run

logger = logging.getLogger(__name__)


@dataclass
class PipelineRun:
    """The request plus the runtime state of one run. Steps mutate it in place."""

    fp: ModuleType                      # orchestrator.factory_pipeline (patch point)
    pipeline: Any                       # the FactoryPipeline instance
    client_id: str
    raw_input: str
    domain: str = "general"
    project_name: Optional[str] = None
    start_phase: Optional[str] = None
    run_id: str = ""
    org_id: Optional[str] = None
    org_slug: Optional[str] = None
    plan: Optional[str] = None
    is_change_request: bool = False
    memory_context: Optional[str] = None
    council_preflight: Optional[Dict[str, Any]] = None
    github_url: Optional[str] = None
    designer_spec: Optional[Dict[str, Any]] = None
    tech_preferences: Optional[Dict[str, Any]] = None
    model_preference: Optional[str] = None
    priority: Optional[str] = None
    codebase_mode: Optional[str] = None
    existing_schema: Optional[Dict[str, Any]] = None
    user_personas: Optional[List[Dict[str, Any]]] = None
    has_customer_portal: Optional[bool] = None
    has_landing_page: bool = False
    app_brand: Optional[Dict[str, Any]] = None
    realtime_features: Optional[List[str]] = None
    seed_vocabulary: Optional[Dict[str, Any]] = None
    multi_tenancy: Optional[bool] = None
    mode: str = "autonomous"
    intake_answers: Optional[Dict[str, Any]] = None
    respondent_email: Optional[str] = None
    agency_name: Optional[str] = None
    agency_logo_url: Optional[str] = None
    # runtime state (the former locals)
    project_dir: Optional[Path] = None
    accumulated_context: Dict[str, Any] = field(default_factory=dict)
    phases_to_run: List[str] = field(default_factory=list)
    results: Dict[str, Any] = field(default_factory=dict)
    waves: List[List[str]] = field(default_factory=list)
    bridge: Any = None
    pipeline_start: float = 0.0


def build_context(run: PipelineRun, project_dir: Path, org_autonomous: bool) -> Dict[str, Any]:
    """The accumulated context every phase receives (verbatim from the old method)."""
    run_id, org_id = run.run_id, run.org_id
    ctx = {
        "run_id": run_id,
        "org_id": org_id,
        "org_slug": run.org_slug or "",
        "plan": run.plan or "trial",
        "client_id": run.client_id,
        "raw_input": run.raw_input,
        "domain": run.domain,
        "project_name": run.project_name or run.fp._extract_project_name(run.raw_input, run_id),
        # Decision log: each phase appends {"key", "value", "reason", "phase", "timestamp"}
        # so downstream phases know WHY architectural choices were made.
        "decisions": [],
        "project_dir": str(project_dir),
        "is_change_request": run.is_change_request,
        # Cross-run memory context injected from MemoryService (may be "")
        "memory_context": run.memory_context or "",
        "github_url": run.github_url or "",
        # "autonomous" skips human approval gates
        "decision_mode": "autonomous" if org_autonomous else "approval_required",
        "tech_preferences": run.tech_preferences or {},
        "model_preference": run.model_preference or "",
        "priority": run.priority or "normal",
        "codebase_mode": run.codebase_mode or "new",
        "existing_schema": run.existing_schema or {},
        # Q1 / Q4 enrichment fields, available to every downstream phase
        "user_personas": run.user_personas or [],
        "has_customer_portal": run.has_customer_portal,
        "has_landing_page": run.has_landing_page,
        "app_brand": run.app_brand or {},
        "realtime_features": run.realtime_features or [],
        "seed_vocabulary": run.seed_vocabulary or {},
        "multi_tenancy": run.multi_tenancy if run.multi_tenancy is not None else False,
        # Interactive questionnaire: "guided" pauses after each stage
        "mode": run.mode or "autonomous",
        "intake_answers": run.intake_answers or {},
        "questionnaire_answers": {},
        "respondent_email": run.respondent_email or None,
        "agency_name": run.agency_name or None,
        "agency_logo_url": run.agency_logo_url or None,
    }
    ds = dict(run.designer_spec or {})
    tp = run.tech_preferences or {}
    if tp and not ds.get("frontend", {}).get("framework"):
        ds.setdefault("frontend", {})["framework"] = tp.get("frontend", "")
        ds.setdefault("backend", {})["framework"] = tp.get("backend", "")
        ds.setdefault("backend", {})["database"] = tp.get("database", "")
    # Keep multi_tenancy in sync so older phase code reading designer_spec.features works.
    if run.multi_tenancy is not None:
        ds.setdefault("features", {})["multi_tenancy"] = run.multi_tenancy
    elif ds.get("features", {}).get("multi_tenancy"):
        ctx["multi_tenancy"] = bool(ds["features"]["multi_tenancy"])
    ctx["designer_spec"] = ds
    return ctx


async def _create_records(run: PipelineRun) -> None:
    """DB run row and the pre-flight council result."""
    fp, run_id, org_id = run.fp, run.run_id, run.org_id
    try:
        await fp._create_run(
            run_id=run_id,
            command=f"factory: {run.raw_input[:60]}",
            org_id=org_id,
            project_name=run.project_name or fp._extract_project_name(run.raw_input, run_id),
            domain=run.domain,
            client_id=run.client_id,
            raw_input=run.raw_input,
        )
    except Exception as _cr_exc:
        logger.warning("create_run failed, falling back to async_save_run: %s", _cr_exc)
        await run.pipeline.ledger.async_save_run(
            run_id, f"factory: {run.raw_input[:60]}", org_id=org_id, status="running")

    if run.council_preflight:
        try:
            _sf = fp._gsf()
            async with _sf() as _s:
                await _s.execute(
                    _sa_update(_Run).where(_Run.id == run_id).values(council_preflight=run.council_preflight)
                )
                await _s.commit()
        except Exception as _exc:
            logger.warning("Failed to persist council_preflight: %s", _exc)


async def _org_autonomous_mode(run: PipelineRun) -> bool:
    """Org settings (autonomous_mode) so the pipeline behaves correctly."""
    try:
        async with run.fp.get_session_factory()() as _os:
            _org = (await _os.execute(_sel(Organisation).where(Organisation.id == run.org_id))).scalar_one_or_none()
            if _org:
                return bool(getattr(_org, "autonomous_mode", False))
    except Exception as _oe:
        logger.debug("Could not load org autonomous_mode: %s", _oe)
    return False


async def _inject_learning(run: PipelineRun) -> None:
    """Per-user learning patterns so every phase can tailor its prompts."""
    fp, ctx = run.fp, run.accumulated_context
    if not (run.org_id and run.client_id):
        return
    try:
        _sf = fp.get_session_factory()
        async with _sf() as _sess:
            _learned = await fp.get_user_context(run.org_id, run.client_id, _sess)
        if _learned:
            ctx["user_learning"] = _learned
            logger.info("Injected %d learning pattern type(s) for %s", len(_learned), run.client_id)
    except Exception as _le:
        logger.warning("Learning context unavailable — phases will run without personalisation (run=%s): %s",
                       run.run_id, _le)


async def _apply_toggles(run: PipelineRun) -> None:
    """Per-org stage toggles (Settings -> phase_configs).

    A disabled optional stage is recorded as skipped and left out of the waves; a
    disable on a mandatory stage is ignored, and why is recorded on the run's
    event stream and context.
    """
    fp, run_id, results = run.fp, run.run_id, run.results
    run.phases_to_run, _toggled_off, _toggle_ignored = fp.apply_stage_toggles(
        run.phases_to_run, await fp.load_disabled_stages(run.org_id))
    run.accumulated_context["stage_toggles"] = {"skipped": _toggled_off, "ignored": _toggle_ignored}
    for _sk in _toggled_off:
        logger.info("[pipeline] Skipping %s: disabled in this org's settings", _sk)
        results[_sk] = {"status": "skipped", "output_path": "", "artifacts": {},
                        "metadata": {"skipped_reason": "disabled_in_settings"},
                        "confidence": 1.0, "issues": []}
        await run.pipeline._update_state(run_id, _sk, "skipped")
        await fp.emit({"type": "phase_complete", "phase": _sk, "status": "skipped",
                       "reason": "disabled_in_settings"}, run_id=run_id)
    for _ig, _why in _toggle_ignored.items():
        logger.warning("[pipeline] %s is disabled in settings but mandatory (%s): running it", _ig, _why)
        await fp.emit({"type": "stage_toggle_ignored", "phase": _ig,
                       "reason": f"{_ig} cannot be switched off: {_why}"}, run_id=run_id)


def _connect_bridge(run: PipelineRun) -> None:
    """Optional external telemetry hook; a failure here never blocks the pipeline."""
    monitor_url = os.environ.get("MONITOR_URL", "")
    if not monitor_url:
        return
    try:
        bridge = run.fp.ExternalMonitorBridge()
        bridge.connect(monitor_url, os.environ.get("MONITOR_API_KEY", ""))
        bridge.register_pipeline(run.run_id, list(run.phases_to_run))
        logger.info("ExternalMonitorBridge connected to %s, monitoring %d phases",
                    monitor_url, len(run.phases_to_run))
        run.bridge = bridge
    except Exception as _br_exc:
        logger.warning("ExternalMonitorBridge init failed — telemetry callbacks will be dropped for run %s: %s",
                       run.run_id, _br_exc)
        run.bridge = None


def _compute_waves(run: PipelineRun) -> None:
    """DAG waves of parallelisable phases; falls back to sequential."""
    try:
        run.waves = run.fp.get_execution_waves(list(run.phases_to_run))
    except Exception as _dag_exc:
        logger.warning("[pipeline] DAG wave computation failed (%s) — falling back to sequential", _dag_exc)
        run.waves = [[p] for p in run.phases_to_run]


async def prepare(run: PipelineRun) -> Optional[dict]:
    """Everything before the first wave. Returns a terminal result if the run ends here."""
    fp = run.fp
    run.run_id = run.run_id or str(uuid.uuid4())
    run_id, org_id = run.run_id, run.org_id

    # Pre-warm the per-org LLM API key cache so synchronous client getters need no await.
    if org_id:
        try:
            await fp.init_org_llm_context(org_id)
        except Exception as _key_exc:
            logger.debug("init_org_llm_context non-fatal: %s", _key_exc)

    run.project_dir = Path.home() / ".aether_os" / "projects" / run_id
    run.project_dir.mkdir(parents=True, exist_ok=True)

    # D6: Initialize project living memory
    fp._pm_init(
        run.project_dir,
        project_name=run.project_name or fp._extract_project_name(run.raw_input, run_id),
        requirement=run.raw_input,
        domain=run.domain,
        run_id=run_id,
    )

    if not org_id:
        logger.error("[pipeline] org_id is required to create a run — aborting (run=%s)", run_id)
        raise ValueError("org_id is required: runs without an org bypass quota tracking and billing")

    await _create_records(run)
    org_autonomous = await _org_autonomous_mode(run)
    run.accumulated_context = build_context(run, run.project_dir, org_autonomous)
    await _inject_learning(run)

    # Phase selection: honour start_phase override, then restore from checkpoint.
    try:
        run.phases_to_run = fp.select_phases(fp.PHASE_SEQUENCE, run.start_phase)
    except ValueError as _sel_exc:
        # An unknown start stage must not silently become a full rebuild.
        return await run.pipeline._abort_run(run_id, str(_sel_exc))
    run.phases_to_run, run.accumulated_context = await fp.restore_from_checkpoint(
        run_id=run_id,
        phase_sequence=fp.PHASE_SEQUENCE,
        phases_to_run=run.phases_to_run,
        accumulated_context=run.accumulated_context,
        emit_fn=fp.emit,
    )
    run.results = {}
    await _apply_toggles(run)
    _connect_bridge(run)
    run.pipeline_start = time.time()
    _compute_waves(run)
    return None
