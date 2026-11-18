"""KAN-98: a stub IR is not a clean run; pattern triggers match words, not substrings."""
import asyncio
from types import SimpleNamespace

import pytest

from aether_os.phases.p02b_domain_ir import task_agent
from aether_os.phases.patterns import PatternSelector


def _names(ir):
    return {p.name for p in PatternSelector(ir).select()}


def test_pattern_triggers_match_whole_words_only():
    # 'ws' inside news/shows, 'file' inside profile, 'role' inside controller selected real-time/upload/rbac code
    noise = {"entities": [{"name": "Article", "fields": [{"name": "newsletter"}, {"name": "shows"}, {"name": "filename"},
                                                         {"name": "controller"}, {"name": "delivery"}]}]}
    assert _names(noise) == set()
    real = {"entities": [{"name": "Invoice", "fields": [{"name": "file_url"}, {"name": "subscriptions"}]}],
            "note": "needs websocket updates"}
    got = _names(real)
    assert got and len(got) >= 2


def test_stub_ir_result_is_flagged_and_not_confident(tmp_path, monkeypatch):
    async def empty(**kw):
        return {}, {}, {}, {}, []
    monkeypatch.setattr(task_agent, "run_4pass_extraction", empty)
    monkeypatch.setattr(task_agent, "get_llm_client", lambda: object())
    pi = SimpleNamespace(run_id="r", domain="general", input_data={"raw_input": "build me an app", "app_name": "Thing"})
    res = asyncio.run(task_agent.run(pi, [], tmp_path))
    assert res.success and res.metadata["stub_ir"] is True
    assert res.confidence <= 0.3 and res.issues


@pytest.mark.parametrize("trigger_text", ["a payment page", "chat room"])
def test_real_triggers_still_select(trigger_text):
    assert _names({"summary": trigger_text})
