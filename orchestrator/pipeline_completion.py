"""
AetherOS — Pipeline Completion Tasks

Background tasks and post-pipeline bookkeeping extracted from factory_pipeline.py
to keep that file under 600 lines.

All functions here run after the phase loop completes but before the pipeline
returns. They are background tasks (asyncio.create_task) except for
persist_finished_at which is awaited inline.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def auto_start_app(
    run_id: str,
    org_id: Optional[str],
    publish_event_fn,
) -> None:
    """Launch the generated app after pipeline completes. Non-blocking — runs as a task."""
    try:
        from aether_os.core.services.run_app_service import _launch_generated_app
        _system_user = {"org_id": org_id, "user_id": "system", "role": "admin", "email": "system@aetheros.internal"}
        result = await _launch_generated_app(run_id=run_id, user=_system_user)
        logger.info("Auto-started generated app for run %s: %s", run_id, result)
        await publish_event_fn(run_id, {
            "type": "app_started",
            "run_id": run_id,
            "port": result.get("port"),
            "mode": result.get("mode", "backend"),
            "preview_url": "/app-preview/",
        })
    except Exception as _e:
        logger.warning("Auto-start generated app failed for run %s: %s", run_id, _e)


async def persist_finished_at(run_id: str) -> None:
    """Write finished_at timestamp to the runs table. Awaited inline at pipeline end."""
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


async def create_completion_notification(
    run_id: str,
    org_id: str,
    duration: float,
    phases_to_run: List[str],
    project_name: Optional[str],
) -> None:
    """Create an in-app notification for org members when the pipeline completes."""
    try:
        from aether_os.core.db import get_session_factory as _gsf_n
        from aether_os.core.models import Notification as _Notif
        _pname = project_name or f"run-{run_id[:8]}"
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


async def fire_completion_webhook(
    run_id: str,
    org_id: str,
    duration: float,
    results: Dict[str, Any],
) -> None:
    """Deliver pipeline.complete webhook event to org subscribers."""
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


async def cleanup_redis_keys(run_id: str, clear_run_fn) -> None:
    """Schedule Redis key cleanup after 5 minutes."""
    await asyncio.sleep(300)
    await clear_run_fn(run_id)


def schedule_completion_tasks(
    run_id: str,
    org_id: Optional[str],
    client_id: str,
    domain: str,
    raw_input: str,
    project_name: Optional[str],
    project_dir: Path,
    duration: float,
    results: Dict[str, Any],
    phases_to_run: list,
    accumulated_context: Dict[str, Any],
    background_tasks: set,
    publish_event_fn,
    clear_run_fn,
    delivery_council_check_fn,
    extract_learning_fn,
    store_run_memory_fn,
    embed_artifacts_fn,
    upload_to_s3_fn,
    pm_update_fn,
    pm_changelog_fn,
) -> None:
    """Schedule all post-pipeline background tasks. Called once at end of _execute_pipeline."""

    def _add(coro):
        t = asyncio.create_task(coro)
        background_tasks.add(t)
        t.add_done_callback(background_tasks.discard)
        return t

    # Auto-start generated app
    _add(auto_start_app(run_id, org_id, publish_event_fn))

    # LLM Council delivery check
    _add(delivery_council_check_fn(
        run_id=run_id,
        project_name=project_name,
        raw_input=raw_input,
        domain=domain,
        results=results,
        org_id=org_id,
        accumulated_context=accumulated_context,
    ))

    # In-app notification
    if org_id:
        _add(create_completion_notification(
            run_id=run_id,
            org_id=org_id,
            duration=duration,
            phases_to_run=phases_to_run,
            project_name=accumulated_context.get("project_name") or project_name,
        ))

        # Webhook
        _add(fire_completion_webhook(
            run_id=run_id, org_id=org_id, duration=duration, results=results,
        ))

    # Learning patterns
    _add(extract_learning_fn(
        run_id=run_id, org_id=org_id, client_id=client_id,
        domain=domain, results=results, accumulated_context=accumulated_context,
    ))

    # D6: Finalize project living memory (synchronous — fast)
    pm_update_fn(project_dir, {"tech_stack": accumulated_context.get("architecture_json", {}).get("tech_stack", {})})
    pm_changelog_fn(project_dir, f"Pipeline completed in {round(duration, 1)}s — {len(phases_to_run)} phases", author="system")

    # Redis key cleanup (after 5 minutes)
    _add(cleanup_redis_keys(run_id, clear_run_fn))

    # Cross-run memory
    _add(store_run_memory_fn(
        run_id=run_id, org_id=org_id, raw_input=raw_input,
        domain=domain, results=results,
    ))

    # Artifact embedding
    _add(embed_artifacts_fn(
        run_id=run_id, project_dir=project_dir, results=results, org_id=org_id,
    ))

    # S3 upload
    _add(upload_to_s3_fn(run_id=run_id, project_dir=project_dir))
