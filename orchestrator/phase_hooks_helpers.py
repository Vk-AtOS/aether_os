"""
AetherOS — Phase Hooks Helpers
Small stateless utilities extracted from phase_hooks.py (L7 fix) to keep
that file under the 600-line limit.  All helpers are pure file-loaders or
context-mutators with no orchestration logic.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def hook_persist_live_url(
    phase_name: str,
    phase_result: Dict[str, Any],
    run_id: str,
    accumulated_context: Dict[str, Any],
) -> None:
    """Persist live_url to runs table after s09_devops."""
    if phase_name != "s09_devops":
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


async def hook_load_research(
    phase_name: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After s01_intake: load build_profile and domain_knowledge from design_brief.json."""
    if phase_name != "s01_intake":
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


async def hook_load_architecture_planner(
    phase_name: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After s01_intake: load service_map.json into accumulated_context."""
    if phase_name != "s01_intake":
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


async def hook_load_integration_discovery(
    phase_name: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After s01_intake: load integration_map.json."""
    if phase_name != "s01_intake":
        return
    _imap_path = project_dir / "p01b_integration_discovery" / "integration_map.json"
    if not _imap_path.exists():
        return
    try:
        accumulated_context["integration_map"] = json.loads(_imap_path.read_text())
        logger.info("[pipeline] integration_map loaded from %s", _imap_path)
    except Exception as _e:
        logger.warning("[pipeline] Failed to load integration_map: %s", _e)


async def hook_load_permission_model(
    phase_name: str,
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After s02_architecture: load permission_model.json."""
    if phase_name != "s02_architecture":
        return
    _perm_path = project_dir / "p02c_permission_modeling" / "permission_model.json"
    if not _perm_path.exists():
        return
    try:
        accumulated_context["permission_model"] = json.loads(_perm_path.read_text())
        logger.info("[pipeline] permission_model loaded from %s", _perm_path)
    except Exception as _e:
        logger.warning("[pipeline] Failed to load permission_model: %s", _e)


async def hook_load_domain_ir(
    phase_name: str,
    phase_result: Dict[str, Any],
    project_dir: Path,
    accumulated_context: Dict[str, Any],
) -> None:
    """After s02_architecture: load domain_ir_path."""
    if phase_name != "s02_architecture":
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

    # C7: persist domain IR to knowledge graph so future similar-domain runs benefit
    try:
        from aether_os.core.knowledge_graph_integration import save_ir_to_knowledge_graph as _save_kg
        _save_kg(accumulated_context)
    except Exception as _kg_exc:
        logger.debug("[pipeline] knowledge_graph save failed (non-fatal): %s", _kg_exc)
