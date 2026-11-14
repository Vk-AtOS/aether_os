"""Slow scoring/scanning runs in a thread: the event loop keeps serving while it works (KAN-136)."""
import asyncio
import time

import aether_os.core.quality.score_async as sa
import aether_os.core.security.code_scanner as cs


async def _ticks_during(coro, interval=0.02):
    ticks = 0
    done = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not done.is_set():
            await asyncio.sleep(interval)
            ticks += 1

    t = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        done.set()
        await t
    return result, ticks


def test_score_project_async_does_not_block_the_loop_and_caches(monkeypatch, tmp_path):
    calls = []

    def slow(p):
        calls.append(p)
        time.sleep(0.3)
        return "SCORE"

    monkeypatch.setattr(sa, "score_project", slow)
    sa._cache.clear()

    async def go():
        r, ticks = await _ticks_during(sa.score_project_async(tmp_path))
        assert r == "SCORE" and ticks >= 5  # a blocked loop would tick ~0 times
        assert await sa.score_project_async(tmp_path) == "SCORE"
        assert len(calls) == 1  # second call served from cache
        await sa.score_project_async(tmp_path, use_cache=False)
        assert len(calls) == 2

    asyncio.run(go())


def test_score_project_async_times_out(monkeypatch, tmp_path):
    monkeypatch.setattr(sa, "score_project", lambda p: time.sleep(0.5))
    monkeypatch.setattr(sa, "TIMEOUT_S", 0.05)
    sa._cache.clear()

    async def go():
        try:
            await sa.score_project_async(tmp_path)
        except asyncio.TimeoutError:
            return True

    assert asyncio.run(go())


def test_scan_project_runs_pip_audit_off_the_loop(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n")
    monkeypatch.setattr(cs, "_run_pip_audit", lambda d: time.sleep(0.3) or [])

    async def go():
        _, ticks = await _ticks_during(cs.CodeScanner().scan_project(str(tmp_path), "saas"))
        return ticks

    assert asyncio.run(go()) >= 5


def test_pip_audit_result_is_cached(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.0\n")
    n = []
    monkeypatch.setattr(cs, "_run_pip_audit_uncached", lambda f: n.append(1) or [])
    cs._AUDIT_CACHE.clear()
    cs._run_pip_audit(str(tmp_path))
    cs._run_pip_audit(str(tmp_path))
    assert len(n) == 1
