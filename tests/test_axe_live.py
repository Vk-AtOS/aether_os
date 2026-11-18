"""KAN-177: a live axe-core result reaches the frontend critic when a build and the browser sandbox exist; else a note."""
import asyncio

from aether_os.core.quality import axe_live
from aether_os.core.sandbox.runner import SandboxUnavailable


def _build(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>")


def _run(tmp_path, monkeypatch, reply):
    async def job(j, *, project, timeout=120):
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(axe_live, "run_browser_job", job)
    monkeypatch.setattr(axe_live.phase_exec, "project_root", lambda p: tmp_path)
    return asyncio.run(axe_live.live_axe_violations(tmp_path))


def test_count_from_the_sandbox_when_a_build_exists(tmp_path, monkeypatch):
    _build(tmp_path)
    assert _run(tmp_path, monkeypatch, {"ok": True, "violations": 3}) == (3, "")
    assert _run(tmp_path, monkeypatch, {"ok": True, "violations": 0}) == (0, "")


def test_not_run_is_none_with_a_reason_never_zero(tmp_path, monkeypatch):
    count, note = _run(tmp_path, monkeypatch, {"ok": True, "violations": 1})      # no dist/ yet
    assert count is None and "no build" in note
    _build(tmp_path)
    count, note = _run(tmp_path, monkeypatch, SandboxUnavailable("no docker"))
    assert count is None and "unavailable" in note
    count, note = _run(tmp_path, monkeypatch, {"ok": False, "error": "crashed"})
    assert count is None and "crashed" in note


def test_s05_uses_the_a11y_stage_count_else_runs_axe_now():
    import inspect
    from aether_os.stages.s05_quality import supervisor
    src = inspect.getsource(supervisor)
    assert 'a11y.get("violations") if a11y.get("ran_axe")' in src       # was the never-set key violations_count
    assert "live_axe_violations(Path(fe_path))" in src
