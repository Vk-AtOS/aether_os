"""Bulkhead: a bounded number of concurrent calls for one class of work, with a bounded wait.

A stuck dependency (say Velaris) can then hold at most `limit` slots; callers beyond that fail fast with BulkheadFull
instead of queueing without bound, so unrelated request handlers keep their own capacity.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Dict, Optional


class BulkheadFull(Exception):
    """No slot became free within the wait: the call was not attempted."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is saturated")
        self.name = name


class Bulkhead:
    def __init__(self, name: str, limit: int, max_wait_s: float = 2.0) -> None:
        self.name, self.limit, self.max_wait_s = name, limit, max_wait_s
        self.in_use = 0
        self.rejected_total = 0
        self._sem: Optional[asyncio.Semaphore] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._loop is not loop:  # a semaphore belongs to one loop (tests, reloads)
            self._sem, self._loop, self.in_use = asyncio.Semaphore(self.limit), loop, 0
        return self._sem

    async def __aenter__(self) -> "Bulkhead":
        sem = self._semaphore()
        try:
            await asyncio.wait_for(sem.acquire(), self.max_wait_s)
        except asyncio.TimeoutError:
            self.rejected_total += 1
            raise BulkheadFull(self.name) from None
        self.in_use += 1
        return self

    async def __aexit__(self, *exc) -> None:
        self.in_use -= 1
        self._semaphore().release()

    def snapshot(self) -> Dict[str, object]:
        return {"name": self.name, "limit": self.limit, "in_use": self.in_use, "rejected_total": self.rejected_total}


_registry: Dict[str, Bulkhead] = {}
_registry_lock = threading.Lock()


def get_bulkhead(name: str, limit: int = 32, max_wait_s: float = 2.0) -> Bulkhead:
    with _registry_lock:
        if name not in _registry:
            _registry[name] = Bulkhead(name, limit, max_wait_s)
        return _registry[name]


def all_bulkheads() -> Dict[str, Bulkhead]:
    with _registry_lock:
        return dict(_registry)
