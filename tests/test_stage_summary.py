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


# ── KAN-188 (M5): the s06 gate can fail, and says what it did not check ───────

def _unit(passed, failed):
    return {"unit_testing": s06.TaskResult("t.py", 0.75, metadata={"passed": passed, "failed": failed, "test_file": "t.py"})}


def _gate(consolidated):
    consolidated["gate"] = s06._gate_report(consolidated)
    res = s06.TaskResult("c.json", 0.5, metadata=consolidated)
    return asyncio.run(s06.TestingStageSupervisor().validate_gate(res, SimpleNamespace()))


def test_s06_gate_blocks_when_no_unit_test_ran():
    out = _gate(s06._consolidate_results({}, ["unit_testing failed: sandbox unavailable"]))
    assert out.passed is False
    assert out.issues == ["no unit test ran: unit_testing failed: sandbox unavailable"]
    assert _gate(s06._consolidate_results(_unit(0, 0), [])).passed is False      # pytest ran nothing


def test_s06_gate_lets_failing_tests_through_and_discloses_it():
    consolidated = s06._consolidate_results(_unit(6, 4), [])
    assert _gate(consolidated).passed is True
    gate = consolidated["gate"]
    assert gate["tests_failed_but_did_not_block"] is True and gate["tests_failed"] == 4
    assert any(n.startswith("e2e_testing: not run here") for n in gate["not_checked"])
    assert any("frontend unit tests" in n for n in gate["not_checked"])
    summary = summarize_stage_outcomes({"s06_testing": {"status": "passed", "metadata": consolidated}})
    assert summary["tests_failed_but_did_not_block"] is True and summary["tests_not_checked"] == gate["not_checked"]
    clean = s06._consolidate_results(_unit(10, 0), [])
    assert _gate(clean).passed and clean["gate"]["tests_failed_but_did_not_block"] is False


def test_s06_verdict_is_fail_when_most_unit_tests_fail():
    assert s06._consolidate_results(_unit(1, 9), [])["test_quality_flag"] == "fail"   # was "warn"
