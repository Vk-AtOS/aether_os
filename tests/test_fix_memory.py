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

PATCH = {"file": "src/pages/TaskPage.tsx", "find": "<div><p>hi</p>", "replace": "<div><p>hi</p></div>"}


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


ERR = "src/pages/TaskPage.tsx(1,1): error TS17008: JSX element 'div' has no corresponding closing tag.\n"


def _loop(monkeypatch, tmp_path, factory, org, llm_calls):
    """The build fails while the file has an unclosed <div>; appending the closing tag fixes the build."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(fm, "get_session_factory", lambda: factory)
    page = tmp_path / "src/pages/TaskPage.tsx"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("<div><p>hi</p>\n")

    async def fake_exec(argv, **kw):
        broken = "</div>" not in page.read_text()
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
    assert "</div>" in page.read_text()

    out, _ = _loop(monkeypatch, tmp_path / "three", factory, "org-2", calls)
    assert out["success"] and len(calls) == 2           # another org does not see org-1's memory


# --- memory poisoning guard ---------------------------------------------------------------------------------------

SRC = "\n".join(["// filler"] * 30 + ["<div><p>hi</p>"] + ["// tail"] * 30)   # error line is 31
ERR31 = {"file": "src/pages/TaskPage.tsx", "line": 31, "signature": "s", "file_kind": "tsx:pages"}


def _p(**kw):
    return {**PATCH, **kw}


def test_only_small_local_same_file_safe_patches_are_storable():
    assert fm.patch_targets_error(_p(), ERR31, SRC)
    assert not fm.patch_targets_error(_p(find="x" * 401), ERR31, SRC)                    # oversized find
    assert not fm.patch_targets_error(_p(replace="y" * 401), ERR31, SRC)                 # oversized replace
    assert not fm.patch_targets_error(_p(file="src/pages/Other.tsx"), ERR31, SRC)        # other file
    assert not fm.patch_targets_error(_p(), {**ERR31, "line": 60}, SRC)                  # error far from the find span
    assert not fm.patch_targets_error(_p(), ERR31, "const n = x\n")                      # find no longer in the source
    assert not fm.patch_targets_error(_p(find="not in the file"), ERR31, SRC)


def test_relative_import_is_fine_without_adding_the_import_keyword():
    assert fm.is_safe_patch(_p(find="import Card from './card'", replace="import Card from './Card'"))


def test_replay_targets_the_current_errors_file_not_the_stored_path(factory):
    seen = []
    async def body():
        async with factory() as s:
            await fm.record("o", "sig", "tsx:pages", [_p(file="src/pages/Elsewhere.tsx")], session=s)
            return await fm.apply_stored("o", "sig", lambda p: seen.append(p["file"]) or True,
                                         target_file="src/pages/Current.tsx", session=s)
    assert run(body())[0]["file"] == "src/pages/Current.tsx" and seen == ["src/pages/Current.tsx"]


def test_hook_screen_rejects_patch_for_another_file(tmp_path):
    from aether_os.phases.p05_frontend.fix_memory_hook import RoundMemory
    (tmp_path / "src/pages").mkdir(parents=True)
    (tmp_path / "src/pages/TaskPage.tsx").write_text("<div><p>hi</p>\n")
    mem = RoundMemory("org", tmp_path, lambda d, p: True)
    mem.screen_model_patches(ERR, [_p(file="src/pages/Other.tsx"), _p(replace="fetch('http://x')")])
    assert mem._candidates == []
    mem.screen_model_patches(ERR, [_p()])
    assert len(mem._candidates) == 1


def test_provenance_is_recorded_and_rows_can_be_purged_by_run(factory):
    async def body():
        async with factory() as s:
            await fm.record("o", "a", "tsx:pages", [_p()], run_id="run-1", user_id="u-9", session=s)
            await fm.record("o", "b", "tsx:pages", [_p()], run_id="run-2", session=s)
            await fm.mark_hit("o", "a", session=s)
            row = (await s.execute(FixMemory.__table__.select().where(FixMemory.signature == "a"))).one()
            assert (row.run_id, row.user_id, row.hits) == ("run-1", "u-9", 1) and row.created_at
            other = (await s.execute(FixMemory.__table__.select().where(FixMemory.signature == "b"))).one()
            assert other.user_id == "system"
            assert await fm.purge_run("other-org", "run-1", session=s) == 0
            assert await fm.purge_run("o", "run-1", session=s) == 1
            assert await fm.lookup("o", "a", session=s) == [] and await fm.lookup("o", "b", session=s)
    run(body())


# --- edit-shape allowlist: every bypass from the four review rounds must be refused ----------------------------------

def _safe(find, replace):
    return fm.is_safe_patch({"file": "src/a.tsx", "find": find, "replace": replace})


@pytest.mark.parametrize("bad", [
    "import x from 'left-pad'", "import 'evil'", "import('evil')",                    # round 1
    "fetch('https://evil.example/x')", "eval(code)", "new Function('return 1')",
    "<div dangerouslySetInnerHTML={{__html: h}} />", "<script>1</script>", "require('child_process')",
    "import {\n  a,\n  b\n} from 'left-pad'",                                         # round 2: multi-line import
    "export * from 'left-pad'", "export { a } from \"evil\"",                         # export ... from a package
    "const u = '//evil.example/x.js'", "fetch(`//evil.example`)",                       # protocol-relative URL
    "el.innerHTML = h", "el.outerHTML = h", "el.insertAdjacentHTML('a', h)",
    "setTimeout('alert(1)', 0)", "setInterval(\"x()\", 5)",                            # string timer
    "window['ev'+'al'](c)", "globalThis['x']", "document['cookie']", "self['fetch']",
    "document.write(x)",
    "const n = 1 /* a */ ; ev/**/al(c)", "<div><p>hi</p> // a comment",                 # round 3: comments split tokens
    "a.constructor", "Reflect.get(a, b)", "a?.[k]", "const p = a + '/' + '/'",         # ?.[ and concatenated '//'
    "const n = 1; x.__proto__ = y", "const n = `t`", "localStorage.x", "n = atob(s)",
    "const \\u0065val = 1", "ev\\u0061l(c)", "n = \"\\x41\"", "n = 1 + \\ 2",       # escapes
    "foo(1)", "n = a[1]",
    "import x from 'javascript:alert(1)'", "import x from '//evil.example/a'", "import x from 'data:text/js,1'",
    "import x from './a:b'", "import x from './a//b'",
    "const n = 1e3constructor", "const n = 0xconstructor", "const n = 1constructor",   # round 4: number grammar
    "import('x'); a from './a'", "const n = import('x') from './a'",                    # import() balanced by from
])
def test_every_known_bypass_is_refused(bad):
    assert not fm.is_safe_patch(_p(replace=bad))


def test_added_call_balanced_by_a_removed_one_is_refused():
    assert not _safe("const a = f(b) + g(c)", "const a = f(b) + h")
    assert not _safe("x(1); y", "x; y(1)")
    assert not _safe("f(a)", "f(a)(b)")


def test_shape_a_case_only_import_path_fix():
    assert _safe("import Card from './components/ui/card'", "import Card from './components/ui/Card'")
    assert _safe("export { A } from './a/b'", "export { A } from './a/B'")
    assert not _safe("import { A } from '../x'", "import { A } from '../y'")                # not case-only
    assert not _safe("import Card from './card'", "import Card from './cards'")             # different length
    assert not _safe("import Card from './card'", "import Card from 'left-pad'")
    assert not _safe("import Card from './card'", "import Card from \"./Card\"")            # quote change
    assert not _safe("import Card from 'react'", "import Card from 'React'")                 # package, not relative
    assert not _safe("import Card from './card'", "import Cart from './Card'")               # two changes
    assert not _safe("const a = './card'", "const a = './Card'")                              # not an import statement
    assert not _safe("import a from './a'", "import a from './a:b'")


def _project(tmp_path):
    (tmp_path / "src/pages").mkdir(parents=True)
    (tmp_path / "src/components/ui").mkdir(parents=True)
    (tmp_path / "src/components/ui/Card.tsx").write_text("export default 1\n")
    (tmp_path / "src/pages/Page.tsx").write_text("import Card from '../components/ui/card'\n")
    (tmp_path / "outside.ts").write_text("x")
    return tmp_path


def _fix(spec):
    return {"file": "src/pages/Page.tsx", "find": "import Card from '../components/ui/card'",
            "replace": f"import Card from '{spec}'"}


def test_shape_a_replay_resolves_the_specifier_inside_src_with_exact_case(tmp_path):
    root = _project(tmp_path)
    assert fm.import_target_ok(root, "src/pages/Page.tsx", _fix("../components/ui/Card"))     # exists, exact case
    assert not fm.import_target_ok(root, "src/pages/Page.tsx", _fix("../components/ui/CARD"))  # wrong case on disk
    assert not fm.import_target_ok(root, "src/pages/Page.tsx", _fix("../components/ui/Missing"))
    assert not fm.import_target_ok(root, "src/pages/Page.tsx", _fix("../../../outside"))      # ../../ traversal
    assert not fm.import_target_ok(root, "src/pages/Page.tsx", _fix("../../outside"))         # leaves src/
    err = {"file": "src/pages/Page.tsx", "line": 1}
    src = (root / "src/pages/Page.tsx").read_text()
    assert fm.patch_targets_error(_fix("../components/ui/Card"), err, src, root)
    assert not fm.patch_targets_error(_fix("../components/ui/CARD"), err, src, root)


def test_shape_b_identifier_rename_is_refused():
    assert not _safe("const totl = items.length", "const total = items.length")
    assert not _safe("const a = b", "const a = new")                      # keyword
    assert not _safe("const a = typeof b", "const a = void b")          # keyword swap
    assert not _safe("x.foo", "x.bar")                                   # member access
    assert not _safe("<Btn disabled />", "<Btn onClick />")              # JSX attribute
    assert not _safe("const a = b", "const a = fetch")


def test_shape_c_missing_closing_tag():
    assert _safe("<div>\n  <p>hi</p>", "<div>\n  <p>hi</p>\n</div>")
    assert _safe("<Card><b>x", "<Card><b>x</b></Card>")
    assert not _safe("<div>", "<div></span>")                                            # tag never opened
    assert not _safe("<div>", "<div></div><script>")
    assert not _safe("<div>", "<div></div>alert(1)")
    assert not _safe("<script>", "<script></script>")                                    # denied identifier
    assert not _safe("<div> a", "<div> b</div>")                                         # find is not a prefix
    assert not _safe("<div>", "<div>")                                                   # no suffix


def test_whitespace_differential_is_refused():
    assert not _safe("a - -b", "a--b") and not _safe("a--b", "a - -b")
    assert not _safe("a + +b", "a++b")
    assert not _safe("x = a - -b <div>", "x = a--b <div></div>")      # prefix altered, tag appended
    assert not _safe("import { A } from './ui'", "import {A, B} from './ui'")      # raw text outside content changed
    assert not _safe("import { A } from './ui'", "import { A, B }from './ui'")


def test_multi_char_operators_are_single_tokens():
    kinds = [t for _, t in fm.tokenize("a--b ++c => d ... e ?. f ** g === h !== i")]
    for op in ("--", "++", "=>", "...", "?.", "**", "===", "!=="):
        assert op in kinds


def test_shape_d_named_import_additions_are_refused():
    """Cut after five review rounds: weakest shape; A and C cover the observed repeat errors."""
    assert not _safe("import { A } from './ui'", "import { A, B } from './ui'")
    assert not _safe("import { A, B } from './ui';", "import { A, B, C } from './ui';")
    assert not _safe("import { A } from './ui'", "import { A,B } from './ui'")


def test_replay_skips_a_stored_patch_that_does_not_target_the_current_error_line(tmp_path, factory, monkeypatch):
    import asyncio as _a
    from aether_os.phases.p05_frontend.fix_memory_hook import RoundMemory
    monkeypatch.setattr(fm, "get_session_factory", lambda: factory)
    page = tmp_path / "src/pages/TaskPage.tsx"
    page.parent.mkdir(parents=True)
    far = "<div><p>hi</p>"
    page.write_text("\n".join(["// filler"] * 40 + [far, "const m = 2"]))   # stored find sits at line 41
    sig = fm.parse_errors(ERR)[0]["signature"]                                      # current error is on line 1
    run(fm.record("org", sig, "tsx:pages", [_p()]))
    applied = []
    mem = RoundMemory("org", tmp_path, lambda d, p: applied.append(p) or True)
    assert _a.run(mem.try_known(ERR)) == 0 and applied == []                         # not near line 1: skipped
    page.write_text(far + "\n")
    mem2 = RoundMemory("org", tmp_path, lambda d, p: applied.append(p) or True)
    assert _a.run(mem2.try_known(ERR)) == 1 and applied[0]["file"] == "src/pages/TaskPage.tsx"
