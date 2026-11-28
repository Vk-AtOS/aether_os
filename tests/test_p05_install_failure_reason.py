"""Run da281716 (s04): `npm install` timed out after 300s, p05 returned success=False with no issue, and the stage
gate could only say "p05_frontend failed and recorded no error text". Then the preview screenshot ran a second
install + build (4.5 minutes) for an app whose dependencies were not there. Both are fixed here.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from aether_os.phases.failure_reason import failure_issues
from aether_os.phases.p05_frontend import npm_runner, preview


def _frontend(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text('{"name": "x", "dependencies": {}}')
    return tmp_path


def test_an_install_that_raises_returns_its_reason(tmp_path, monkeypatch):
    async def timed_out(*a, **k):
        raise RuntimeError("command timed out after 300s")
    monkeypatch.setattr(npm_runner.phase_exec, "run", timed_out)
    why = asyncio.run(npm_runner.install_frontend_deps(_frontend(tmp_path)))
    assert "npm install failed" in why and "timed out after 300s" in why
    # the stage gate now names it instead of "recorded no error text"
    issue = failure_issues("s04_frontend", "p05_frontend", SimpleNamespace(issues=[why], metadata={}))[0]
    assert "timed out after 300s" in issue


def test_a_failing_exit_code_is_reported_and_success_stamps_node_modules(tmp_path, monkeypatch):
    codes = iter([1, 0])

    fe = _frontend(tmp_path)

    async def run(*a, **k):
        code = next(codes)
        if code == 0:
            (fe / "node_modules").mkdir()
        return SimpleNamespace(returncode=code, stderr="npm ERR! network ETIMEDOUT")
    monkeypatch.setattr(npm_runner.phase_exec, "run", run)
    assert "exit 1" in asyncio.run(npm_runner.install_frontend_deps(fe))
    assert asyncio.run(npm_runner.install_frontend_deps(fe)) == ""
    assert npm_runner.node_modules_fresh(fe, npm_runner.pkg_hash(fe))
    assert asyncio.run(npm_runner.install_frontend_deps(fe)) == ""    # fresh: no third npm call (iterator is empty)


def test_preview_does_not_reinstall_when_the_build_produced_nothing(tmp_path, monkeypatch):
    calls = []

    async def run(*a, **k):
        calls.append(a)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(preview.phase_exec, "run", run)
    assert asyncio.run(preview.take_preview_screenshot(_frontend(tmp_path), tmp_path / "shot.png")) is False
    assert calls == []
