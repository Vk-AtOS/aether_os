"""KAN-100 p15: the Postman collection exists without a model, a malformed model answer cannot crash the phase,
and the gate finds postman/collection.json."""
import asyncio
import json
from types import SimpleNamespace

from aether_os.phases.base import TaskResult
from aether_os.phases.p15_handoff import gate, task_agent

ENDPOINTS = [{"method": "get", "path": "/api/items"}, {"method": "POST", "path": "/api/items"}]


def _run(tmp_path, monkeypatch, llm):
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda *a, **k: llm)
    data = {"project_name": "Demo", "architecture_json": {"api_endpoints": ENDPOINTS}}
    return asyncio.run(task_agent.run(SimpleNamespace(input_data=data), [], tmp_path))


def test_collection_lists_the_endpoints_even_with_no_model(tmp_path, monkeypatch):
    class Down:
        async def call(self, *a, **k):
            raise RuntimeError("no model")
    _run(tmp_path, monkeypatch, Down())
    items = json.loads((tmp_path / "postman" / "collection.json").read_text())["item"]
    assert [i["name"] for i in items] == ["GET /api/items", "POST /api/items"]       # was [] unless the call itself raised


def test_non_string_model_documents_fall_back_to_the_defaults(tmp_path, monkeypatch):
    class Odd:
        async def call(self, *a, **k):
            return json.dumps({"readme": ["not", "text"], "architecture": None, "database": 3, "api": "",
                               "runbook": {}, "permissions": 1, "development": None})
    _run(tmp_path, monkeypatch, Odd())                                  # used to raise TypeError in write_text
    assert (tmp_path / "docs" / "README.md").read_text().startswith("# Demo")


def test_gate_finds_the_postman_collection_in_its_folder(tmp_path, monkeypatch):
    class Down:
        async def call(self, *a, **k):
            raise RuntimeError("no model")
    r = _run(tmp_path, monkeypatch, Down())
    out = gate.validate(TaskResult(output_path=r.output_path, confidence=0.9, metadata={}, success=True))
    assert not any("Postman" in i for i in out.issues), out.issues
