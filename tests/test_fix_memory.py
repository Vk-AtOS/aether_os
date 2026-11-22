"""KAN-215: structured run memory: signature normalisation, org isolation, expiry, bounded summaries, build-loop reuse."""
from __future__ import annotations

import asyncio
import subprocess

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aether_os.core import fix_memory as fm
from aether_os.core.db import Base
from aether_os.core.models import GlobalPattern
from aether_os.core.models_memory import FixMemory, RunPatternMemory
from aether_os.phases.p05_frontend import build_loop

PATCH = {"file": "src/pages/TaskPage.tsx", "find": "const n: number = 'x'", "replace": "const n: number = 1"}


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/m.db")

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[
                FixMemory.__table__, RunPatternMemory.__table__, GlobalPattern.__table__])
    asyncio.run(init())
    return async_sessionmaker(engine, expire_on_commit=False)


def run(coro):
    return asyncio.run(coro)


def test_equivalent_tsc_errors_share_one_signature():
    a = "src/pages/A.tsx(10,5): error TS2304: Cannot find name 'Button'."
    b = "src/pages/B.tsx(254,306): error TS2304: Cannot find name 'Card'."
    ea, eb = fm.parse_errors(a)[0], fm.parse_errors(b)[0]
    assert ea["signature"] == eb["signature"]
    assert ea["file_kind"] == eb["file_kind"] == "tsx:pages"
    other = fm.parse_errors("src/pages/A.tsx(10,5): error TS2322: Type 'x' is not assignable to type 'y'.")[0]
    assert other["signature"] != ea["signature"]


def test_vite_error_with_absolute_path_is_parsed():
    out = "/tmp/w/src/pages/X.tsx:291:42: ERROR: Unexpected \"}\""
    err = fm.parse_errors(out)[0]
    assert err["file"] == "src/pages/X.tsx"


def test_lookup_is_org_scoped_and_stored_fix_survives_roundtrip(factory):
    async def body():
        async with factory() as s:
            await fm.record("org-a", "sig1", "tsx:pages", [PATCH], session=s)
            assert await fm.lookup("org-a", "sig1", session=s) == [PATCH]
            assert await fm.lookup("org-b", "sig1", session=s) == []
            assert await fm.lookup("", "sig1", session=s) == []
            assert await fm.mark_failure("org-b", "sig1", session=s) is False   # other org cannot touch it
            assert await fm.lookup("org-a", "sig1", session=s) == [PATCH]
    run(body())


def test_apply_stored_uses_validate_callback_and_fix_failing_twice_is_dropped(factory):
    async def body():
        async with factory() as s:
            await fm.record("o", "sig", "tsx:pages", [PATCH], session=s)
            assert await fm.apply_stored("o", "sig", lambda p: False, session=s) == []
            assert await fm.apply_stored("o", "sig", lambda p: True, session=s) == [PATCH]
            assert await fm.mark_failure("o", "sig", session=s) is False
            assert await fm.mark_failure("o", "sig", session=s) is True
            assert await fm.lookup("o", "sig", session=s) == []
    run(body())


def test_prompt_summary_is_bounded_org_scoped_and_has_no_other_org_content(factory):
    async def body():
        async with factory() as s:
            for i in range(20):
                await fm.record_run("o", f"r{i}", "saas", [f"Entity{i}"] + [f"ent{j}x" for j in range(12)], ["crud"], session=s)
            await fm.record_run("other", "x", "saas", ["SecretEntity"], ["secret"], session=s)
            s.add(GlobalPattern(org_id=None, domain="saas", pattern_name="crud", pattern_type="arch", success_rate=0.9))
            s.add(GlobalPattern(org_id="other", domain="saas", pattern_name="OtherOrgOnly", pattern_type="arch"))
            await s.commit()
            text = await fm.prompt_summary("o", "saas", ["Entity3"], max_tokens=60, session=s)
            assert 0 < len(text) <= 60 * 4 + 40
            assert "SecretEntity" not in text and "OtherOrgOnly" not in text
            full = await fm.prompt_summary("o", "saas", ["Entity3"], session=s)
            assert "Entity3" in full and "platform pattern: crud" in full
            assert len(full) <= fm.SUMMARY_MAX_TOKENS * 4 + 40
            assert await fm.prompt_summary("nobody", "healthcare", session=s) == ""
    run(body())


ERR = "src/pages/TaskPage.tsx(1,7): error TS2322: Type 'string' is not assignable to type 'number'.\n"


def _loop(monkeypatch, tmp_path, factory, org, llm_calls):
    """The build fails while the file holds a string typed as number; the patch fixes the build."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(fm, "get_session_factory", lambda: factory)
    page = tmp_path / "src/pages/TaskPage.tsx"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("const n: number = 'x'\n")

    async def fake_exec(argv, **kw):
        broken = "'x'" in page.read_text()
        if argv[1] == "tsc":
            return subprocess.CompletedProcess([], 2 if broken else 0, stdout=ERR if broken else "", stderr="")
        if not broken:
            (tmp_path / "dist").mkdir(exist_ok=True)
            (tmp_path / "dist/index.html").write_text("<html/>")
        return subprocess.CompletedProcess([], 1 if broken else 0, stdout="", stderr="")

    async def fake_fix(*_):
        llm_calls.append(1)
        return [PATCH]

    monkeypatch.setattr(build_loop.phase_exec, "run", fake_exec)
    monkeypatch.setattr(build_loop, "_llm_fix", fake_fix)
    return run(build_loop.run_build_loop(tmp_path, max_rounds=3, org_id=org)), page


def test_build_loop_records_model_fix_then_reuses_it_without_a_model_call(monkeypatch, tmp_path, factory):
    calls: list = []
    out, _ = _loop(monkeypatch, tmp_path / "one", factory, "org-1", calls)
    print("PAGE", (tmp_path / "one/src/pages/TaskPage.tsx").read_text(), out)
    assert out["success"] and len(calls) == 1           # first run: the model fixed it, memory recorded it
    sig = fm.parse_errors(ERR)[0]["signature"]
    assert run(fm.lookup("org-1", sig)) == [PATCH]

    out, page = _loop(monkeypatch, tmp_path / "two", factory, "org-1", calls)
    assert out["success"] and len(calls) == 1           # second run: memory hit, no model call
    assert "= 1" in page.read_text()

    out, _ = _loop(monkeypatch, tmp_path / "three", factory, "org-2", calls)
    assert out["success"] and len(calls) == 2           # another org does not see org-1's memory
