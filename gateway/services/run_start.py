"""Start a build in the background (shared by /rerun, /branch and clarifying-answers restarts)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable, Optional

from sqlalchemy import update

from aether_os.core.db import get_session_factory
from aether_os.core.models import Run
from aether_os.orchestrator.factory_pipeline import get_factory

logger = logging.getLogger(__name__)

BUSY_STATUSES = ("running", "queued", "paused", "pending")
RESTARTABLE_STATUSES = ("failed", "cancelled", "error")

# Strong references so in-flight builds are not garbage-collected.
_background_tasks: set = set()


def start_in_background(**kwargs: Any) -> None:
    async def _bg() -> None:
        try:
            await get_factory().run(**kwargs)
        except Exception as exc:
            logger.error("Run %s (from %s) failed: %s", kwargs["run_id"], kwargs.get("start_phase"), exc)

    task = asyncio.create_task(_bg())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def claim_run(run_id: str, org_id: str, *, values: dict, not_in: Iterable[str] = (),
                    only_in: Optional[Iterable[str]] = None) -> bool:
    """Atomically move an existing run to a new state, in ONE conditional UPDATE, so two
    concurrent restarts cannot both pass a separate check and both start a build. True only
    for the caller whose UPDATE matched (rowcount 1); only that caller may start the build.
    `not_in`: refuse while the status is one of these; `only_in`: require one of these."""
    cond = [Run.id == run_id, Run.org_id == org_id]
    if not_in:
        cond.append(Run.status.notin_(tuple(not_in)))
    if only_in is not None:
        cond.append(Run.status.in_(tuple(only_in)))
    async with get_session_factory()() as session:
        won = (await session.execute(update(Run).where(*cond).values(**values))).rowcount
        await session.commit()
    return bool(won)
