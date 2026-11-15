"""KAN-97/KAN-98: non-critical sub-phase failures are survivable; gate denials always stop the run."""
import asyncio
from types import ModuleType, SimpleNamespace

import pytest

from aether_os.core.errors import PipelineBlockedError
from aether_os.stages.s01_intake import supervisor as s01
from aether_os.stages.s02_architecture import supervisor as s02


def _fake_import(raises):
    def imp(name):
        m = ModuleType(name)

        async def run(pi, mem, out):
            raise raises

        m.run = run
        return m
    return imp


class _PM:
    def get_output_dir(self, pid, ph):
        import tempfile
        return __import__("pathlib").Path(tempfile.mkdtemp())


def _sup(mod):
    return (mod.IntakeStageSupervisor if mod is s01 else mod.ArchitectureStageSupervisor)()


@pytest.mark.parametrize("mod", [s01, s02])
def test_non_critical_returns_exception_critical_raises(monkeypatch, mod):
    monkeypatch.setattr(mod.importlib, "import_module", _fake_import(RuntimeError("boom")))
    pi = SimpleNamespace(project_id="p")
    sup = _sup(mod)
    r = asyncio.run(sup._run_sub_phase("p", pi, [], _PM(), critical=False))
    assert isinstance(r, RuntimeError)
    with pytest.raises(RuntimeError):
        asyncio.run(sup._run_sub_phase("p", pi, [], _PM()))


@pytest.mark.parametrize("mod", [s01, s02])
def test_gate_denial_always_propagates(monkeypatch, mod):
    monkeypatch.setattr(mod.importlib, "import_module", _fake_import(PipelineBlockedError("denied")))
    with pytest.raises(PipelineBlockedError):
        asyncio.run(_sup(mod)._run_sub_phase("p", SimpleNamespace(project_id="p"), [], _PM(), critical=False))


def test_s01_parallel_gate_denial_stops_run(monkeypatch):
    # String-target setattr first: pytest 9 resolves it via importlib.import_module, which the next line fakes.
    monkeypatch.setattr("aether_os.core.projects.get_project_manager", lambda: _PM())
    monkeypatch.setattr(s01.importlib, "import_module", _fake_import(PipelineBlockedError("Gate 1 denied")))
    pi = SimpleNamespace(project_id="p", run_id="r", input_data={})
    with pytest.raises(PipelineBlockedError):
        asyncio.run(_sup(s01).run_task(pi, []))


def test_s01_p00c_runs_after_p00_and_sees_its_build_profile(monkeypatch):
    # KAN-98 item 3: p00c reads build_profile while p00 (which produces it) ran in parallel.
    seen = {}

    def imp(name):
        m = ModuleType(name)

        async def run(pi, mem, out):
            from aether_os.phases.base import TaskResult
            if "p00_research" in name:
                await asyncio.sleep(0.05)   # slow producer: a parallel p00c would start first
                return TaskResult(output_path="", confidence=1, metadata={"build_profile": {"architecture": "microservices"}})
            if "p00c" in name:
                seen["profile"] = pi.input_data.get("build_profile")
            if "p01_intake" in name:
                pi.input_data.update(entities=[{"name": "x"}], project_contract={"a": 1})
            return TaskResult(output_path="", confidence=1, metadata={})

        m.run = run
        return m

    monkeypatch.setattr(s01.importlib, "import_module", imp)
    monkeypatch.setattr("aether_os.core.projects.get_project_manager", lambda: _PM())
    pi = SimpleNamespace(project_id="p", run_id="r", input_data={})
    asyncio.run(_sup(s01).run_task(pi, []))
    assert seen["profile"] == {"architecture": "microservices"}
