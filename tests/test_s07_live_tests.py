"""KAN-109: the live perf/a11y/e2e tests run against the probe app, or are skipped with a recorded reason."""
import asyncio
from types import SimpleNamespace

from aether_os.phases.base import TaskResult
from aether_os.phases.p07b_self_healing import task_agent as heal
from aether_os.stages.s07_healing import supervisor as s07


class _R:
    def __init__(self, layer, passed):
        self.layer, self.passed, self.failure_type = layer, passed, None if passed else "crash"


class _Mon:
    def __init__(self, **kw):
        pass

    async def run_full_check(self):
        return [_R("startup", self.up)]

    def get_failure_type(self, r):
        return None

    def to_dict(self):
        return {}


def _probe(monkeypatch, tmp_path, up, hook):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("")
    _Mon.up = up
    monkeypatch.setattr(heal, "QualityMonitor", _Mon)
    proc = SimpleNamespace(poll=lambda: 0)
    monkeypatch.setattr(heal.phase_exec, "start_app", lambda *a, **k: proc)
    monkeypatch.setattr(heal.socket, "create_connection", lambda *a, **k: _Ctx())
    return asyncio.run(heal._quality_probe(tmp_path, [], tmp_path, hook))


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_probe_writes_l1_and_runs_live_hook(monkeypatch, tmp_path):
    seen = []

    async def hook(port):
        seen.append(port)
        return {"ok": True}

    out = _probe(monkeypatch, tmp_path, True, hook)
    assert out["l1_passed"] is True and out["live_tests"] == {"ok": True} and seen


def test_probe_does_not_run_live_hook_when_app_down(monkeypatch, tmp_path):
    async def hook(port):
        raise AssertionError("must not run")

    out = _probe(monkeypatch, tmp_path, False, hook)
    assert out["l1_passed"] is False and out["live_tests"] is None


def test_s07_records_skip_reason(monkeypatch, tmp_path):
    async def fake_heal(pi, mem, out, live_hook=None):
        return TaskResult(output_path=str(out), confidence=0.5, metadata={
            "status": "all_tests_passing", "quality_probe": {"skipped": True, "reason": "no_main_py"}})

    monkeypatch.setattr("aether_os.phases.p07b_self_healing.task_agent.run", fake_heal)
    monkeypatch.setattr("aether_os.core.projects.get_project_manager",
                        lambda: SimpleNamespace(get_output_dir=lambda *a: tmp_path / "o"))
    pi = SimpleNamespace(project_id="p", input_data={})
    res = asyncio.run(s07.HealingStageSupervisor().run_task(pi, []))
    assert res.metadata["live_test_results"]["skipped"] is True
    assert "no_main_py" in res.metadata["live_test_results"]["reason"]
