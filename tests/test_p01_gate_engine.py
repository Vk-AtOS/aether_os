"""KAN-97/KAN-109: p01 entity gate stops on denial/timeout; verification uses a real LLM method."""
import asyncio
from types import SimpleNamespace

import pytest

from aether_os.core.errors import PipelineBlockedError
from aether_os.core.llm.client import LLMClient
from aether_os.phases.p01_intake_requirements import gate_engine


def _run_gate(monkeypatch, status, choice=None):
    from aether_os.core.decisions import decision_engine as de
    from aether_os.core import pipeline_state
    from aether_os.orchestrator import events

    class Eng:
        async def request_approval(self, d):
            pass

        async def await_decision(self, i):
            return SimpleNamespace(status=status, human_choice=choice)

    async def noop(*a, **k):
        pass

    monkeypatch.setattr(de, "get_decision_engine", lambda: Eng())
    monkeypatch.setattr(pipeline_state, "publish_event", noop)
    tok = events.ACTIVE_RUN_ID.set("run1")
    data = {}
    try:
        return asyncio.run(gate_engine.run_entity_approval_gate(
            data=data, confidence=0.3, confidence_reason="x",
            entities_extracted=[{"name": "A"}], requirements_doc={}, summary={})), data
    finally:
        events.ACTIVE_RUN_ID.reset(tok)


@pytest.mark.parametrize("status", ["denied", "timeout"])
def test_denied_or_timed_out_gate_blocks(monkeypatch, status):
    with pytest.raises(PipelineBlockedError):
        _run_gate(monkeypatch, status)


def test_corrected_entities_reach_input_data(monkeypatch):
    (_, _, ents), data = _run_gate(monkeypatch, "approved", "Foo, Bar")
    assert [e["name"] for e in data["entities"]] == ["Foo", "Bar"]


def test_llmclient_has_no_complete_and_verification_uses_call(monkeypatch):
    assert not hasattr(LLMClient, "complete")
    seen = {}

    class L:
        async def call(self, prompt, **kw):
            seen.update(kw)
            return "NO: something else"

    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: L())
    pi = SimpleNamespace(input_data={}, run_id="r")
    asyncio.run(gate_engine.run_intent_verification(
        data={"raw_input": "x " * 40}, requirements_doc={"entities": [{"name": "A"}]}, phase_input=pi))
    assert pi.input_data["intent_verification"].startswith("NO")
