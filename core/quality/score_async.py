"""score_project from async code without blocking the event loop.

score_project runs `vite build` (up to 120 s) and bandit (30 s) as subprocesses. Calling it
directly inside an async route froze every request on that worker. This runs it in a worker thread,
caps how many scorings run at once (a burst of users must not start a burst of vite builds), bounds
the wait, and caches a result briefly per project directory for read-only callers.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path

from aether_os.core.quality.metrics import QualityScore, score_project

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 2
TIMEOUT_S = 150.0
CACHE_TTL_S = 120.0
CACHE_MAX = 256

_sem: asyncio.Semaphore | None = None
_sem_loop: asyncio.AbstractEventLoop | None = None
_cache: dict[str, tuple[float, QualityScore]] = {}
_cache_lock = threading.Lock()


def _semaphore() -> asyncio.Semaphore:
    global _sem, _sem_loop
    loop = asyncio.get_running_loop()
    if _sem is None or _sem_loop is not loop:
        _sem, _sem_loop = asyncio.Semaphore(MAX_CONCURRENT), loop
    return _sem


async def score_project_async(project_dir: Path, *, use_cache: bool = True) -> QualityScore:
    """Score in a thread. use_cache=False for callers that change the project between calls
    (the healing loop). Raises asyncio.TimeoutError when scoring exceeds TIMEOUT_S."""
    key = str(Path(project_dir).resolve())
    if use_cache:
        with _cache_lock:
            hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
    async with _semaphore():
        score = await asyncio.wait_for(asyncio.to_thread(score_project, Path(project_dir)), TIMEOUT_S)
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
        _cache[key] = (time.monotonic(), score)
    return score
