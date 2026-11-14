"""KAN-100: p11 does not treat a failed deploy as a skip, and its network can publish ports."""
import asyncio

from aether_os.phases.base import TaskResult
from aether_os.phases.p11_deployment import gate, helpers


def test_failed_deploy_marked_skipped_is_not_a_success():
    meta = {"success": False, "skipped": True, "error": "No main.py found to deploy"}
    out = gate.validate(TaskResult(output_path="", confidence=0.4, metadata=meta, success=False))
    assert out.passed is False


def test_real_skip_still_passes():
    meta = {"success": True, "skipped": True}
    assert gate.validate(TaskResult(output_path="", confidence=0.9, metadata=meta)).passed is True


def test_supervisor_does_not_upgrade_failed_skip(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from aether_os.phases.p11_deployment import supervisor_agent as sup
    import aether_os.phases.p11_deployment.task_agent as ta

    class FakeAgent:
        async def run(self, pi):
            return {"success": False, "skipped": True, "error": "x"}

    monkeypatch.setattr(ta, "TaskAgent", FakeAgent)
    monkeypatch.setattr("aether_os.core.projects.get_project_manager",
                        lambda: SimpleNamespace(get_output_dir=lambda *a: tmp_path))
    res = asyncio.run(sup.DeploymentSupervisor().run_task(SimpleNamespace(project_id="p"), []))
    assert res.success is False


def test_network_is_not_internal(monkeypatch):
    calls = []

    class P:
        returncode = 1

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, **kw):
        calls.append(args)
        return P()

    monkeypatch.setattr(helpers.asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(helpers.ensure_network())
    create = next(c for c in calls if "create" in c)
    assert "--internal" not in create and helpers.APP_NETWORK in create
