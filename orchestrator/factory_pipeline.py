"""
AetherOS — 26-Phase Factory Pipeline

Each phase is a completely independent module.
All inter-phase communication goes through the MessageBus only.
The orchestrator routes messages; it never calls phase logic directly.
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
    ACTIVE_RUN_ID, ACTIVE_PHASE, emit,
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

logger = logging.getLogger(__name__)

# Phases whose failure must abort the pipeline — downstream phases depend on their output.
# Self-healing (p07b) and observational phases (p08+) are deliberately excluded so
# they don't block delivery on non-critical failures.
CRITICAL_PHASES = frozenset({
    "p01_intake_requirements",  # no requirements → nothing to build
    "p02_architecture",         # no architecture → codegen produces garbage
    "p04_backend",              # no backend → p05 integration fails completely
})

# Ordered 20-phase sequence (12 core + 8 post-deployment)
PHASE_SEQUENCE = [
    "p01_intake_requirements",
    "p02_architecture",
    "p02b_domain_ir",
    "p03_scaffolding",
    "p04_backend",
    "p05_frontend",
    "p06_review_security",
    "p07_testing",
    "p07b_self_healing",
    "p08_cicd_deployment",
    "p09_observability",
    "p10_docs_delivery",
    "p11_deployment",       # Docker build & run — delivers a live URL
    "p11a_monitoring",      # Prometheus + Grafana + OTEL
    "p11b_error_tracking",  # Sentry + structlog
    "p11c_analytics",       # PostHog events + dashboard
    "p11d_alerting",        # Alertmanager + runbooks
    "p12a_feature_flags",   # Unleash feature flags
    "p12b_ab_testing",      # GrowthBook experiments
    "p13_app_memory",       # mem0 memory layer + knowledge graph
    "p14_client_portal",    # Standalone client review portal
]

# Phase name → supervisor class path (20 phases: 12 core + 8 post-deployment)
PHASE_SUPERVISORS: Dict[str, str] = {
    "p01_intake_requirements": "aether_os.phases.p01_intake_requirements.IntakeRequirementsSupervisor",
    "p02_architecture":        "aether_os.phases.p02_architecture.ArchitectureSupervisor",
    "p02b_domain_ir":          "aether_os.phases.p02b_domain_ir.DomainIRSupervisor",
    "p03_scaffolding":         "aether_os.phases.p03_scaffolding.ScaffoldingSupervisor",
    "p04_backend":             "aether_os.phases.p04_backend.BackendSupervisor",
    "p05_frontend":            "aether_os.phases.p05_frontend.FrontendSupervisor",
    "p06_review_security":     "aether_os.phases.p06_review_security.ReviewSecuritySupervisor",
    "p07_testing":             "aether_os.phases.p07_testing.TestingSupervisor",
    "p07b_self_healing":       "aether_os.phases.p07b_self_healing.SelfHealingSupervisor",
    "p08_cicd_deployment":     "aether_os.phases.p08_cicd_deployment.CICDDeploymentSupervisor",
    "p09_observability":       "aether_os.phases.p09_observability.ObservabilitySupervisor",
    "p10_docs_delivery":       "aether_os.phases.p10_docs_delivery.DocsDeliverySupervisor",
    "p11_deployment":          "aether_os.phases.p11_deployment.DeploymentSupervisor",
    # Post-deployment phases
    "p11a_monitoring":         "aether_os.phases.p11a_monitoring.MonitoringSupervisor",
    "p11b_error_tracking":     "aether_os.phases.p11b_error_tracking.ErrorTrackingSupervisor",
    "p11c_analytics":          "aether_os.phases.p11c_analytics.AnalyticsSupervisor",
    "p11d_alerting":           "aether_os.phases.p11d_alerting.AlertingSupervisor",
    "p12a_feature_flags":      "aether_os.phases.p12a_feature_flags.FeatureFlagsSupervisor",
    "p12b_ab_testing":         "aether_os.phases.p12b_ab_testing.ABTestingSupervisor",
    "p13_app_memory":          "aether_os.phases.p13_app_memory.AppMemorySupervisor",
    "p14_client_portal":       "aether_os.phases.p14_client_portal.ClientPortalSupervisor",
}


def _load_supervisor(phase_name: str):
    """Dynamically import and instantiate the supervisor for a phase."""
    class_path = PHASE_SUPERVISORS.get(phase_name)
    if not class_path:
        return None
    module_path, class_name = class_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


class FactoryPipeline:
    """
    26-phase factory pipeline.
    Routes entirely via the message bus.
    No phase imports another phase.
    """

    def __init__(self) -> None:
        self.ledger = get_ledger()
        self.pm = get_project_manager()

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
                  github_url: Optional[str] = None) -> dict:

        timeout = float(os.environ.get("PIPELINE_TIMEOUT_MINUTES", "30")) * 60
        try:
            return await asyncio.wait_for(self._execute_pipeline(
                client_id, raw_input, domain, project_name, start_phase,
                run_id, org_id, org_slug, plan, is_change_request, memory_context,
                council_preflight, github_url,
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
                  github_url: Optional[str] = None) -> dict:

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
            project_name=project_name or f"project-{run_id[:8]}",
            requirement=raw_input,
            domain=domain,
            run_id=run_id,
        )

        try:
            from aether_os.core.db_utils import create_run as _create_run
            await _create_run(
                run_id=run_id,
                command=f"factory: {raw_input[:60]}",
                org_id=org_id or "",
                project_name=project_name or f"project-{run_id[:8]}",
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
            "project_name": project_name or f"project-{run_id[:8]}",
            "project_dir": str(project_dir),
            "is_change_request": is_change_request,
            # Cross-run memory context injected from MemoryService (may be "")
            "memory_context": memory_context or "",
            # Optional GitHub repo to fork/clone instead of generating from scratch
            "github_url": github_url or "",
            # Pipeline flow control: "autonomous" skips human approval gates
            "decision_mode": "autonomous" if _org_autonomous else "approval_required",
        }

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
                logger.debug("Learning context unavailable (non-fatal): %s", _le)
        
        # 10-phase consolidated pipeline
        ACTIVE_PHASES = PHASE_SEQUENCE  # All 10 consolidated phases

        phases_to_run = ACTIVE_PHASES
        if start_phase:
            all_phases = PHASE_SEQUENCE
            if start_phase in all_phases:
                phases_to_run = all_phases[all_phases.index(start_phase):]

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
                logger.debug("Aether2Bridge init non-fatal: %s", _br_exc)
                _bridge = None

        results = {}
        pipeline_start = time.time()

        for phase_name in phases_to_run:
            # Set context vars so LLM calls in this phase can emit to the queue
            run_token   = ACTIVE_RUN_ID.set(run_id)
            phase_token = ACTIVE_PHASE.set(phase_name)

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
                _phase_timeout = float(os.environ.get("PHASE_TIMEOUT_SECONDS", "600"))
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
                    await self._await_human_approval(
                        run_id=run_id,
                        org_id=org_id or "",
                        phase_name=phase_name,
                        reason=str((phase_result.get("issues") or ["unknown"])[:1][0]),
                    )

                # Emit file_written events for every file produced by this phase
                _phase_dir = project_dir / phase_name
                if _phase_dir.exists():
                    for _f in _phase_dir.rglob("*"):
                        if _f.is_file():
                            try:
                                _sz = _f.stat().st_size
                            except OSError:
                                _sz = 0
                            await emit({
                                "type": "file_written",
                                "phase": phase_name,
                                "path": str(_f.relative_to(project_dir)),
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
                    # so the user can inspect/edit the parsed requirements before codegen starts.
                    if accumulated_context.get("decision_mode") != "autonomous":
                        try:
                            await set_control(run_id, "spec_review")
                            await emit({"type": "spec_review_ready", "run_id": run_id}, run_id=run_id)
                            logger.info("[pipeline] Spec review gate: waiting for approval (run=%s)", run_id)
                            _spec_timeout = int(os.environ.get("SPEC_REVIEW_TIMEOUT", "600"))
                            _spec_waited = 0
                            while _spec_waited < _spec_timeout:
                                _ctrl = await get_control(run_id)
                                if _ctrl == "spec_approved":
                                    logger.info("[pipeline] Spec approved — continuing (run=%s)", run_id)
                                    await set_control(run_id, "running")
                                    break
                                if _ctrl == "cancel":
                                    logger.warning("[pipeline] Spec review cancelled (run=%s)", run_id)
                                    raise RuntimeError("Pipeline cancelled at spec review")
                                await asyncio.sleep(3)
                                _spec_waited += 3
                            else:
                                # Timeout: auto-approve so the pipeline isn't blocked forever
                                logger.warning("[pipeline] Spec review timeout — auto-approving (run=%s)", run_id)
                                await set_control(run_id, "running")
                        except RuntimeError:
                            raise
                        except Exception as _sr_exc:
                            logger.warning("[pipeline] Spec review gate error (non-fatal): %s", _sr_exc)

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

                # Load domain_ir.json after p02b so all downstream phases receive it
                if phase_name == "p02b_domain_ir":
                    import json as _json
                    _ir_path_str = phase_result.get("domain_ir_path", "")
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
                        for _f in _p04_src.glob("*.py"):
                            _dest = _dest_src / _f.name
                            # Only overwrite if generated file is non-trivial
                            if _f.stat().st_size > 50:
                                _shutil.copy2(_f, _dest)
                                logger.info("[pipeline] S11: merged %s → %s", _f.name, _dest)
                            else:
                                logger.debug("[pipeline] S11: skipped trivial %s (%d bytes)", _f.name, _f.stat().st_size)
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
                    if _routes_candidate.exists():
                        accumulated_context["api_routes_path"] = str(_routes_candidate)
                        logger.info("[pipeline] api_routes_path → %s", _routes_candidate)

                    # BackendAuditCouncil — autonomous multi-model code review of generated main.py
                    async def _backend_audit_council():
                        try:
                            from aether_os.core.council.council_reviewer import run_council
                            _main_candidates = [
                                project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
                                project_dir / "p04_backend" / "src" / "main.py",
                                project_dir / "src" / "main.py",
                            ]
                            _main_py = next((p for p in _main_candidates if p.exists()), None)
                            if not _main_py:
                                logger.debug("[BackendAuditCouncil] main.py not found, skipping")
                                return
                            _src = _main_py.read_text()
                            _report = await asyncio.wait_for(
                                run_council(_src, run_id, accumulated_context.get("project_name", "Project"), domain or "general"),
                                timeout=90.0,
                            )
                            from dataclasses import asdict as _asdict
                            _report_dict = _asdict(_report)
                            _out = project_dir / "council_review.json"
                            import json as _cj
                            _out.write_text(_cj.dumps(_report_dict, indent=2))
                            accumulated_context["council_review"] = _report_dict
                            await emit({"type": "council_review_complete", "score": _report.average_score, "issues": len(_report.consensus_issues)}, run_id=run_id)
                            logger.info("[BackendAuditCouncil] run %s: avg_score=%.1f consensus_issues=%d", run_id, _report.average_score, len(_report.consensus_issues))
                        except Exception as _bac_exc:
                            logger.warning("[BackendAuditCouncil] non-fatal: %s", _bac_exc)
                    _bac_task = asyncio.create_task(_backend_audit_council())
                    _background_tasks_set = getattr(self, "_bg_tasks", set())
                    _background_tasks_set.add(_bac_task)
                    _bac_task.add_done_callback(_background_tasks_set.discard)

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

        # Auto-start the generated app via the proper run_app logic
        # (builds frontend, patches SQLite, handles crash fallback)
        async def _auto_start_app():
            try:
                from aether_os.gateway.routers.factory_runs_router import start_run_app as _sar
                _system_user = {"org_id": org_id, "user_id": "system", "role": "admin", "email": "system@aetheros.internal"}
                result = await _sar(run_id=run_id, user=_system_user)
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
        asyncio.create_task(_auto_start_app())

        duration = time.time() - pipeline_start

        # LLM Council delivery check (background — stores result and flags run if quality fails)
        async def _delivery_council_check():
            try:
                from aether_os.core.council import DeliveryCouncil
                from aether_os.core.db import get_session_factory as _gsf
                from aether_os.core.models import Run as _Run
                from sqlalchemy import update as _sa_update
                _dc = DeliveryCouncil()
                _delivery = await asyncio.wait_for(
                    _dc.run(
                        run_id=run_id,
                        project_name=project_name or f"project-{run_id[:8]}",
                        domain=domain,
                        phases_results=results,
                        org_id=org_id,
                    ),
                    timeout=120,
                )
                # Determine final status: completed or needs_review
                _council_passed = _delivery.get("passed", True)
                _council_score = _delivery.get("score", 1.0)
                _final_status = "completed" if _council_passed else "needs_review"
                _sf = _gsf()
                async with _sf() as _s:
                    await _s.execute(
                        _sa_update(_Run)
                        .where(_Run.id == run_id)
                        .values(
                            council_delivery=_delivery,
                            status=_final_status,
                            message=(
                                None if _council_passed
                                else f"DeliveryCouncil flagged issues (score={_council_score:.2f}): "
                                     f"{_delivery.get('reason', '')} — "
                                     f"Suggestions: {'; '.join(_delivery.get('suggestions', []))}"
                            ),
                        )
                    )
                    await _s.commit()
                if not _council_passed:
                    logger.warning(
                        "DeliveryCouncil: run %s flagged as needs_review (score=%.2f): %s | suggestions: %s",
                        run_id, _council_score, _delivery.get("reason", ""),
                        _delivery.get("suggestions", []),
                    )
                    # Emit an SSE event so the UI can show the council feedback immediately
                    await publish_event(run_id, {
                        "type": "council_delivery_review",
                        "passed": False,
                        "score": _council_score,
                        "reason": _delivery.get("reason", ""),
                        "suggestions": _delivery.get("suggestions", []),
                    })
                else:
                    logger.info(
                        "DeliveryCouncil: run %s passed (score=%.2f)", run_id, _council_score
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "DeliveryCouncil timed out after 120s for run %s — marking completed", run_id
                )
                try:
                    from aether_os.core.db import get_session_factory as _gsf2t
                    from aether_os.core.models import Run as _Run2t
                    from sqlalchemy import update as _sa_update2t
                    _sf2t = _gsf2t()
                    async with _sf2t() as _s2t:
                        await _s2t.execute(
                            _sa_update2t(_Run2t).where(_Run2t.id == run_id).values(status="completed")
                        )
                        await _s2t.commit()
                except Exception:
                    pass
            except Exception as _exc:
                logger.warning("DeliveryCouncil check failed: %s", _exc)
                # Council unavailable — promote to completed so run is not stuck in council_review
                try:
                    from aether_os.core.db import get_session_factory as _gsf2
                    from aether_os.core.models import Run as _Run2
                    from sqlalchemy import update as _sa_update2
                    _sf2 = _gsf2()
                    async with _sf2() as _s2:
                        await _s2.execute(
                            _sa_update2(_Run2).where(_Run2.id == run_id).values(status="completed")
                        )
                        await _s2.commit()
                except Exception:
                    pass

        _dc_task = asyncio.create_task(_delivery_council_check())
        _background_tasks.add(_dc_task)
        _dc_task.add_done_callback(_background_tasks.discard)

        # Emit pipeline_complete immediately so SSE clients are not blocked.
        # Status is "council_review" until the DeliveryCouncil background task completes.
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
                        link=f"/project/{run_id}",
                    )
                    async with _gsf_n()() as _s:
                        _s.add(_notif)
                        await _s.commit()
                except Exception as _ne:
                    logger.debug("[pipeline] notification creation failed: %s", _ne)
            _n_task = asyncio.create_task(_create_completion_notification())
            _background_tasks.add(_n_task)
            _n_task.add_done_callback(_background_tasks.discard)

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
            _background_tasks.add(_wh_t)
            _wh_t.add_done_callback(_background_tasks.discard)

        # D6: Finalize project living memory
        _pm_update(project_dir, {"tech_stack": accumulated_context.get("architecture_json", {}).get("tech_stack", {})})
        _pm_changelog(project_dir, f"Pipeline completed in {round(duration, 1)}s — {len(phases_to_run)} phases", author="system")

        # Schedule Redis key cleanup after 5 minutes (B3 + B5: store task ref)
        async def _cleanup():
            await asyncio.sleep(300)
            await clear_run(run_id)
            _background_tasks.discard(asyncio.current_task())
        _t = asyncio.create_task(_cleanup())
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)

        # ── Store outcome in cross-run memory for future learning (background) ──
        async def _store_memory():
            if not org_id:
                return
            try:
                from aether_os.core.services.memory_service import get_memory_service
                ms = get_memory_service()
                await ms.store_run_outcome(
                    org_id=org_id,
                    run_id=run_id,
                    raw_input=raw_input,
                    status="completed",
                    domain=domain,
                    phase_outputs={k: v.get("artifacts", {}) for k, v in results.items()},
                )
            except Exception as _me:
                logger.debug("[pipeline] Memory store skipped: %s", _me)
        _t2 = asyncio.create_task(_store_memory())
        _background_tasks.add(_t2)
        _t2.add_done_callback(_background_tasks.discard)

        # ── PART 2: Embed artifacts for semantic search (background, non-blocking)
        async def _embed_artifacts():
            if await get_control(run_id) == "cancel":
                return
            try:
                from aether_os.core.artifact_store import get_artifact_store
                store = get_artifact_store()
                _extensions = {".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".sql"}
                _count = 0
                _errors = 0
                _MAX_ARTIFACTS = int(os.environ.get("ARTIFACT_EMBED_LIMIT", "500"))
                for _phase in results:
                    if await get_control(run_id) == "cancel":
                        break
                    _phase_dir = project_dir / _phase
                    if _phase_dir.exists():
                        for f in _phase_dir.rglob("*"):
                            if f.is_file() and f.suffix in _extensions:
                                try:
                                    await store.store_artifact(run_id, str(f.relative_to(project_dir)), f.read_text(), org_id=org_id)
                                    _count += 1
                                    if _count >= _MAX_ARTIFACTS:
                                        break
                                except Exception as _ef:
                                    _errors += 1
                                    logger.debug("[pipeline] artifact embed failed %s: %s", f.name, _ef)
                                    continue
                    if _count >= _MAX_ARTIFACTS:
                        break
                if _errors:
                    logger.warning("[pipeline] Embedded %d artifacts (%d failed) for run %s", _count, _errors, run_id)
                else:
                    logger.info("[pipeline] Embedded %d artifacts for run %s", _count, run_id)
            except Exception as e:
                logger.warning("[pipeline] Artifact embedding skipped: %s", e)
        _t3 = asyncio.create_task(_embed_artifacts())
        _background_tasks.add(_t3)
        _t3.add_done_callback(_background_tasks.discard)

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
        """Persist phase status via ORM (FIX-017)."""
        try:
            from aether_os.core.db import get_session_factory as _gsf_us
            from aether_os.core.models import PhaseCompletion as _PC_us
            async with _gsf_us()() as _sess_us:
                existing_pc = (await _sess_us.get(_PC_us, (run_id, phase)))
                if existing_pc:
                    existing_pc.status = status
                    existing_pc.updated_at = time.time()
                else:
                    _sess_us.add(_PC_us(
                        run_id=run_id,
                        phase_name=phase,
                        status=status,
                        updated_at=time.time(),
                    ))
                await _sess_us.commit()
        except Exception as e:
            logger.warning("State update failed: %s", e)

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
_background_tasks: set = set()

_factory: Optional[FactoryPipeline] = None


def get_factory() -> FactoryPipeline:
    global _factory
    if _factory is None:
        _factory = FactoryPipeline()
    return _factory
