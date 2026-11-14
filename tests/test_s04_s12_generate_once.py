"""KAN-109/KAN-98: s12 must not regenerate the specialist phases s04 already ran."""
import asyncio
from types import SimpleNamespace

from aether_os.stages.s12_specialist import supervisor as s12


def _run(monkeypatch, tmp_path, extra):
    ran = []

    async def sub(self, phase, pi, mem, pm):
        ran.append(phase)
        return s12.TaskResult(output_path=str(tmp_path), confidence=1.0)

    monkeypatch.setattr(s12.SpecialistStageSupervisor, "_run_sub_phase", sub)
    monkeypatch.setattr("aether_os.core.projects.get_project_manager",
                        lambda: SimpleNamespace(get_output_dir=lambda *a: tmp_path))
    data = {"build_profile": {"frontend_framework": "react_native", "build_type": "cli"}, **extra}
    asyncio.run(s12.SpecialistStageSupervisor().run_task(SimpleNamespace(project_id="p", input_data=data), []))
    return ran


def test_s12_runs_specialists_s04_did_not(monkeypatch, tmp_path):
    assert sorted(_run(monkeypatch, tmp_path, {})) == ["p05b_mobile", "p05d_cli"]


def test_s12_skips_what_s04_ran(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, {"specialist_phases_run": ["p05b_mobile", "p05d_cli"]}) == []
