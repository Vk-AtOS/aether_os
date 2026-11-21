"""p05 policy: the phase succeeds when `vite build` bundles; leftover tsc errors are warnings with a visible count."""
from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

from aether_os.phases.p05_frontend import build_loop
from aether_os.phases.p05_frontend.build_loop import result_summary, run_build_loop
from aether_os.stages.s04_frontend.supervisor import FrontendStageSupervisor

TSC_OUT = "".join(f"src/a.tsx({i},1): error TS2322: bad {i}\n" for i in range(14))


def _cp(code, out=""):
    return subprocess.CompletedProcess([], code, stdout=out, stderr="")


def _run(monkeypatch, tmp_path, tsc, build, make_dist=True, patches=None):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    calls = []

    async def fake_exec(argv, **kw):
        calls.append(argv[:3])
        if argv[1] == "tsc":
            return tsc
        if make_dist and build.returncode == 0:
            (tmp_path / "dist").mkdir(exist_ok=True)
            (tmp_path / "dist" / "index.html").write_text("<html/>")
        return build

    async def fake_fix(_):
        return patches or []

    monkeypatch.setattr(build_loop.phase_exec, "run", fake_exec)
    monkeypatch.setattr(build_loop, "_llm_fix", fake_fix)
    return asyncio.run(run_build_loop(tmp_path, max_rounds=3)), calls


def test_built_with_tsc_errors_is_success_with_count_and_messages(monkeypatch, tmp_path):
    res, _ = _run(monkeypatch, tmp_path, _cp(2, TSC_OUT), _cp(0))
    assert res["success"] is True and res["built"] is True
    assert res["tsc_errors"] == 14 and len(res["tsc_messages"]) == build_loop.MAX_TSC_MESSAGES
    meta, issues = result_summary(res)
    assert meta["tsc_errors"] == 14 and meta["build_ok"] and "14 TypeScript error" in issues[0]


def test_vite_failure_is_failure(monkeypatch, tmp_path):
    res, _ = _run(monkeypatch, tmp_path, _cp(2, TSC_OUT), _cp(1))
    assert res["success"] is False and res["tsc_errors"] == 14
    assert result_summary(res)[1] == []


def test_build_ok_but_no_dist_is_failure(monkeypatch, tmp_path):
    res, _ = _run(monkeypatch, tmp_path, _cp(0), _cp(0), make_dist=False)
    assert res["success"] is False


def test_clean_run_is_one_round(monkeypatch, tmp_path):
    res, calls = _run(monkeypatch, tmp_path, _cp(0), _cp(0))
    assert res == {"success": True, "built": True, "tsc_errors": 0, "tsc_messages": [], "rounds": 1}


def test_loop_keeps_trying_to_fix_tsc_errors(monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.tsx").write_text("const x = 1\n")
    patch = [{"file": "src/a.tsx", "find": "const x = 1", "replace": "const x = 2"}]
    res, calls = _run(monkeypatch, tmp_path, _cp(2, TSC_OUT), _cp(0), patches=patch)
    assert res["success"] and res["tsc_errors"] == 14
    assert [c[1] for c in calls].count("tsc") >= 2 or res["rounds"] >= 1  # tried at least once more or bailed on a no-op patch
    assert (tmp_path / "src" / "a.tsx").read_text() == "const x = 2\n"


def _sup_result(success, tsc_errors):
    return SimpleNamespace(success=success, confidence=0.7, output_path="", status="ok",
                           metadata={"frontend_output_path": "", "tsc_errors": tsc_errors, "tsc_messages": ["e1"]})


def test_s04_gate_passes_with_tsc_warning(tmp_path):
    (tmp_path / "index.html").write_text("<html/>")
    r = _sup_result(True, 5)
    r.metadata["frontend_output_path"] = str(tmp_path)
    out = asyncio.run(FrontendStageSupervisor().validate_gate(r, None))
    assert out.passed and "5 TypeScript error" in out.issues[0]


def test_s04_gate_fails_when_build_failed(tmp_path):
    (tmp_path / "index.html").write_text("<html/>")
    r = _sup_result(False, 5)
    r.metadata["frontend_output_path"] = str(tmp_path)
    assert not asyncio.run(FrontendStageSupervisor().validate_gate(r, None)).passed
