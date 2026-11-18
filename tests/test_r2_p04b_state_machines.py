"""KAN-98 item 7: p04b state machines land in the backend src dir, not the phase output dir."""
import asyncio
import json
from types import SimpleNamespace

from aether_os.phases.p04b_business_logic import task_agent


def test_state_machines_are_written_into_backend_src(tmp_path, monkeypatch):
    def no_llm():
        raise RuntimeError("no model in tests")
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", no_llm)
    ir = tmp_path / "ir.json"
    ir.write_text(json.dumps({"entities": [], "workflows": [
        {"entity": "Order", "field": "status", "states": ["new", "paid"], "transitions": [["new", "paid"]],
         "terminal_states": ["paid"]}]}))
    src = tmp_path / "backend" / "src"
    src.mkdir(parents=True)
    out = tmp_path / "out"
    pi = SimpleNamespace(input_data={"domain_ir_path": str(ir), "backend_src_dir": str(src)}, raw_input="")
    asyncio.run(task_agent.run(pi, [], out))
    assert (src / "workflows" / "order_sm.py").is_file()
    assert not (out / "workflows").exists()


def _run_ir(tmp_path, monkeypatch, ir_doc):
    def no_llm():
        raise RuntimeError("no model in tests")
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", no_llm)
    ir = tmp_path / "ir.json"
    ir.write_text(json.dumps(ir_doc))
    src = tmp_path / "backend" / "src"
    src.mkdir(parents=True)
    pi = SimpleNamespace(input_data={"domain_ir_path": str(ir), "backend_src_dir": str(src),
                                     "integration_flags": {"needs_email": True}}, raw_input="")
    return asyncio.run(task_agent.run(pi, [], tmp_path / "out")), src


def test_hostile_workflow_and_event_names_are_refused_before_anything_is_written(tmp_path, monkeypatch):
    """KAN-69 G6: '../../x' wrote outside src and a quote closed a string in the generated source."""
    for n, ir_doc in enumerate(({"workflows": [{"entity": "../../evil", "steps": ["a"]}]},
                                {"workflows": [{"entity": "Order'); import os #", "steps": ["a"]}]},
                                {"notifications": [{"event": "../../../x", "template": "t"}]})):
        case = tmp_path / f"c{n}"
        case.mkdir()
        result, src = _run_ir(case, monkeypatch, ir_doc)
        assert result.success is False and "unsafe_name" in result.issues[0]
        assert not (src / "workflows").exists() and list(case.rglob("evil*")) == []


def test_notification_text_is_html_escaped(tmp_path, monkeypatch):
    result, src = _run_ir(tmp_path, monkeypatch, {"notifications": [{"event": "shipped", "template": "<script>x()</script>"}]})
    page = (src.parent / "templates" / "emails" / "shipped.html").read_text()
    assert "<script>x()" not in page and "&lt;script&gt;" in page
