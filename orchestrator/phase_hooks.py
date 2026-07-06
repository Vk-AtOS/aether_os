"""
AetherOS — Phase Post-Processing Hooks

Contains per-phase logic that runs after each phase completes in _execute_pipeline.
Extracted from factory_pipeline.py to keep that file under 600 lines.

Each hook function takes:
  phase_name, phase_result, run_id, project_dir, accumulated_context, domain, client_id
and mutates accumulated_context in-place.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


async def run_phase_hooks(
    phase_name: str,
    phase_result: Dict[str, Any],
    run_id: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
    domain: str,
    client_id: str,
    emit_fn: Callable,
    get_control_fn: Callable,
    set_control_fn: Callable,
    publish_event_fn: Callable,
    run_phase_fn: Callable,
    background_tasks: set,
    messages_module: Any,
    phase_input: Any = None,
) -> None:
    """Run all post-phase hooks for the given phase. Mutates accumulated_context in-place."""
    org_id = accumulated_context.get("org_id")

    await _hook_persist_live_url(phase_name, phase_result, run_id, accumulated_context)
    await _hook_p01_intake(
        phase_name, project_dir, run_id, accumulated_context,
        emit_fn, get_control_fn, set_control_fn, publish_event_fn,
    )
    await _hook_p00_research(phase_name, project_dir, accumulated_context)
    await _hook_p00c_architecture_planner(phase_name, project_dir, accumulated_context)
    await _hook_p02_architecture(phase_name, phase_result, project_dir, accumulated_context)
    await _hook_p01b_integration_discovery(phase_name, project_dir, accumulated_context)
    await _hook_p02c_permission_modeling(phase_name, project_dir, accumulated_context)
    await _hook_p02b_domain_ir(phase_name, phase_result, project_dir, accumulated_context)
    await _hook_p04_backend(
        phase_name, project_dir, run_id, domain, client_id, accumulated_context,
        run_phase_fn, background_tasks, messages_module,
    )
    await _hook_quality_gate(
        phase_name, project_dir, run_id, org_id, accumulated_context,
        emit_fn, run_phase_fn, background_tasks, phase_input, messages_module,
    )


async def _hook_quality_gate(
    phase_name: str,
    project_dir: Path,
    run_id: str,
    org_id: Optional[str],
    accumulated_context: Dict[str, Any],
    emit_fn: Callable,
    run_phase_fn: Callable,
    background_tasks: set,
    phase_input: Any,
    messages_module: Any,
) -> None:
    """After p07_testing: run quality gate and self-healing loop (up to 3 attempts)."""
    if phase_name != "p07_testing":
        return
    from aether_os.core.quality.metrics import score_project
    from aether_os.core.errors import PipelineBlockedError

    for attempt in range(1, 4):
        quality = score_project(project_dir)
        if quality.total >= 80:
            logger.info("[quality] Gate passed: %.1f%%", quality.total)
            await emit_fn({"type": "quality_gate_passed", "score": quality.total}, run_id=run_id)
            return

        if attempt < 3:
            msg = f"Quality score {quality.total:.1f}% < 80% — running self-healing attempt {attempt}/3"
            logger.info("[quality] %s", msg)
            await emit_fn({"type": "llm_chunk", "phase": "quality_gate", "text": msg}, run_id=run_id)
            await run_phase_fn("p07b_self_healing", phase_input)
        else:
            logger.error("[quality] Gate failed after 3 attempts. Final score: %.1f%%", quality.total)
            if org_id:
                _pname = accumulated_context.get("project_name") or f"run-{run_id[:8]}"

                async def _notify_she(_rid=run_id, _oid=org_id, _pn=_pname):
                    try:
                        from aether_os.core.db import get_session_factory as _gsf_she
                        from aether_os.core.models import Notification as _Notif_she
                        _notif = _Notif_she(
                            org_id=_oid,
                            type="self_healing_exhausted",
                            title=f"Self-healing exhausted for {_pn}",
                            message="All 3 self-healing attempts failed. Quality gate not met.",
                            link=f"/dashboard/runs/{_rid}",
                        )
                        async with _gsf_she()() as _s:
                            _s.add(_notif)
                            await _s.commit()
                    except Exception as _ne:
                        logger.debug("[pipeline] self_healing_exhausted notification failed: %s", _ne)

                _t = asyncio.create_task(_notify_she())
                background_tasks.add(_t)
                _t.add_done_callback(background_tasks.discard)
            raise PipelineBlockedError(
                f"Quality gate failed after 3 improvement attempts. Final score: {quality.total:.1f}%"
            )


async def _hook_persist_live_url(
    phase_name: str,
    phase_result: Dict[str, Any],
    run_id: str,
    accumulated_context: Dict[str, Any],
) -> None:
    """Persist live_url to runs table after p11_deployment."""
    if phase_name != "p11_deployment":
        return
    _live_url = phase_result.get("metadata", {}).get("live_url")
    if not _live_url:
        return
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


async def _hook_p01_intake(
    phase_name: str,
    project_dir: Path,
    run_id: str,
    accumulated_context: Dict[str, Any],
    emit_fn: Callable,
    get_control_fn: Callable,
    set_control_fn: Callable,
    publish_event_fn: Callable,
) -> None:
    """After p01: extract project name from intake JSON and optionally run spec review gate."""
    if phase_name != "p01_intake_requirements":
        return

    _intake_path = project_dir / "p01_intake_requirements" / "intake" / "intake.json"
    try:
        if _intake_path.exists():
            _intake = json.loads(_intake_path.read_text())
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
    if accumulated_context.get("decision_mode") != "autonomous":
        try:
            from aether_os.orchestrator.spec_review_gate import run_spec_review_gate
            await run_spec_review_gate(
                run_id=run_id,
                accumulated_context=accumulated_context,
                emit_fn=emit_fn,
                get_control_fn=get_control_fn,
                set_control_fn=set_control_fn,
                publish_event_fn=publish_event_fn,
            )
        except RuntimeError:
            raise
        except Exception as _sr_exc:
            logger.warning("[pipeline] Spec review gate error (non-fatal): %s", _sr_exc)


async def _hook_p00_research(
    phase_name: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After p00_research: load build_profile and domain_knowledge from design_brief.json."""
    if phase_name != "p00_research":
        return
    _brief_path = project_dir / "p00_research" / "design_brief.json"
    if not _brief_path.exists():
        return
    try:
        _brief = json.loads(_brief_path.read_text())
        _bp = _brief.get("build_profile")
        if _bp:
            accumulated_context["build_profile"] = _bp
            logger.info(
                "[pipeline] build_profile loaded: %s (backend=%s, arch=%s)",
                _bp.get("name"), _bp.get("backend_lang"), _bp.get("architecture"),
            )
    except Exception as _e:
        logger.warning("[pipeline] Failed to load build_profile from design_brief: %s", _e)
    try:
        _brief = json.loads(_brief_path.read_text())
        _dk = _brief.get("domain_knowledge")
        if _dk:
            accumulated_context["domain_knowledge"] = _dk
            logger.info(
                "[pipeline] domain_knowledge propagated: domain=%s, entities=%d",
                _dk.get("domain"), len(_dk.get("entity_names", [])),
            )
    except Exception as _e:
        logger.warning("[pipeline] Failed to propagate domain_knowledge: %s", _e)


