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


def test_p11_compose_has_no_default_secret_key(tmp_path):
    # KAN-69: the generated compose defaulted SECRET_KEY to a placeholder identical in every app
    from aether_os.phases.p11_deployment.writers import write_docker_compose
    path = write_docker_compose(tmp_path, tmp_path)
    text = path.read_text()
    assert "SECRET_KEY: ${SECRET_KEY:?" in text and "changeme" not in text
