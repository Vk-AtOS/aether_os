"""With no dedicated reviewer configured, the council reviews through the install's model router (KAN-220)."""
from __future__ import annotations

import asyncio

from aether_os.core.council import council_reviewer as cr

REPLY = "SCORE: 8\nISSUES:\n- missing index on tasks.owner_id\nSTRENGTHS:\n- parameterised queries\n"


class _Client:
    def __init__(self, reply=REPLY, fail=False):
        self.calls, self.reply, self.fail = [], reply, fail

    async def call(self, prompt, task_type="code_generation", system=None, org_id=None, **kw):
        self.calls.append((task_type, org_id))
        if self.fail:
            raise RuntimeError("provider down")
        return self.reply


def _no_dedicated(monkeypatch):
    async def none(*a, **k):
        return None
    for name in ("_call_claude", "_call_gemini", "_call_ollama"):
        monkeypatch.setattr(cr, name, none)


def test_router_reviews_when_no_dedicated_reviewer(monkeypatch):
    _no_dedicated(monkeypatch)
    client = _Client()
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: client)
    report = asyncio.run(cr.run_council("def f():\n    return 1\n", "r1", org_id="org1"))
    assert len(report.reviews) == 2 and report.average_score > 0
    assert client.calls == [("code_review", "org1"), ("code_review", "org1")]


def test_router_failure_leaves_an_empty_report(monkeypatch):
    _no_dedicated(monkeypatch)
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: _Client(fail=True))
    report = asyncio.run(cr.run_council("x = 1\n", "r2"))
    assert report.reviews == []


def test_router_not_used_when_a_dedicated_reviewer_answers(monkeypatch):
    _no_dedicated(monkeypatch)

    async def claude(*a, **k):
        return cr._parse_review_response(REPLY, "claude", "Security")
    monkeypatch.setattr(cr, "_call_claude", claude)
    client = _Client()
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: client)
    report = asyncio.run(cr.run_council("x = 1\n", "r3"))
    assert len(report.reviews) == 1 and client.calls == []