async def _hook_p00c_architecture_planner(
    phase_name: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After p00c: load service_map.json into accumulated_context."""
    if phase_name != "p00c_architecture_planner":
        return
    _sm_path = project_dir / "p00c_architecture_planner" / "service_map.json"
    if not _sm_path.exists():
        return
    try:
        _sm = json.loads(_sm_path.read_text())
        if _sm.get("services"):
            accumulated_context["service_map"] = _sm
            logger.info(
                "[pipeline] service_map loaded: %d services, bus=%s",
                len(_sm["services"]), _sm.get("message_bus", ""),
            )
    except Exception as _e:
        logger.warning("[pipeline] Failed to load service_map: %s", _e)


async def _hook_p02_architecture(
    phase_name: str,
    phase_result: Dict[str, Any],
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After p02_architecture: load architecture.json and build knowledge graph."""
    if phase_name != "p02_architecture":
        return

    # Load architecture.json
    _arch_candidates = []
    _op = phase_result.get("output_path", "")
    if _op:
        _arch_candidates.append(Path(_op))
    _arch_candidates.append(project_dir / "p02_architecture" / "architecture.json")
    for _cand in _arch_candidates:
        if _cand.exists():
            try:
                accumulated_context["architecture_json"] = json.loads(_cand.read_text())
                accumulated_context["p02_architecture_path"] = str(_cand)
                logger.info("[pipeline] architecture_json loaded from %s", _cand)
                break
            except Exception as _e:
                logger.warning("[pipeline] Failed to load architecture_json from %s: %s", _cand, _e)
    else:
        logger.warning("[pipeline] architecture.json not found after p02 — downstream phases will use their own fallbacks")

    # Build knowledge graph
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
        _endpoints = [f"{e.get('method')} {e.get('path')}" for e in _arch.get("api_endpoints", [])[:10]]
        _models = [t.get("table", t.get("name")) for t in _arch.get("database_schema", [])[:8]]
        accumulated_context["graph_context"] = {
            "domain": _domain, "tech_stack": _ts, "endpoints": _endpoints,
            "models": _models, "graph_stats": _kg.stats(),
        }
        _kg_path = str(project_dir / "knowledge_graph.gpickle")
        _kg.persist(_kg_path)
        accumulated_context["knowledge_graph_path"] = _kg_path
        logger.info("[RAG] Knowledge graph built: %d nodes, %d endpoints, %d models",
                    _kg.stats()["node_count"], len(_endpoints), len(_models))
    except Exception as _kg_exc:
        logger.warning("[RAG] Knowledge graph build failed: %s", _kg_exc)


async def _hook_p01b_integration_discovery(
    phase_name: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After p01b: load integration_map.json."""
    if phase_name != "p01b_integration_discovery":
        return
    _imap_path = project_dir / "p01b_integration_discovery" / "integration_map.json"
    if not _imap_path.exists():
        return
    try:
        accumulated_context["integration_map"] = json.loads(_imap_path.read_text())
        logger.info("[pipeline] integration_map loaded from %s", _imap_path)
    except Exception as _e:
        logger.warning("[pipeline] Failed to load integration_map: %s", _e)


async def _hook_p02c_permission_modeling(
    phase_name: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After p02c: load permission_model.json."""
    if phase_name != "p02c_permission_modeling":
        return
    _perm_path = project_dir / "p02c_permission_modeling" / "permission_model.json"
    if not _perm_path.exists():
        return
    try:
        accumulated_context["permission_model"] = json.loads(_perm_path.read_text())
        logger.info("[pipeline] permission_model loaded from %s", _perm_path)
    except Exception as _e:
        logger.warning("[pipeline] Failed to load permission_model: %s", _e)


async def _hook_p02b_domain_ir(
    phase_name: str,
    phase_result: Dict[str, Any],
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After p02b: load domain_ir_path."""
    if phase_name != "p02b_domain_ir":
        return
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


async def _hook_p04_backend(
    phase_name: str,
    project_dir: Path,
    run_id: str,
    domain: str,
    client_id: str,
    accumulated_context: Dict[str, Any],
    run_phase_fn: Callable,
    background_tasks: set,
    messages_module: Any,
) -> None:
    """After p04_backend: S11 merge, api_routes propagation, pattern injection, BackendAuditCouncil."""
    if phase_name != "p04_backend":
        return

    PhaseInput = messages_module.PhaseInput

    # S11: merge generated code into p03 scaffolding tree
    _p04_src = project_dir / "p04_backend" / "backend_codegen" / "src"
    _p03_dir = project_dir / "p03_scaffolding"
    _scaffold_dirs = [d for d in _p03_dir.iterdir() if d.is_dir()] if _p03_dir.exists() else []
    if _p04_src.exists() and _scaffold_dirs:
        _scaffold_root = _scaffold_dirs[0]
        _dest_src = _scaffold_root / "src"
        _dest_src.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(_p04_src), str(_dest_src), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        logger.info("[pipeline] S11: merged p04 src tree → %s", _dest_src)
        accumulated_context["backend_src_dir"] = str(_dest_src)
        accumulated_context["backend_main_py"] = str(_dest_src / "main.py")
    else:
        if _p04_src.exists():
            accumulated_context["backend_src_dir"] = str(_p04_src)
            accumulated_context["backend_main_py"] = str(_p04_src / "main.py")

    # Propagate api_routes.json
    _routes_candidate = project_dir / "p04_backend" / "backend_codegen" / "api_routes.json"
    if not _routes_candidate.exists():
        _routes_candidate = project_dir / "p04_backend" / "api_routes.json"
    if _routes_candidate.exists():
        accumulated_context["api_routes_path"] = str(_routes_candidate)
        logger.info("[pipeline] api_routes_path → %s", _routes_candidate)

    # Pattern library injection
    try:
        from aether_os.phases.patterns import PatternSelector as _PS
        _ir_for_patterns = accumulated_context.get("domain_ir", {})
        if not _ir_for_patterns:
            _ir_path_for_patterns = accumulated_context.get("domain_ir_path", "")
            if _ir_path_for_patterns:
                try:
                    _ir_for_patterns = json.loads(Path(_ir_path_for_patterns).read_text())
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

    # BackendAuditCouncil — blocking re-generation feedback loop
    _BAC_THRESHOLD = float(os.environ.get("COUNCIL_THRESHOLD", "0.70"))
    _bac_main_candidates = [
        project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
        project_dir / "p04_backend" / "src" / "main.py",
        project_dir / "src" / "main.py",
    ]
    _bac_main_py = next((p for p in _bac_main_candidates if p.exists()), None)
    if not _bac_main_py:
        logger.debug("[BackendAuditCouncil] main.py not found, skipping")
        return

    for _bac_attempt in range(3):
        try:
            from aether_os.core.council.council_reviewer import run_council
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
                json.dumps(_bac_report_dict, indent=2)
            )
            accumulated_context["council_review"] = _bac_report_dict
            logger.info(
                "[BackendAuditCouncil] run %s attempt %d: avg_score=%.2f issues=%d",
                run_id, _bac_attempt + 1,
                _bac_report.average_score, len(_bac_report.consensus_issues),
            )

            if _bac_report.average_score >= _BAC_THRESHOLD or _bac_attempt >= 2:
                break

            _bac_issues_text = "\n".join(
                f"- {iss}" for iss in (_bac_report.consensus_issues or [])
            )
            accumulated_context["council_feedback"] = (
                f"BackendAuditCouncil scored {_bac_report.average_score:.2f}/1.0 "
                f"(attempt {_bac_attempt + 1}). Fix before generating:\n"
                f"{_bac_issues_text}"
            )
            logger.info(
                "[BackendAuditCouncil] score %.2f < %.2f — re-running p04_backend (retry %d/2)",
                _bac_report.average_score, _BAC_THRESHOLD, _bac_attempt + 1,
            )
            _bac_retry_input = PhaseInput(
                run_id=run_id, project_id=run_id, phase="p04_backend",
                input_data=accumulated_context, output_dir=str(project_dir),
                domain=domain, client_id=client_id,
            )
            try:
                await asyncio.wait_for(
                    run_phase_fn("p04_backend", _bac_retry_input),
                    timeout=600.0,
                )
                # Re-do S11 merge so downstream phases see improved code
                _bac_p04_src = project_dir / "p04_backend" / "backend_codegen" / "src"
                _bac_p03_dir = project_dir / "p03_scaffolding"
                _bac_scaffold_dirs = (
                    [d for d in _bac_p03_dir.iterdir() if d.is_dir()]
                    if _bac_p03_dir.exists() else []
                )
                if _bac_p04_src.exists() and _bac_scaffold_dirs:
                    _bac_dest = _bac_scaffold_dirs[0] / "src"
                    _bac_dest.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(
                        str(_bac_p04_src), str(_bac_dest),
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                    accumulated_context["backend_src_dir"] = str(_bac_dest)
                    accumulated_context["backend_main_py"] = str(_bac_dest / "main.py")
                    logger.info("[BackendAuditCouncil] S11 re-merge → %s", _bac_dest)
                _bac_main_py = next((p for p in _bac_main_candidates if p.exists()), None)
                if not _bac_main_py:
                    logger.warning("[BackendAuditCouncil] main.py missing after retry")
                    break
            except Exception as _bac_retry_exc:
                logger.warning("[BackendAuditCouncil] p04 retry failed: %s — stopping loop", _bac_retry_exc)
                break
        except Exception as _bac_exc:
            logger.warning("[BackendAuditCouncil] council failed (non-fatal): %s", _bac_exc)
            break
