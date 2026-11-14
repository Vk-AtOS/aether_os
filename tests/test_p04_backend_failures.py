"""KAN-98/KAN-109: p04_backend does not swallow gate/sandbox failures; the uiux gate can fail."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from aether_os.core.errors import PipelineBlockedError
from aether_os.core.sandbox.runner import SandboxUnavailable
from aether_os.phases.base import TaskResult
from aether_os.phases.p04_backend import task_agent
from aether_os.phases.p04_uiux_design import gate


def _run(monkeypatch, tmp_path, backend, uiux=None):
    import aether_os.phases.p04a_backend_codegen.task_agent as a
    import aether_os.phases.p04_uiux_design.task_agent as u

    async def run_a(*x):
        return backend() if callable(backend) else backend

    async def run_u(*x):
        return TaskResult(output_path=str(tmp_path), confidence=1.0)

    monkeypatch.setattr(a, "run", run_a)
    monkeypatch.setattr(u, "run", run_u)
    pi = SimpleNamespace(input_data={}, run_id="r", project_id="p")
    return asyncio.run(task_agent.run(pi, [], tmp_path / "o"))


@pytest.mark.parametrize("exc", [SandboxUnavailable("no sandbox"), PipelineBlockedError("denied")])
def test_blocking_errors_propagate(monkeypatch, tmp_path, exc):
    def boom():
        raise exc
    with pytest.raises(type(exc)):
        _run(monkeypatch, tmp_path, boom)


def test_design_only_is_not_success(monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("codegen died")
    res = _run(monkeypatch, tmp_path, boom)
    assert res.success is False


def test_uiux_gate_fails_without_pages_or_components(tmp_path):
    f = tmp_path / "d.json"
    f.write_text(json.dumps({"pages": [], "components": []}))
    assert gate.validate(TaskResult(output_path=str(f), confidence=1.0)).passed is False
    f.write_text(json.dumps({"pages": [{"name": "A"}], "components": [{"name": "B"}]}))
    assert gate.validate(TaskResult(output_path=str(f), confidence=1.0)).passed is True
