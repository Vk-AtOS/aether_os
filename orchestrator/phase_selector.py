"""
Phase selection helpers extracted from factory_pipeline.py.

Covers two concerns:
  1. Slicing the phase sequence for a run (start_phase override + checkpoint resume).
  2. Mapping affected-area names to concrete phase names for change requests.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Maps human-readable area names (as supplied in change-request API calls) to the
# canonical phase name that is the first phase that must re-run for that area.
AREA_TO_PHASE: Dict[str, str] = {
    # Current s0x_* stage names (post-July-2026 refactor)
    "intake":          "s01_intake",
    "requirements":    "s01_intake",
    "architecture":    "s02_architecture",
    "scaffolding":     "s02_architecture",
    "backend":         "s03_backend",
    "api":             "s03_backend",
    "database":        "s03_backend",
    "frontend":        "s04_frontend",
    "ui":              "s04_frontend",
    "ux":              "s04_frontend",
    "security":        "s05_quality",
    "review":          "s05_quality",
    "testing":         "s06_testing",
    "tests":           "s06_testing",
    "healing":         "s07_healing",
    "cicd":            "s09_devops",
    "ci":              "s09_devops",
    "cd":              "s09_devops",
    "observability":   "s08_observability",
    "monitoring":      "s08_observability",
    "docs":            "s11_handoff",
    "documentation":   "s11_handoff",
    "deployment":      "s09_devops",
    "deploy":          "s09_devops",
    "enterprise":      "s10_enterprise",
    "handoff":         "s11_handoff",
}


# The one mapping from pre-refactor phase ids to the stage that now contains them.
# The 12 stage ids are canonical; these are accepted only so old runs, old
# checkpoints and old clients keep working. Built from each stage's sub-phase list.
_STAGE_SUB_PHASES: Dict[str, Tuple[str, ...]] = {
    "s01_intake": ("p00_intake", "p00a_intake", "p00_research", "p00b_data_archaeology",
                   "p00c_architecture_planner", "p01_requirements",
                   "p01_intake_requirements", "p01b_integration_discovery"),
    "s02_architecture": ("p02_architecture", "p02b_domain_ir", "p02c_permission_modeling",
                         "p03_scaffolding"),
    "s03_backend": ("p04_backend", "p04a_backend_codegen", "p04b_business_logic",
                    "p04c_integration_codegen"),
    "s04_frontend": ("p04_uiux_design", "p05_frontend"),
    "s05_quality": ("p06_review_security", "p06b_formal_verification"),
    "s06_testing": ("p07_testing", "p07a_unit_testing", "p07b_performance_testing",
                    "p07c_accessibility_testing", "p07d_e2e_testing"),
    "s07_healing": ("p07b_self_healing",),
    "s08_observability": ("p09_observability", "p11a_monitoring", "p11b_error_tracking",
                          "p11c_analytics", "p11d_alerting"),
    "s09_devops": ("p08_cicd", "p08_cicd_deployment", "p11_deployment",
                   "p11e_enterprise_deployment"),
    "s10_enterprise": ("p12a_feature_flags", "p12b_ab_testing", "p13_app_memory", "p16_iam",
                       "p17_control_plane", "p18_billing_metering", "p21_sre_agent"),
    "s11_handoff": ("p09_documentation", "p10_docs_delivery", "p14_client_portal",
                    "p15_handoff"),
    "s12_specialist": ("p05b_mobile", "p05c_desktop", "p05d_cli", "p05e_serverless",
                       "p19_service_catalog", "p20_multiregion"),
}
LEGACY_STAGE_IDS: Dict[str, str] = {
    legacy: stage for stage, subs in _STAGE_SUB_PHASES.items() for legacy in subs
}


def canonical_stage_id(stage_id: str, phase_sequence: List[str]) -> str:
    """Return the canonical stage id for a stage id or a legacy phase id.

    Raises ValueError for an id that is neither: an unknown id must not silently
    turn a "re-run from X" into a full rebuild.
    """
    resolved = stage_id if stage_id in phase_sequence else LEGACY_STAGE_IDS.get(stage_id)
    if resolved not in phase_sequence:
        raise ValueError(
            f"Unknown stage id {stage_id!r}; expected one of: {', '.join(phase_sequence)}")
    return resolved


def select_phases(
    phase_sequence: List[str],
    start_phase: Optional[str] = None,
) -> List[str]:
    """Return the slice of *phase_sequence* that should run for this invocation.

    When *start_phase* is supplied, only stages from that point onwards are
    returned (legacy phase ids start at the stage that contains them); an unknown
    id raises ValueError. Without it the full sequence is used.
    """
    if start_phase:
        return phase_sequence[phase_sequence.index(canonical_stage_id(start_phase, phase_sequence)):]
    return list(phase_sequence)


def resolve_change_request_phase(
    affected_areas: List[str],
    phase_sequence: List[str],
    default_phase: str = "s03_backend",
) -> str:
    """Resolve a list of affected area names to the earliest phase that must re-run.

    Returns the phase name of the earliest matched phase, or *default_phase* if
    no area maps to a known phase.
    """
    candidate_indices = []
    for area in (affected_areas or []):
        mapped = AREA_TO_PHASE.get(area.lower().strip())
        if mapped and mapped in phase_sequence:
            candidate_indices.append(phase_sequence.index(mapped))

    if candidate_indices:
        return phase_sequence[min(candidate_indices)]
    return default_phase


async def restore_from_checkpoint(
    run_id: str,
    phase_sequence: List[str],
    phases_to_run: List[str],
    accumulated_context: Dict[str, Any],
    emit_fn,
) -> Tuple[List[str], Dict[str, Any]]:
    """Attempt to restore pipeline state from a DB checkpoint.

    Loads the checkpoint_data from the Run record.  If valid, updates
    *accumulated_context* in-place and returns a sliced *phases_to_run*
    starting from the phase after the last completed one.

    Returns *(phases_to_run, accumulated_context)* — the caller should
    replace its local variables with the returned values.

    Never raises: all errors are logged as warnings and the original
    *phases_to_run* / *accumulated_context* are returned unchanged.
    """
    try:
        from aether_os.core.db import get_session_factory as _gsf
        from aether_os.core.models import Run as _Run
        _sf = _gsf()
        async with _sf() as _sess:
            _run_rec = await _sess.get(_Run, run_id)
            _ckpt = _run_rec.checkpoint_data if _run_rec else None

        if _ckpt and not isinstance(_ckpt, dict):
            logger.warning("[phase_selector] Ignoring malformed checkpoint_data (not a dict) for run %s", run_id)
            _ckpt = None

        if _ckpt and not ("last_completed_phase" in _ckpt and "accumulated_context" in _ckpt):
            logger.warning(
                "[phase_selector] Ignoring checkpoint_data with unexpected schema for run %s "
                "(got keys: %s — expected last_completed_phase + accumulated_context)",
                run_id, list(_ckpt.keys()),
            )
            _ckpt = None

        if _ckpt and _ckpt.get("last_completed_phase"):
            _last_done = _ckpt["last_completed_phase"]
            _saved_ctx = _ckpt.get("accumulated_context") or {}
            # A legacy id names one sub-phase of a stage, which says nothing about the
            # rest of that stage: resume AT the containing stage, not after it.
            _legacy_stage = LEGACY_STAGE_IDS.get(_last_done)
            if (_last_done in phase_sequence or _legacy_stage in phase_sequence) and _saved_ctx:
                accumulated_context.update(_saved_ctx)
                accumulated_context["run_id"] = run_id
                _resume_idx = (phase_sequence.index(_last_done) + 1
                               if _last_done in phase_sequence
                               else phase_sequence.index(_legacy_stage))
                phases_to_run = phase_sequence[_resume_idx:]
                logger.info(
                    "[phase_selector] Resuming run %s from checkpoint after phase %s (%d phases remaining)",
                    run_id, _last_done, len(phases_to_run),
                )
                await emit_fn(
                    {"type": "pipeline_resumed", "resumed_after": _last_done,
                     "phases_remaining": len(phases_to_run)},
                    run_id=run_id,
                )
            else:
                logger.debug("[phase_selector] Checkpoint found but phase %r not in sequence — ignoring", _last_done)

    except Exception as _exc:
        logger.warning("[phase_selector] Checkpoint restore failed (non-fatal): %s", _exc)

    return phases_to_run, accumulated_context
