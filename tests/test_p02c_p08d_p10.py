"""KAN-98/KAN-100/KAN-97: p02c accepts its own default model; p08 deployment fails when all sub-tasks fail; dead duplicate portal is gone."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from aether_os.phases.p02c_permission_modeling import task_agent as p02c


def test_p02c_accepts_the_model_its_prompt_describes():
    model = {"roles": ["Admin", "Staff"], "permissions": {"Admin": {"Invoice": ["read"]}}, "field_masks": {}}
    assert p02c._validate_permission_model(model) == []
    assert p02c._validate_permission_model({"roles": [{"name": "A"}], "permissions": []}) == []
    assert p02c._validate_permission_model({"roles": [], "permissions": {}})


def test_p08_deployment_all_failed_is_failure(monkeypatch, tmp_path):
    from aether_os.phases.base import TaskResult
    from aether_os.phases.p08_cicd_deployment import task_agent as t

    class Fake:
        def __init__(self):
            pass

        async def run(self, pi):
            return {"status": "failed", "output_path": ""}
    monkeypatch.setattr("aether_os.phases.p08_cicd.task_agent.CICDAgent", Fake)

    class Dep:
        async def run(self, pi):
            return {"success": False}
    monkeypatch.setattr("aether_os.phases.p11_deployment.task_agent.TaskAgent", Dep)
    pi = SimpleNamespace(input_data={}, run_id="r")
    res = asyncio.run(t.run(pi, [], tmp_path))
    assert res.success is False


def test_unauthenticated_duplicate_portal_is_removed():
    assert not (Path(__file__).resolve().parents[1] / "phases" / "gateway").exists()
