"""
AetherOS — Factory Run Post-Build Cleanup / Maintenance Hooks
Extracted from factory_run_background.py to keep it under 400 lines.

Contains post-pipeline-completion hooks (non-fatal, all exceptions logged):
  1. Persist quality score to the runs table
  2. Record GlobalPattern aggregate learning entry
  3. Extract learning-loop patterns from the completed run
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def run_post_build_hooks(
    *,
    run_id: str,
    domain: str,
    user_id: Optional[str],
    org_id: str,
) -> None:
    """Execute all post-build maintenance hooks for a completed pipeline run.

    Every hook is independently wrapped so a failure in one never silences the
    others.  All exceptions are logged at debug/info level — these are
    best-effort background tasks, not business-critical paths.
    """
    # 1. Persist quality score to runs table
    try:
        from aether_os.core.quality.metrics import score_project
        from aether_os.core.projects import get_project_manager
        from aether_os.core.db import get_session_factory as _gsf_qs
        from aether_os.core.models import Run as _Run_qs
        from sqlalchemy import update as _upd_qs
        _project_dir = get_project_manager().get_project_dir(run_id)
        if _project_dir.exists():
            _qscore = score_project(_project_dir)
            async with _gsf_qs()() as _s_qs:
                await _s_qs.execute(
                    _upd_qs(_Run_qs).where(_Run_qs.id == run_id)
                    .values(quality_score=int(_qscore.total))
                )
                await _s_qs.commit()
            logger.info("[post-build] quality_score=%d saved for run %s", _qscore.total, run_id)
    except Exception as _qse:
        logger.debug("[post-build] quality score persist skipped: %s", _qse)

    # 2. Record GlobalPattern aggregate learning
    try:
        from aether_os.core.quality.metrics import score_project as _sp2
        from aether_os.core.projects import get_project_manager as _gpm2
        from aether_os.core.db import get_session_factory as _gsf_gp2
        from aether_os.core.services.global_pattern_service import record_global_pattern
        _project_dir2 = _gpm2().get_project_dir(run_id)
        if _project_dir2.exists():
            _qscore2 = _sp2(_project_dir2)
            async with _gsf_gp2()() as _s_gp:
                await record_global_pattern(
                    run_id=run_id,
                    domain=domain or "general",
                    quality_score_total=float(_qscore2.total),
                    quality_details=_qscore2.details,
                    session=_s_gp,
                )
            logger.info(
                "[post-build] GlobalPattern recorded domain=%s score=%.1f",
                domain, _qscore2.total,
            )
    except Exception as _gpe:
        logger.debug("[post-build] GlobalPattern skipped: %s", _gpe)

    # 3. Learning loop — extract patterns from completed run
    if user_id and org_id:
        try:
            from aether_os.core.services import learning_service as _ls2
            from aether_os.core.db import get_session_factory as _gsf_ls
            async with _gsf_ls()() as _s_ls:
                await _ls2.extract_patterns_from_run(run_id, org_id, user_id, _s_ls)
            logger.info("[post-build] Learning patterns extracted for user %s", user_id)
        except Exception as _le:
            logger.debug("[post-build] Learning loop skipped: %s", _le)
