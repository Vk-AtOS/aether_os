"""Run da281716: healing exhausted its attempts and s07 reported only "the probe never ran: unit tests were not
passing", so nobody knew whether the generated app even started. The healer now starts + probes the app after the
last attempt too; the verdict records what the probe saw and still fails on the exhausted healing.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from aether_os.phases.p07b_self_healing import task_agent as heal
from aether_os.stages.s07_healing.run_verdict import decide


def test_the_app_is_probed_after_healing_is_exhausted(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("app = None\n")
    (tmp_path / "test_main.py").write_text("def test_x(): assert False\n")
    probes = []

    async def failing_tests(test_file):
        return {"passed": False, "output": "FAILED test_main.py::test_create - 409"}

    async def no_fix(*a, **k):
        return False

    async def probe(project_dir, entities, output_dir, live_hook):
        probes.append(entities)
        return {"l1_passed": True, "live_tests": {"endpoints": {"passed": True, "failures": [], "checks": []}}}

    monkeypatch.setattr(heal, "_find_file", lambda d, pat: tmp_path / ("src/main.py" if pat == "main.py" else "test_main.py"))
    monkeypatch.setattr(heal, "_run_tests", failing_tests)
    monkeypatch.setattr(heal, "heal_file", no_fix)
    monkeypatch.setattr(heal, "apply_deterministic_fallback", lambda *a: None)
    monkeypatch.setattr(heal, "_quality_probe", probe)
    pi = SimpleNamespace(run_id="r", input_data={"entities": [{"name": "Task"}]})
    out = tmp_path / "out"
    result = asyncio.run(heal._run_inner(pi, [], out, live_hook=None))

    assert result.success is False and result.metadata["status"] == "max_attempts_reached"
    assert probes == [["Task"]]                       # probed once, after the last attempt
    verdict = decide(result.metadata)
    assert verdict["passed"] is False and verdict["app_started"] is True
    assert verdict["reasons"] == ["healing did not get the unit tests passing (max_attempts_reached)"]
    assert '"l1_passed": true' in Path(out / "self_healing.json").read_text()
