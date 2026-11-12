"""Start a build in the background (shared by /rerun, /branch and clarifying-answers restarts)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aether_os.orchestrator.factory_pipeline import get_factory

logger = logging.getLogger(__name__)

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
