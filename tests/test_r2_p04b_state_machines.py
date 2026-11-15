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
