"""KAN-275: the council sees real evidence, and a timeout or error is needs_review, never a pass."""
import asyncio
import json

import pytest

from aether_os.core.council import council as council_mod
from aether_os.core.council.delivery_evidence import build_delivery_evidence

RESULTS = {
    "s05_quality": {"status": "completed", "metadata": {"blocking_findings": ["SQL injection in /x"],
                    "verification_report": {"overall_verdict": "FAIL", "invariants_failed": [{}, {}]}}},
    "s06_testing": {"status": "completed", "metadata": {"total_tests": 40, "passed_tests": 31,
                    "gate": {"tests_ran": 40, "tests_failed": 9, "tests_failed_but_did_not_block": True}}},
    "s07_healing": {"status": "failed", "error": "app never became healthy",
                    "metadata": {"healing_passed": False, "quality_probe": {"passed": False, "failed_layers": ["crud"]}}},
}


def test_evidence_carries_real_failures_and_is_bounded():
    ev = json.loads(build_delivery_evidence(RESULTS))
    assert ev["tests"]["failed"] == 9 and ev["tests"]["failed_but_did_not_block"]
    assert ev["s07_probe"]["probe_passed"] is False and ev["s07_probe"]["failed_layers"] == ["crud"]
    assert ev["security_and_invariants"]["blocking_findings"] == ["SQL injection in /x"]
    assert ev["failed_or_skipped_stages"][0]["stage"] == "s07_healing"
    huge = {f"s{i}": {"status": "failed", "error": "x" * 5000} for i in range(100)}
    assert len(build_delivery_evidence(huge)) <= 3500


class _Client:
    def __init__(self, behaviour):
        self.behaviour, self.prompt = behaviour, None

    async def call(self, prompt, **kw):
        self.prompt = prompt
        return await self.behaviour()


def _patch(monkeypatch, client):
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: client)
    monkeypatch.setenv("COUNCIL_ENABLED", "true")


async def _run():
    return await council_mod.DeliveryCouncil().run("r1", "p", "general", RESULTS)


@pytest.mark.asyncio
async def test_timeout_is_needs_review_not_a_pass(monkeypatch):
    async def hang():
        await asyncio.sleep(10)
    monkeypatch.setattr(council_mod, "_COUNCIL_TIMEOUT_S", 0.05)
    _patch(monkeypatch, _Client(hang))
    res = await _run()
    assert res["passed"] is False and res["status"] == "needs_review" and "timed out" in res["reason"]


@pytest.mark.asyncio
async def test_llm_error_is_needs_review(monkeypatch):
    async def boom():
        raise RuntimeError("provider down")
    _patch(monkeypatch, _Client(boom))
    res = await _run()
    assert res["passed"] is False and res["status"] == "needs_review" and "RuntimeError" in res["reason"]


@pytest.mark.asyncio
async def test_unparseable_reply_is_not_a_pass_and_prompt_has_evidence(monkeypatch):
    async def junk():
        return "not json"
    client = _Client(junk)
    _patch(monkeypatch, client)
    res = await _run()
    assert res["passed"] is False
    assert "SQL injection in /x" in client.prompt and "app never became healthy" in client.prompt
