"""KAN-185: a run with a failed s06 shows it in the run result."""
import asyncio
from types import SimpleNamespace

from aether_os.orchestrator.stage_gate import summarize_stage_outcomes
from aether_os.stages.s06_testing import supervisor as s06


def test_summary_lists_failed_and_skipped():
    out = summarize_stage_outcomes({
        "s05_quality": {"status": "passed"},
        "s06_testing": {"status": "failed", "issues": ["unit tests failed"]},
        "s08_observability": {"status": "skipped", "metadata": {"skipped_reason": "disabled_in_settings"}},
        "s07_healing": {"status": "timeout", "error": "phase timed out"},
    })
    assert [f["stage"] for f in out["failed_stages"]] == ["s06_testing", "s07_healing"]
    assert out["skipped_stages"] == [{"stage": "s08_observability", "reason": "disabled_in_settings"}]
    assert out["all_stages_ok"] is False


def test_clean_run_is_ok():
    assert summarize_stage_outcomes({"s01": {"status": "passed"}})["all_stages_ok"] is True


def test_s06_with_failing_verdict_is_a_failed_stage(monkeypatch, tmp_path):
    bad = {"test_quality_flag": "fail", "phases": {}}
    monkeypatch.setattr(s06, "_consolidate_results", lambda r, i: bad)

    monkeypatch.setattr("aether_os.core.projects.get_project_manager",
                        lambda: SimpleNamespace(get_output_dir=lambda *a: tmp_path))
    monkeypatch.setattr(s06.asyncio, "gather", lambda *a, **k: _empty())
    pi = SimpleNamespace(project_id="p", run_id="r", input_data={})
    res = asyncio.run(s06.TestingStageSupervisor().run_task(pi, []))
    assert res.success is False


async def _empty():
    return []
