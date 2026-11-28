"""KAN-247: the s09 and s11 gates block on their real failure conditions (they used to always pass)."""
import asyncio

from aether_os.phases.base import TaskResult
from aether_os.stages.s09_devops import supervisor as s09
from aether_os.stages.s11_handoff import supervisor as s11


# ── s09 / s11 gates block on their real failures ─────────────────────────────

def _gate(sup, meta):
    return asyncio.run(sup.validate_gate(TaskResult("o", 0.8, metadata=meta), None))


def test_s09_blocks_without_dockerfile_or_when_the_deploy_failed(tmp_path):
    df = tmp_path / "Dockerfile"
    df.write_text("FROM python")
    sup = s09.DevOpsStageSupervisor()
    assert not _gate(sup, {"dockerfile_path": "", "deploy": {"state": "deployed"}}).passed
    failed = _gate(sup, {"dockerfile_path": str(df), "deploy": {"state": "failed", "reason": "/health never 200"}})
    assert not failed.passed and "/health never 200" in failed.issues[0]
    ok = _gate(sup, {"dockerfile_path": str(df), "ci_workflow_path": str(df), "deploy": {"state": "deployed"}})
    assert ok.passed and ok.issues == []


def test_s09_deploy_status_from_p11():
    no_docker = TaskResult("o", 0.8, metadata={"skipped": True, "message": "Docker not available"}, success=True)
    assert s09._deploy_status(no_docker, "") == {"state": "not_deployed", "reason": "Docker not available",
                                                 "live_url": None}
    broken = TaskResult("o", 0.3, metadata={}, issues=["Container health check failed"], success=False)
    assert s09._deploy_status(broken, "")["state"] == "failed"
    up = TaskResult("o", 0.9, metadata={"live_url": "http://h:1"}, success=True)
    assert s09._deploy_status(up, "http://h:1")["state"] == "deployed"


def test_s11_blocks_when_the_run_cannot_be_exported(tmp_path):
    sup = s11.HandoffStageSupervisor()
    q = tmp_path / "q.json"
    q.write_text("{}")
    refused = _gate(sup, {"export_manifest_path": None, "quality_report_path": str(q),
                          "export_error": "Export check failed: secret found in backend/.env"})
    assert not refused.passed and "secret found in backend/.env" in refused.issues[0]
    assert not _gate(sup, {"export_manifest_path": None, "quality_report_path": None}).passed
    m = tmp_path / "export_manifest.json"
    m.write_text("{}")
    assert not _gate(sup, {"export_manifest_path": str(m), "quality_report_path": None}).passed
    assert _gate(sup, {"export_manifest_path": str(m), "quality_report_path": str(q)}).passed
