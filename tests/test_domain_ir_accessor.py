"""KAN-98: generators for non-Python output see the real domain model, not a placeholder entity."""
import asyncio
import json
from types import SimpleNamespace

from aether_os.phases.utils import get_domain_ir


def _ir(tmp_path):
    p = tmp_path / "domain_ir.json"
    p.write_text(json.dumps({"domain": "hr", "entities": [{"name": "Employee", "table": "employees", "fields": []}]}))
    return str(p)


def test_accessor_reads_the_path_s02_stores(tmp_path):
    assert get_domain_ir({"domain_ir_path": _ir(tmp_path)})["entities"][0]["table"] == "employees"
    assert get_domain_ir({"domain_ir": {"entities": [{"table": "x"}]}})["entities"][0]["table"] == "x"
    assert get_domain_ir({}) == {} and get_domain_ir({"domain_ir_path": "/nope"}) == {}


def test_mobile_generator_gets_ir_entities(monkeypatch, tmp_path):
    from aether_os.phases.p05b_mobile import task_agent
    seen = {}

    async def fake(entities, name, out, api):
        seen["entities"] = entities
        return tmp_path

    monkeypatch.setattr(task_agent, "generate_rn_project", fake)
    pi = SimpleNamespace(input_data={"domain_ir_path": _ir(tmp_path), "build_profile": {"frontend_framework": "react_native"}})
    asyncio.run(task_agent.run(pi, [], tmp_path / "o"))
    assert [e["table"] for e in seen["entities"]] == ["employees"]
