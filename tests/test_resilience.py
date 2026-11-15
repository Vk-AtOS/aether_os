"""KAN-49: breaker and bulkhead behaviour, and the failure-injection acceptance cases for the building blocks."""
import asyncio

import pytest

from aether_os.core.resilience import Bulkhead, BulkheadFull, CircuitBreaker, CircuitOpen


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def boom():
    raise ConnectionError("down")


async def fine():
    return "ok"


@pytest.mark.asyncio
async def test_breaker_opens_after_threshold_and_fails_fast():
    clock = Clock()
    b = CircuitBreaker("x", failure_threshold=3, reset_after_s=30, clock=clock)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await b.call(boom)
    assert b.state == "open"
    called = []

    async def spy():
        called.append(1)

    with pytest.raises(CircuitOpen):
        await b.call(spy)
    assert called == []                      # the dependency is not touched while open


@pytest.mark.asyncio
async def test_breaker_half_open_allows_one_probe_then_closes_or_reopens():
    clock = Clock()
    b = CircuitBreaker("x", failure_threshold=1, reset_after_s=10, clock=clock)
    with pytest.raises(ConnectionError):
        await b.call(boom)
    clock.t = 11
    assert b.state == "half_open"
    b.before_call()                          # the probe
    with pytest.raises(CircuitOpen):
        b.before_call()                      # a second caller is refused while the probe runs
    b.record_failure("still down")
    assert b.state == "open"
    clock.t = 30
    assert await b.call(fine) == "ok" and b.state == "closed"


@pytest.mark.asyncio
async def test_errors_that_are_not_failures_do_not_open_the_breaker():
    b = CircuitBreaker("x", failure_threshold=2)

    async def not_found():
        raise KeyError("404")

    for _ in range(5):
        with pytest.raises(KeyError):
            await b.call(not_found, is_failure=lambda e: not isinstance(e, KeyError))
    assert b.state == "closed"


@pytest.mark.asyncio
async def test_bulkhead_rejects_when_full_and_other_bulkheads_are_unaffected():
    slow, other = Bulkhead("slow", 2, max_wait_s=0.05), Bulkhead("other", 2, max_wait_s=0.05)
    release = asyncio.Event()

    async def hold():
        async with slow:
            await release.wait()

    tasks = [asyncio.create_task(hold()) for _ in range(2)]
    await asyncio.sleep(0.01)
    with pytest.raises(BulkheadFull):
        async with slow:
            pass
    async with other:                        # a different class of work still has its own slots
        pass
    assert slow.snapshot()["rejected_total"] == 1
    release.set()
    await asyncio.gather(*tasks)
    assert slow.in_use == 0
