"""KAN-99 item 1: High/Critical security findings and Z3 FAIL block delivery (fail closed)."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from aether_os.phases.base import TaskResult
from aether_os.phases.p06_review_security.gate import validate as p06_validate
from aether_os.stages.s05_quality import supervisor as s05
from aether_os.stages.s05_quality.gate_functions import detect_critical_issues


def _gate(meta):
    sup = s05.QualityGateSupervisor()
    return asyncio.run(sup.validate_gate(TaskResult(output_path="x", confidence=1, metadata=meta), None))


def test_bandit_issue_severity_high_is_detected(tmp_path):
    issues = detect_critical_issues(tmp_path, [{"issue_severity": "HIGH", "description": "B602 shell=True"}], {})
    assert [i["severity"] for i in issues] == ["high"]


def test_gate_blocks_unresolved_high_and_z3_fail_but_not_clean():
    assert not _gate({"blocking_findings": ["B602 shell=True"]}).passed
    assert not _gate({"verification_report": {"overall_verdict": "FAIL"}}).passed
    assert _gate({"verification_report": {"overall_verdict": "PASS"}, "security_findings": [{"severity": "low"}]}).passed


def test_run_task_without_llm_leaves_high_finding_blocking(tmp_path, monkeypatch):
    p06 = TaskResult(output_path=str(tmp_path), confidence=.8, success=True,
                     metadata={"security_findings": [{"issue_severity": "HIGH", "description": "B602 shell=True"}]})
    async def fake(self, **k):
        return p06 if k["sub_phase_name"] == "p06_review_security" else TaskResult(output_path=str(tmp_path), confidence=1, success=True)
    monkeypatch.setattr(s05.QualityGateSupervisor, "_run_sub_phase", fake)
    monkeypatch.setattr(s05, "get_project_manager", lambda: SimpleNamespace(get_output_dir=lambda *a: tmp_path))
    pi = SimpleNamespace(project_id="p", run_id="r", input_data={"backend_output_path": str(tmp_path)})
    res = asyncio.run(s05.QualityGateSupervisor().run_task(pi, []))
    assert res.metadata["blocking_findings"] == ["B602 shell=True"]
    assert not asyncio.run(s05.QualityGateSupervisor().validate_gate(res, pi)).passed


def test_crashed_security_review_blocks(tmp_path, monkeypatch):
    dead = TaskResult(output_path=str(tmp_path), confidence=0, success=False, metadata={"skipped": True, "error": "boom"})
    async def fake(self, **k):
        return dead if k["sub_phase_name"] == "p06_review_security" else TaskResult(output_path=str(tmp_path), confidence=1, success=True)
    monkeypatch.setattr(s05.QualityGateSupervisor, "_run_sub_phase", fake)
    monkeypatch.setattr(s05, "get_project_manager", lambda: SimpleNamespace(get_output_dir=lambda *a: tmp_path))
    pi = SimpleNamespace(project_id="p", run_id="r", input_data={})
    res = asyncio.run(s05.QualityGateSupervisor().run_task(pi, []))
    assert not asyncio.run(s05.QualityGateSupervisor().validate_gate(res, pi)).passed


def test_p06_gate_counts_issue_severity_and_blocks_one_high(tmp_path):
    f = tmp_path / "c.json"
    f.write_text('{"phases":{"static_analysis":{"metadata":{"findings":[{"issue_severity":"HIGH"}]}}}}')
    assert not p06_validate(TaskResult(output_path=str(f), confidence=1)).passed
