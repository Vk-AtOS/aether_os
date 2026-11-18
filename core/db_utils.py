"""
AetherOS — Async DB Utilities
Replaces all raw sqlite3.connect() calls that were blocking the FastAPI event loop.
These functions use SQLAlchemy async ORM exclusively.
All functions are safe to await from async FastAPI route handlers.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func
from .db import get_session_factory
from .db import get_session_factory as _gsf
from .models import Notification, User
from .models import PhaseCompletion
from .models import PhaseConfig
from .models import Run
from .models import RunMetadata
from . import notification_prefs
from .notifications.email import get_email_notifier
from sqlalchemy import update as sa_update
from sqlalchemy.orm import selectinload
import os
logger = logging.getLogger(__name__)
# Strong reference set so background notification tasks are not garbage collected
_background_notify_tasks: set = set()
# ── Run queries ───────────────────────────────────────────────────────────────
async def get_run_list(
    org_id: str,
    limit: int = 100,
    offset: int = 0,
    cursor: Optional[float] = None,
) -> Dict[str, Any]:
    """Return paginated run history for an org.
    Supports two pagination modes:
    - Cursor-based (preferred): pass cursor=<started_at float> to get the next page.
      Returns {"items": [...], "total": int, "next_cursor": float|None}.
    - Offset-based (legacy): pass offset=N. Slower at high page numbers but kept for
      backward compatibility with callers that haven't migrated yet.
    Returns {"items": [...], "total": int, "next_cursor": float|None}.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Total count (separate query, cheap with index on org_id)
        count_stmt = select(func.count()).select_from(Run).where(Run.org_id == org_id)
        total: int = (await session.execute(count_stmt)).scalar_one()
        if total == 0:
            return {"items": [], "total": 0, "next_cursor": None}
        # Cursor-based pagination: seek rows older than cursor timestamp
        # (started_at DESC ordering — cursor is the started_at of the last seen row)
        base_filter = Run.org_id == org_id
        if cursor is not None:
            # Fetch limit+1 to detect whether there is a next page
            stmt = (
                select(Run)
                .where(base_filter, Run.started_at < cursor)
                .order_by(Run.started_at.desc())
                .limit(limit + 1)
            )
        else:
            # No cursor: use offset for the first page (or legacy callers)
            stmt = (
                select(Run)
                .where(base_filter)
                .order_by(Run.started_at.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        result = await session.execute(stmt)
        all_rows = result.scalars().all()
        has_more = len(all_rows) > limit
        runs = all_rows[:limit]
        if not runs:
            return {"items": [], "total": total, "next_cursor": None}
        run_ids = [r.id for r in runs]
        # Latest phase per run (one query for all runs)
        phase_stmt = (
            select(PhaseCompletion.run_id, PhaseCompletion.phase_name)
            .where(
                PhaseCompletion.run_id.in_(run_ids),
                PhaseCompletion.phase_name != "pipeline",
            )
            .order_by(PhaseCompletion.updated_at.desc())
        )
        phase_rows = (await session.execute(phase_stmt)).all()
        phase_map: Dict[str, str] = {}
        for rid, pname in phase_rows:
            if rid not in phase_map:
                phase_map[rid] = pname
        # Priorities
        prio_stmt = select(RunMetadata.run_id, RunMetadata.priority).where(
            RunMetadata.run_id.in_(run_ids)
        )
        prio_rows = (await session.execute(prio_stmt)).all()
        prio_map: Dict[str, str] = {rid: prio for rid, prio in prio_rows}
    formatted = []
    for run in runs:
        cmd = run.command or "Untitled Project"
        d: Dict[str, Any] = {
            "id":            run.id,
            "project_name":  run.project_name or (cmd[9:] if cmd.startswith("factory: ") else cmd),
            "command":       cmd,
            "status":        run.status,
            "cost":          run.cost or 0.0,
            "started_at":    int(run.started_at * 1000) if run.started_at else None,
            "finished_at":   int(run.finished_at * 1000) if run.finished_at else None,
            "live_url":      run.live_url,
            "current_phase": phase_map.get(run.id),
            # DB-H2: Run.phases JSON was a dual-write shortcut that could diverge from
            # phase_completions (the authoritative source). List view omits phase detail;
            # callers needing full phase status use get_run_detail() which reads phase_completions.
            "phases":        {},
            "priority":      prio_map.get(run.id, "normal"),
            "domain":        run.domain,
            "client_id":     run.client_id,
        }
        formatted.append(d)
    # Provide next_cursor so callers can avoid OFFSET on subsequent pages.
    # next_cursor is the started_at float of the oldest item in this page.
    next_cursor: Optional[float] = runs[-1].started_at if has_more and runs else None
    return {"items": formatted, "total": total, "next_cursor": next_cursor}
async def get_run_detail(run_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
    """Return full run detail with phase_completions and events."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(Run)
            .options(
                selectinload(Run.phase_completions),
                selectinload(Run.events),
            )
            .where(Run.id == run_id)
        )
        if org_id:
            stmt = stmt.where(Run.org_id == org_id)
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            return {}
        # Priority
        pm = await session.get(RunMetadata, run_id)
        priority = pm.priority if pm else "normal"
    phases: Dict[str, Any] = {}
    for pc in (run.phase_completions or []):
        phases[pc.phase_name] = {
            "status":     pc.status,
            "duration_s": pc.duration_s,
            "updated_at": pc.updated_at,
        }
    events = [
        {
            "id":        ev.id,
            "agent":     ev.agent,
            "action":    ev.action,
            "detail":    ev.detail,
            "timestamp": ev.timestamp,
        }
        for ev in sorted(run.events or [], key=lambda e: e.timestamp or 0)
    ]
    cmd = run.command or "Untitled Project"
    return {
        "id":           run.id,
        "run_id":       run.id,
        "project_name": run.project_name or (cmd[9:] if cmd.startswith("factory: ") else cmd),
        "command":      cmd,
        "status":       run.status,
        "started_at":   int(run.started_at * 1000) if run.started_at else None,
        "finished_at":  int(run.finished_at * 1000) if run.finished_at else None,
        "cost":         run.cost or 0.0,
        "live_url":     run.live_url,
        "current_phase": run.current_phase,
        "phases":       phases,
        "events":       events,
        "priority":     priority,
        "domain":       run.domain,
        "client_id":    run.client_id,
        "raw_input":    run.raw_input,
        "requirement":  run.requirement,
        "message":      run.message,
        "self_test_report": run.self_test_report,
        "council_delivery": run.council_delivery,
    }
async def set_run_priority(run_id: str, org_id: str, priority: str) -> bool:
    """Upsert priority for a run. Returns False if run not found or org mismatch."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Verify org ownership
        run = await session.get(Run, run_id)
        if not run or run.org_id != org_id:
            return False
        pm = await session.get(RunMetadata, run_id)
        if pm:
            pm.priority = priority
            pm.updated_at = time.time()
        else:
            session.add(RunMetadata(run_id=run_id, priority=priority, updated_at=time.time()))
        await session.commit()
    return True
async def record_phase_completion(
    run_id: str,
    phase_name: str,
    status: str,
    duration_s: Optional[float] = None,
) -> None:
    """Upsert a phase completion record."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        pc = await session.get(PhaseCompletion, (run_id, phase_name))
        if pc:
            pc.status = status
            pc.duration_s = duration_s
            pc.updated_at = time.time()
        else:
            session.add(PhaseCompletion(
                run_id=run_id,
                phase_name=phase_name,
                status=status,
                duration_s=duration_s,
                updated_at=time.time(),
            ))
        await session.commit()
async def update_run_status(
    run_id: str,
    status: str,
    org_id: Optional[str] = None,
    current_phase: Optional[str] = None,
    message: Optional[str] = None,
) -> bool:
    """Update run status (and optionally current_phase / message). Returns False if not found."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        run = await session.get(Run, run_id)
        if not run:
            return False
        if org_id and run.org_id != org_id:
            return False
        run.status = status
        if current_phase is not None:
            run.current_phase = current_phase
        if message is not None:
            run.message = message[:2000]
        if status in ("completed", "failed", "cancelled", "gated"):
            run.finished_at = time.time()
        await session.commit()
        if status in ("completed", "failed") and run.org_id:
            _emit_run_notification(run, status)
    return True
def _emit_run_notification(run, status: str) -> None:
    """Fire-and-forget task to create an in-app notification and send email on run completion/failure."""
    async def _create():
        try:
            title = (
                f"Run completed: {run.project_name or run.id[:8]}"
                if status == "completed"
                else f"Run failed: {run.project_name or run.id[:8]}"
            )
            msg = "Pipeline finished successfully." if status == "completed" else "Pipeline encountered an error."
            notif = Notification(
                org_id=run.org_id,
                user_id=run.user_id,
                type=f"run_{status}",
                title=title,
                message=msg,
                link=f"/project/{run.id}",
            )
            async with _gsf()() as sess:
                sess.add(notif)
                await sess.commit()
                # Get user email for email notification
                if run.user_id and await notification_prefs.allows(run.org_id, run.user_id, f"run_{status}", "email"):
                    db_user = await sess.get(User, run.user_id)
                    if db_user and db_user.email and not db_user.email.endswith("@deleted.invalid"):
                        notifier = get_email_notifier()
                        frontend_url = os.getenv("FRONTEND_URL", "")
                        if status == "completed":
                            await notifier.notify_run_complete(
                                db_user.email, run.project_name or run.id[:8], run.id,
                                run.cost or 0.0, frontend_url,
                            )
                        else:
                            await notifier.notify_run_failed(
                                db_user.email, run.project_name or run.id[:8], run.id, frontend_url,
                            )
        except Exception as exc:
            logger.debug("Run status email notification failed (non-fatal): %s", exc)
    try:
        asyncio.get_running_loop()  # raises RuntimeError outside an event loop (handled below)
        _t = asyncio.create_task(_create())
        _background_notify_tasks.add(_t)
        _t.add_done_callback(_background_notify_tasks.discard)
    except RuntimeError as e:
        logger.warning("db_utils: no running event loop — background notification skipped: %s", e)
async def create_run(
    run_id: str,
    command: str,
    org_id: str,
    project_name: Optional[str] = None,
    domain: str = "general",
    client_id: Optional[str] = None,
    raw_input: Optional[str] = None,
) -> None:
    """Insert a new run record, or update status/command if it already exists."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.get(Run, run_id)
        if existing:
            existing.status = "running"
            existing.command = command
            if project_name:
                existing.project_name = project_name
            if raw_input:
                existing.raw_input = raw_input
        else:
            session.add(Run(
                id=run_id,
                command=command,
                org_id=org_id,
                status="running",
                started_at=time.time(),
                project_name=project_name,
                domain=domain,
                client_id=client_id,
                raw_input=raw_input,
            ))
        await session.commit()
async def set_run_live_url(run_id: str, org_id: str, live_url: Optional[str]) -> bool:
    """Set (or clear) the live deployment URL for a run."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != org_id:
            return False
        run.live_url = live_url
        await session.commit()
    return True
# ── Phase config queries ──────────────────────────────────────────────────────
async def get_phase_configs(org_id: str) -> List[Dict[str, Any]]:
    """Return all phase config rows."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(PhaseConfig))
        rows = result.scalars().all()
    return [
        {"phase_name": r.phase_name, "enabled": bool(r.enabled), "priority": r.priority}
        for r in rows
    ]
async def upsert_phase_config(phase_name: str, enabled: bool, priority: str) -> None:
    """Upsert a phase config row."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        pc = await session.get(PhaseConfig, phase_name)
        if pc:
            pc.enabled = int(enabled)
            pc.priority = priority
            pc.updated_at = time.time()
        else:
            session.add(PhaseConfig(
                phase_name=phase_name,
                enabled=int(enabled),
                priority=priority,
                updated_at=time.time(),
            ))
        await session.commit()
async def async_update_run_live_url(run_id: str, live_url) -> None:
    """Persist or clear the live_url for a deployed run using async ORM (no raw sqlite3)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            sa_update(Run).where(Run.id == run_id).values(live_url=live_url)
        )
        await session.commit()