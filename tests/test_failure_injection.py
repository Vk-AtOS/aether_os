"""KAN-49 acceptance: injected failures stay contained.

Velaris down or slow -> fails fast after a few calls, and the rest of the API keeps answering.
"""
import asyncio
import time

import httpx
import pytest

from aether_os.core.resilience import bulkhead, get_breaker, reset_all
from aether_os.core.velaris.client import Identity, VelarisClient, VelarisUnavailable

pytestmark = pytest.mark.asyncio


def _client(handler):
    import cryptography.hazmat.primitives.asymmetric.ed25519 as ed
    return VelarisClient("http://velaris.test", b"s" * 32, ed.Ed25519PrivateKey.generate(),
                         transport=httpx.MockTransport(handler))


WHO = Identity("u", "o", "admin")


async def test_velaris_down_fails_fast_after_five_calls_and_4xx_never_counts():
    reset_all()
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("refused")
    c = _client(handler)
    for _ in range(5):
        with pytest.raises(VelarisUnavailable):
            await c.request(WHO, "GET", "/agents")
    with pytest.raises(VelarisUnavailable, match="circuit open"):
        await c.request(WHO, "GET", "/agents")
    assert len(calls) == 5                                # the sixth call never left the process
    assert get_breaker("velaris").state == "open"
    reset_all()

    ok = _client(lambda r: httpx.Response(404, json={"detail": "nope"}))
    for _ in range(10):
        assert (await ok.request(WHO, "GET", "/x"))[0] == 404
    assert get_breaker("velaris").state == "closed"
    reset_all()


async def test_slow_velaris_cannot_hold_more_than_the_bulkhead_and_other_work_still_runs(monkeypatch):
    reset_all()
    monkeypatch.setenv("VELARIS_MAX_INFLIGHT", "2")
    release = asyncio.Event()

    async def slow(request):
        await release.wait()
        return httpx.Response(200, json={"ok": True})
    c = _client(slow)
    held = [asyncio.create_task(c.request(WHO, "GET", "/slow")) for _ in range(2)]
    await asyncio.sleep(0.05)
    bulkhead._registry["velaris"].max_wait_s = 0.05
    t0 = time.monotonic()
    with pytest.raises(VelarisUnavailable, match="busy"):
        await c.request(WHO, "GET", "/slow")
    assert time.monotonic() - t0 < 1                      # rejected quickly, not after the 30 s client timeout
    assert await asyncio.sleep(0, "other work runs") == "other work runs"
    release.set()
    await asyncio.gather(*held)
    reset_all()
