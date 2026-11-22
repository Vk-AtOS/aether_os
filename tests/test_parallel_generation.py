"""KAN-214: waves run independent stages concurrently within a width, and entity pages
are written concurrently within PIPELINE_PAGE_CONCURRENCY, backing off on 429."""
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aether_os.orchestrator.parallel_runner import run_phases_in_wave, wave_width
from aether_os.phases.p05_frontend import domain_assembler, page_concurrency
from aether_os.phases.p05_frontend.page_concurrency import (
    call_with_backoff, page_concurrency as page_limit,
)

class _Input:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def _wave(tmp_path, phases, fn):
    return await run_phases_in_wave(
        wave=phases, run_phase_fn=fn, accumulated_context={}, run_id="r", org_id=None,
        project_dir=tmp_path, domain="general", client_id="c", emit_fn=AsyncMock(),
        update_state_fn=AsyncMock(), phase_input_cls=_Input, critical_phases=frozenset())


def _sleeper(delay, seen=None, fail=()):
    state = {"now": 0, "peak": 0}

    async def run(name, _input):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        try:
            await asyncio.sleep(delay[name])
            if name in fail:
                raise RuntimeError("boom")
            return {"status": "completed", "artifacts": {}, "output_path": ""}
        finally:
            state["now"] -= 1
    return run, state


@pytest.mark.asyncio
async def test_wave_wall_time_is_the_longest_phase_not_the_sum(tmp_path, monkeypatch):
    monkeypatch.delenv("PIPELINE_WAVE_WIDTH", raising=False)
    run, _ = _sleeper({"s03_backend": 0.4, "s04_frontend": 0.6})
    t = time.monotonic()
    res = await _wave(tmp_path, ["s03_backend", "s04_frontend"], run)
    elapsed = time.monotonic() - t
    assert elapsed < 0.95 and all(r["status"] == "completed" for r in res.values())


@pytest.mark.asyncio
async def test_wave_width_limits_phases_running_at_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_WAVE_WIDTH", "2")
    names = ["a", "b", "c", "d"]
    run, state = _sleeper({n: 0.1 for n in names})
    t = time.monotonic()
    await _wave(tmp_path, names, run)
    assert state["peak"] == 2 and time.monotonic() - t >= 0.19


@pytest.mark.asyncio
async def test_one_failing_phase_does_not_cancel_the_other(tmp_path, monkeypatch):
    monkeypatch.delenv("PIPELINE_WAVE_WIDTH", raising=False)
    run, _ = _sleeper({"a": 0.05, "b": 0.2}, fail=("a",))
    res = await _wave(tmp_path, ["a", "b"], run)
    assert res["a"]["status"] == "failed" and res["b"]["status"] == "completed"


def test_wave_width_parsing(monkeypatch):
    monkeypatch.delenv("PIPELINE_WAVE_WIDTH", raising=False)
    assert wave_width() == 0
    monkeypatch.setenv("PIPELINE_WAVE_WIDTH", "x")
    assert wave_width() == 0
    monkeypatch.setenv("PIPELINE_WAVE_WIDTH", "3")
    assert wave_width() == 3


def test_page_concurrency_default_and_override(monkeypatch):
    monkeypatch.delenv("PIPELINE_PAGE_CONCURRENCY", raising=False)
    assert page_limit() == 3
    monkeypatch.setenv("PIPELINE_PAGE_CONCURRENCY", "0")
    assert page_limit() == 1
    monkeypatch.setenv("PIPELINE_PAGE_CONCURRENCY", "nope")
    assert page_limit() == 3


async def _assemble(tmp_path, n_entities):
    src = tmp_path / "src"
    (src / "pages").mkdir(parents=True)
    ents = [{"table": f"t{i}", "name": f"E{i}", "columns": ["id"]} for i in range(n_entities)]
    return await domain_assembler.assemble_domain_pages(
        src_dir=src, domain="general", domain_ir=None, entities=ents, build_types=[],
        layout_mode="admin", route_map={}, project_name="P", data={}, output_dir=tmp_path,
        phase_start=asyncio.get_event_loop().time(), phase_timeout=1e9,
        write_with_guard_fn=lambda path, code: Path(path).write_text(code),
        generate_product_grid_fn=lambda *a, **k: "grid",
        generate_entity_page_fn=lambda *a, **k: "template",
        generate_domain_dashboard_fn=lambda *a, **k: "dash",
        is_product_entity_fn=lambda t: False, to_pascal_case_fn=lambda t: t,
        pluralise_fn=lambda t: t, run_frontend_governor_fn=lambda *a, **k: None,
        write_domain_pages_fn=lambda *a, **k: None,
    )


@pytest.mark.parametrize("limit,expected_peak", [("3", 3), ("1", 1)])
@pytest.mark.asyncio
async def test_entity_pages_never_exceed_the_limit(tmp_path, monkeypatch, limit, expected_peak):
    monkeypatch.setenv("PIPELINE_PAGE_CONCURRENCY", limit)
    state = {"now": 0, "peak": 0}

    async def fake_page(**_kw):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.05)
        state["now"] -= 1
        return "export default function X() { return null }"

    async def no_dash(**_kw):
        return None

    monkeypatch.setattr(domain_assembler, "write_entity_page_llm", fake_page)
    monkeypatch.setattr(domain_assembler, "write_dashboard_llm", no_dash)
    stats = await _assemble(tmp_path, 7)
    assert state["peak"] == expected_peak and stats["llm_count"] == 7


@pytest.mark.asyncio
async def test_429_is_retried_with_backoff_then_succeeds(monkeypatch):
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(page_concurrency.asyncio, "sleep", fake_sleep)
    calls = {"n": 0}

    async def call():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return "ok"

    assert await call_with_backoff(call, "page") == "ok"
    assert sleeps == [5.0, 10.0]


@pytest.mark.asyncio
async def test_non_rate_limit_error_is_not_retried_and_429_gives_up(monkeypatch):
    monkeypatch.setattr(page_concurrency.asyncio, "sleep", AsyncMock())
    calls = {"n": 0}

    async def broken():
        calls["n"] += 1
        raise ValueError("bad prompt")

    with pytest.raises(ValueError):
        await call_with_backoff(broken, "page")
    assert calls["n"] == 1

    async def limited():
        calls["n"] += 1
        raise RuntimeError("rate limit exceeded")

    calls["n"] = 0
    with pytest.raises(RuntimeError):
        await call_with_backoff(limited, "page")
    assert calls["n"] == page_concurrency.RATE_LIMIT_RETRIES + 1
