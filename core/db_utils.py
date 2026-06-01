"""
AetherOS — Async DB Utilities

Replaces all raw sqlite3.connect() calls that were blocking the FastAPI event loop.
These functions use SQLAlchemy async ORM exclusively.

All functions are safe to await from async FastAPI route handlers.
"""
from __future__ import annotations
import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text, update, delete, func

# Strong reference set so background notification tasks are not garbage collected
_background_notify_tasks: set = set()


# ── Run queries ───────────────────────────────────────────────────────────────

async def get_run_list(
    org_id: str,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Return paginated run history for an org with total count.

    Returns {"items": [...], "total": int} so callers don't overfetch.
    """
    from .db import get_session_factory
    from .models import Run, PhaseCompletion, RunMetadata

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Total count (separate query, cheap with index on org_id)
        count_stmt = select(func.count()).select_from(Run).where(Run.org_id == org_id)
        total: int = (await session.execute(count_stmt)).scalar_one()

        if total == 0:
            return {"items": [], "total": 0}

        # Paginated runs
        stmt = (
            select(Run)
            .where(Run.org_id == org_id)
            .order_by(Run.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        runs = result.scalars().all()

        if not runs:
            return {"items": [], "total": total}

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
            "phases":        run.phases or {},
            "priority":      prio_map.get(run.id, "normal"),
            "domain":        run.domain,
            "client_id":     run.client_id,
        }
        formatted.append(d)
    return {"items": formatted, "total": total}


async def get_run_detail(run_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
    """Return full run detail with phase_completions and events."""
    from .db import get_session_factory
    from .models import Run, PhaseCompletion, RunMetadata
    from sqlalchemy.orm import selectinload

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
    }


async def set_run_priority(run_id: str, org_id: str, priority: str) -> bool:
    """Upsert priority for a run. Returns False if run not found or org mismatch."""
    from .db import get_session_factory
    from .models import Run, RunMetadata

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
    from .db import get_session_factory
    from .models import PhaseCompletion

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
) -> bool:
    """Update run status (and optionally current_phase). Returns False if not found."""
    from .db import get_session_factory
    from .models import Run

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
        if status in ("completed", "failed", "cancelled", "gated"):
            run.finished_at = time.time()
        await session.commit()
        if status in ("completed", "failed") and run.org_id:
            _emit_run_notification(run, status)
    return True


def _emit_run_notification(run, status: str) -> None:
    """Fire-and-forget task to create an in-app notification and send email on run completion/failure."""
    import asyncio
    async def _create():
        try:
            from .db import get_session_factory as _gsf
            from .models import Notification, User
            import time as _t
            from sqlalchemy import select as _sel
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
                if run.user_id:
                    db_user = await sess.get(User, run.user_id)
                    if db_user and db_user.email and not db_user.email.endswith("@deleted.invalid"):
                        from .notifications.email import get_email_notifier
                        import os
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
        except Exception:
            pass
    try:
        loop = asyncio.get_running_loop()
        _t = asyncio.create_task(_create())
        _background_notify_tasks.add(_t)
        _t.add_done_callback(_background_notify_tasks.discard)
    except RuntimeError:
        pass  # no running event loop — skip background notification


async def create_run(
    run_id: str,
    command: str,
    org_id: str,
    project_name: Optional[str] = None,
    domain: str = "general",
    client_id: Optional[str] = None,
    raw_input: Optional[str] = None,
) -> None:
    """Insert a new run record."""
    from .db import get_session_factory
    from .models import Run

    session_factory = get_session_factory()
    async with session_factory() as session:
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
    from .db import get_session_factory
    from .models import Run

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
    from .db import get_session_factory
    from .models import PhaseConfig

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
    from .db import get_session_factory
    from .models import PhaseConfig

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
    from .db import get_session_factory
    from .models import Run
    from sqlalchemy import update as sa_update

    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            sa_update(Run).where(Run.id == run_id).values(live_url=live_url)
        )
        await session.commit()
