"""KAN-212: repair by small verified patches (unique find, validated, rolled back on failure)."""
from __future__ import annotations

import asyncio
import logging

from aether_os.core.codegen import patching as pt
from aether_os.phases.p07b_self_healing import patch_repair as pr

PY = "import os\n\ndef add(a, b):\n    return a + c\n\ndef sub(a, b):\n    return a - b\n"


def _proj(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text(PY)
    (tmp_path / "src" / "P.tsx").write_text("export const P = () => <div>{count}</div>;\n")
    return tmp_path


def _apply(root, patches, ts_check=None):
    return asyncio.run(pt.apply_verified(root, patches, "t", ts_check))


def test_valid_patch_fixes_py_and_tsx(tmp_path):
    root = _proj(tmp_path)

    async def ok():
        return True
    rep = _apply(root, [{"file": "src/m.py", "find": "a + c", "replace": "a + b"},
                        {"file": "src/P.tsx", "find": "{count}", "replace": "{0}"}], ok)
    assert (rep.proposed, rep.applied, rep.rolled_back) == (2, 2, 0)
    assert "a + b" in (root / "src/m.py").read_text() and "{0}" in (root / "src/P.tsx").read_text()


def test_ambiguous_find_is_not_applied(tmp_path):
    root = _proj(tmp_path)
    rep = _apply(root, [{"file": "src/m.py", "find": "return a", "replace": "return b"}])
    assert rep.applied == 0 and "ambiguous (2 matches)" in rep.reasons[0]
    assert (root / "src/m.py").read_text() == PY


def test_missing_find_and_path_escape_are_not_applied(tmp_path):
    root = _proj(tmp_path)
    rep = _apply(root, [{"file": "src/m.py", "find": "nope", "replace": "x"},
                        {"file": "../../etc/passwd", "find": "a", "replace": "b"}, "junk"])
    assert rep.applied == 0 and len(rep.reasons) == 3


def test_patch_that_breaks_compile_is_rolled_back(tmp_path):
    root = _proj(tmp_path)
    rep = _apply(root, [{"file": "src/m.py", "find": "a + c", "replace": "a +"}])
    assert (rep.applied, rep.rolled_back) == (0, 1) and (root / "src/m.py").read_text() == PY


def test_ts_patch_is_rolled_back_when_tsc_gets_worse(tmp_path):
    root = _proj(tmp_path)
    before = (root / "src/P.tsx").read_text()

    async def worse():
        return False
    rep = _apply(root, [{"file": "src/P.tsx", "find": "{count}", "replace": "{"}], worse)
    assert (rep.applied, rep.rolled_back) == (0, 1) and (root / "src/P.tsx").read_text() == before


def test_report_logs_proposed_applied_rolled_back(tmp_path, caplog):
    rep = _apply(_proj(tmp_path), [{"file": "src/m.py", "find": "a + c", "replace": "a +"}])
    with caplog.at_level(logging.INFO):
        rep.log("tag", 2)
    assert "proposed 1, applied 0, rolled back 1" in caplog.text


def test_error_context_reads_python_tracebacks(tmp_path):
    root = _proj(tmp_path)
    tb = f'File "{root}/src/m.py", line 4, in add\nNameError\nFile "/usr/lib/python3/x.py", line 9'
    ctx = pt.error_context(root, tb)
    assert "--- src/m.py" in ctx and "4|     return a + c" in ctx and "x.py" not in ctx


def test_rewrite_guards(tmp_path):
    f = tmp_path / "m.py"
    assert pt.reject_rewrite(PY, PY, f) == ""
    assert "syntax error" in pt.reject_rewrite("def add(:", PY, f)
    assert "drops sub" in pt.reject_rewrite("def add(a, b):\n    return a + b\n" * 3 + "import os\n" * 5, PY, f)
    assert "too large" in pt.reject_rewrite(PY, "x = 1\n" * 1000, f)


def test_p07b_uses_patches_not_a_whole_file_rewrite(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    (root / "src" / "big.py").write_text("x = 1\n" * 1000 + "def f():\n    return missing_name\n")
    big = root / "src" / "big.py"

    async def fake_patches(prompt, tag, timeout=60.0):
        assert "6007| " not in prompt and "missing_name" in prompt
        return [{"file": "src/big.py", "find": "return missing_name", "replace": "return 1"}]

    async def no_rewrite(*_a, **_k):
        raise AssertionError("whole-file rewrite must not be used")
    monkeypatch.setattr(pr, "request_patches", fake_patches)
    out = f'File "{big}", line 1002, in f\nNameError'
    assert asyncio.run(pr.heal_file(big, root, root / "t.py", out, None, "", 1, no_rewrite))
    assert "return 1" in big.read_text()


def test_p07b_large_file_without_applicable_patch_is_left_alone(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    big = root / "src" / "big.py"
    big.write_text("x = 1\n" * 1000)

    async def none(*_a, **_k):
        return []

    async def rewrite(*_a, **_k):
        raise AssertionError("too large for a rewrite")
    monkeypatch.setattr(pr, "request_patches", none)
    assert not asyncio.run(pr.heal_file(big, root, root / "t.py", "boom", None, "", 1, rewrite))


def test_p07b_small_file_rewrite_still_guarded(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    m = root / "src" / "m.py"

    async def none(*_a, **_k):
        return []

    async def bad(*_a, **_k):
        return "def add(:"
    monkeypatch.setattr(pr, "request_patches", none)
    assert not asyncio.run(pr.heal_file(m, root, root / "t.py", "boom", None, "", 1, bad))
    assert m.read_text() == PY

    async def good(*_a, **_k):
        return PY.replace("a + c", "a + b")
    assert asyncio.run(pr.heal_file(m, root, root / "t.py", "boom", None, "", 1, good))
    assert "a + b" in m.read_text()
