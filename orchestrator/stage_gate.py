"""Stage outcome rules: what blocks a run, and which stages an org may switch off.

Kept apart from factory_pipeline.py so the sequential path and the parallel-wave
path apply the same rules.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import PhaseConfig

logger = logging.getLogger(__name__)

# Stages an org cannot switch off, with the reason recorded when a disable is ignored.
# Everything else in the sequence (s08, s10, s12) produces output no other stage or
# gate reads, and may be skipped.
MANDATORY_STAGES: Dict[str, str] = {
    "s01_intake": "every later stage builds from its requirements",
    "s02_architecture": "all code generation reads its domain model",
    "s03_backend": "the frontend, quality, testing and deploy stages need the backend",
    "s04_frontend": "s05, s06, s09 and s12 read its output; request frontend 'none' to build without a UI",
    "s05_quality": "security and quality review is a blocking check and feeds healing",
    "s06_testing": "healing needs its test summary",
    "s07_healing": "it applies the quality-score gate that decides whether the run may ship",
    "s09_devops": "a run is done only when the deployed app answers at its live URL",
    "s11_handoff": "it produces the quality report and the delivery",
}


def gate_block_reason(stage: str, result: Dict[str, Any],
                      critical_stages: FrozenSet[str]) -> Optional[str]:
    """Why this stage result must end the run, or None if the run may continue.

    "escalated" means the stage's gate still failed after its retries; gates block
    for every stage. A crash or timeout ("failed"/"timeout") blocks for critical
    stages only: the others are allowed to leave a partial deliverable.
    """
    status = result.get("status")
    if status == "escalated":
        issues = "; ".join(str(i) for i in (result.get("issues") or []) if i)
        return f"Stage {stage} did not pass its gate after retries: {issues or 'no reason given'}"
    if status in ("failed", "timeout") and stage in critical_stages:
        return f"Stage {stage} {status}: {result.get('error') or 'no reason given'}"
    return None


def recorded_status(result: Dict[str, Any]) -> str:
    """The status stored on the stage row: what happened, never an upgrade to "completed"."""
    status = result.get("status")
    if status in ("passed", "skipped", "failed", "timeout"):
        return status
    return "failed" if status == "escalated" else "completed"


async def load_disabled_stages(org_id: Optional[str]) -> Set[str]:
    """Stage ids this org has switched off in Settings (phase_configs.enabled = 0).

    If the settings cannot be read, nothing is treated as disabled: running a stage
    the org wanted skipped is the safe direction, silently skipping one is not.
    """
    if not org_id:
        return set()
    try:
        async with get_session_factory()() as session:
            rows = await session.execute(
                select(PhaseConfig.phase_name).where(
                    PhaseConfig.org_id == org_id, PhaseConfig.enabled == 0))
            return {name for (name,) in rows.all()}
    except Exception as exc:
        logger.warning("[stage_gate] could not read stage toggles for org %s; "
                       "running every stage: %s", org_id, exc)
        return set()


def apply_stage_toggles(
    stages: List[str], disabled: Iterable[str],
) -> Tuple[List[str], List[str], Dict[str, str]]:
    """Split `stages` by the org's toggles.

    Returns (stages to run, optional stages to skip, {mandatory stage: why its
    disable was ignored}).
    """
    off = set(disabled)
    skipped = [s for s in stages if s in off and s not in MANDATORY_STAGES]
    ignored = {s: MANDATORY_STAGES[s] for s in stages if s in off and s in MANDATORY_STAGES}
    return [s for s in stages if s not in skipped], skipped, ignored
