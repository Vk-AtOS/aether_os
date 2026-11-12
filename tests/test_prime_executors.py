"""Prime executors: exactly-once execution, the webhook and the run-gate executor.

Fixtures (svc, counting) are imported from tests/prime_helpers.py."""
# ruff: noqa: F811  (a fixture imported by name and then requested as an argument)
from __future__ import annotations

import asyncio
from decimal import Decimal
import hashlib
import hmac
import json

import httpx
import pytest
import pytest_asyncio

from aether_os.core import pipeline_state
from aether_os.core.audit import chain
import aether_os.core.db as db
from aether_os.core.encryption import encrypt
from aether_os.core.models import Run, Webhook
from aether_os.core.security import safe_http
from aether_os.prime import approvals, AutonomyLevel, executors
from aether_os.prime.approvals import RequestError
from aether_os.tests.prime_helpers import (  # noqa: F401  (svc and counting are fixtures)
    act, actions, ALICE, BOB, BOB_IDS, counting, grant, ORG, OTHER_ORG, set_row, svc,
)

pytestmark = pytest.mark.asyncio


# ── execution: exactly once ───────────────────────────────────────────────────

async def test_level4_executes_once_without_a_person(svc, counting):
    await grant(AutonomyLevel.ACT_SILENTLY)
    out = await svc.submit(act(), ORG, "counting")
    req = out["request"]
    assert out["outcome"] == "EXECUTE" and req["state"] == "approved" and req["decided_by"] == "prime"
    assert req["execution"]["status"] == "succeeded" and len(counting.calls) == 1
    await svc._execute(req["id"])
    await asyncio.gather(*[svc._execute(req["id"]) for _ in range(5)])
    assert len(counting.calls) == 1
    assert (await actions()).count("prime.execution.result") == 1


async def test_concurrent_approvals_execute_once(svc, counting):
    await grant()
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    results = await asyncio.gather(
        *[svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True) for _ in range(4)],
        svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=True),
        return_exceptions=True)
    assert len(counting.calls) == 1
    assert any(isinstance(r, dict) and r["state"] == "approved" for r in results)


async def test_unknown_executor_is_refused(svc, counting, monkeypatch):
    await grant()
    with pytest.raises(RequestError) as e:
        await svc.submit(act(), ORG, "no-such-executor")
    assert e.value.status == 400 and await actions() == ["prime.delegation.grant"]

    req = (await svc.submit(act(), ORG, "counting"))["request"]
    monkeypatch.delitem(executors.REGISTRY, "counting")
    seen = await svc.get(req["id"], BOB, BOB_IDS, ORG)
    assert not seen["can_approve"] and "unknown executor" in seen["what_will_happen"]
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert e.value.status == 409 and counting.calls == []


@pytest.mark.parametrize("raised,status", [
    (executors.ExecutionFailed("endpoint said no"), "failed"),
    (RuntimeError("connection dropped token=sk-ant-REDACTME1234567890"), "needs_attention"),
])
async def test_failure_is_ledgered_and_never_retried(svc, counting, raised, status):
    counting.raises = raised
    await grant()
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    done = await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert done["state"] == "approved" and done["execution"]["status"] == status
    last = (await chain.read_entries())[-1]
    assert last["action"] == "prime.execution.result" and last["payload"]["execution"] == status
    again = await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    await svc._execute(req["id"])
    assert again["execution"]["status"] == status and len(counting.calls) == 1


async def test_crash_mid_execution_leaves_needs_attention_not_a_retry(svc, counting):
    counting.raises = asyncio.CancelledError()   # the process dying inside the executor
    await grant()
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    with pytest.raises(asyncio.CancelledError):
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    counting.raises = None
    assert (await svc.get(req["id"], BOB, BOB_IDS, ORG))["execution"]["status"] == "running"
    await set_row(req["id"], exec_started_at=approvals._now() - approvals.EXECUTION_STALE_AFTER * 2)
    seen = await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    await svc._execute(req["id"])
    assert seen["execution"]["status"] == "needs_attention" and len(counting.calls) == 1
    assert (await actions())[-1] == "prime.execution.start"   # no result was ever claimed


async def test_dry_run_is_the_default_and_does_nothing(svc):
    await grant(AutonomyLevel.ACT_THEN_NOTIFY)
    req = (await svc.submit(act(), ORG))["request"]
    assert req["executor"] == "dry_run" == executors.DEFAULT_EXECUTOR
    assert req["execution"] == {"status": "succeeded", "result": {"dry_run": True, "action_type": "leave.approve"},
                                "idempotency_key": f"prime-{req['request_hash']}"}
    assert "nothing is carried out" in req["what_will_happen"]


# ── webhook executor ──────────────────────────────────────────────────────────

SECRET = "s3cret-signing-key"


@pytest_asyncio.fixture
async def hook(svc, monkeypatch):
    """An org webhook subscribed to prime.execute, and a fake endpoint behind it."""
    sent, answer = [], {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if isinstance(answer["status"], Exception):
            raise answer["status"]
        return httpx.Response(answer["status"])

    async def fake_safe_request(method, url, *, timeout=10.0, **kw):
        # stands in for core.security.safe_http.safe_request (DNS + pinning are tested there)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout) as c:
            return await c.request(method, url, **kw)
    monkeypatch.setattr(executors, "safe_request", fake_safe_request)
    async with db.get_session_factory()() as s:
        s.add_all([
            Webhook(id="wh-ok", org_id=ORG, url="https://erp.example.test/prime",
                    events=["prime.execute"], secret=encrypt(SECRET)),
            Webhook(id="wh-all", org_id=ORG, url="https://x.example.test", events=["*"], secret=encrypt(SECRET)),
            Webhook(id="wh-other", org_id=OTHER_ORG, url="https://y.example.test",
                    events=["prime.execute"], secret=encrypt(SECRET)),
            Webhook(id="wh-nokey", org_id=ORG, url="https://z.example.test",
                    events=["prime.execute"], secret="not-a-ciphertext"),
        ])
        await s.commit()
    await grant(AutonomyLevel.ACT_SILENTLY)
    return sent, answer


async def pay(svc, webhook_id):
    out = await svc.submit(act("invoice.approve", amount=Decimal("500"), currency="INR",
                               params={"webhook_id": webhook_id, "invoice": "INV-7"}), ORG, "webhook")
    req = out["request"]   # an external effect is never auto-approved: the deputy approves
    assert out["outcome"] == "NEEDS_APPROVAL" and req["state"] == "pending"
    return await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)


async def test_webhook_executor_sends_one_signed_message(svc, hook):
    sent, _ = hook
    req = await pay(svc, "wh-ok")
    assert req["execution"]["status"] == "succeeded" and len(sent) == 1
    assert "https://erp.example.test/prime" in req["what_will_happen"]
    r = sent[0]
    key = f"prime-{req['request_hash']}"
    assert str(r.url) == "https://erp.example.test/prime" and r.method == "POST"
    assert r.headers["Idempotency-Key"] == key == r.headers["X-AetherOS-Delivery"]
    expected = hmac.new(SECRET.encode(), r.content, hashlib.sha256).hexdigest()
    assert r.headers["X-AetherOS-Signature-256"] == f"sha256={expected}"
    body = json.loads(r.content)
    assert body["event"] == "prime.execute" and body["id"] == key
    assert body["payload"]["type"] == "invoice.approve" and body["payload"]["amount"] == "500"
    assert body["payload"]["params"]["invoice"] == "INV-7" and body["payload"]["approved_by"] == BOB
    assert SECRET not in json.dumps(await chain.read_entries())


@pytest.mark.parametrize("webhook_id", ["wh-all", "wh-other", "wh-nokey", "missing", None])
async def test_webhook_executor_refuses_endpoints_not_allow_listed(svc, hook, webhook_id):
    sent, _ = hook
    req = await pay(svc, webhook_id)
    assert req["execution"]["status"] == "failed" and sent == []


@pytest.mark.parametrize("answer,status", [
    (400, "failed"), (404, "failed"), (500, "needs_attention"), (302, "needs_attention"),
    (httpx.ReadTimeout("slow"), "needs_attention"), (httpx.ConnectError("refused"), "failed"),
])
async def test_webhook_executor_never_retries(svc, hook, answer, status):
    sent, reply = hook
    reply["status"] = answer
    req = await pay(svc, "wh-ok")
    assert req["execution"]["status"] == status and len(sent) == 1
    await svc._execute(req["id"])
    assert len(sent) == 1


async def test_webhook_executor_uses_the_ssrf_check(svc, hook, monkeypatch):
    sent, _ = hook
    monkeypatch.setattr(executors, "safe_request", safe_http.safe_request)  # the real pinned check
    async with db.get_session_factory()() as s:
        s.add(Webhook(id="wh-local", org_id=ORG, url="http://127.0.0.1:9/x",
                      events=["prime.execute"], secret=encrypt(SECRET)))
        await s.commit()
    req = await pay(svc, "wh-local")
    assert req["execution"]["status"] == "failed" and sent == []
    assert "address refused" in req["execution"]["result"]["error"]


# ── internal executor: the specification review gate ──────────────────────────

async def test_run_gate_executor_releases_only_a_waiting_run_of_the_same_org(svc):
    await grant()
    async with db.get_session_factory()() as s:
        s.add_all([Run(id="run-1", org_id=ORG), Run(id="run-2", org_id=ORG), Run(id="run-x", org_id=OTHER_ORG)])
        await s.commit()
    for run_id in ("run-1", "run-x"):
        await pipeline_state.set_control(run_id, "spec_review")
    await pipeline_state.set_control("run-2", "running")

    async def approve(params, type_="run.spec.approve"):
        req = (await svc.submit(act(type_, params=params), ORG, "aetheros.run_gate"))["request"]
        return await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)

    ok = await approve({"run_id": "run-1"})
    assert "run-1" in ok["what_will_happen"] and ok["execution"]["status"] == "succeeded"
    assert await pipeline_state.get_control("run-1") == "spec_approved"

    for params, type_ in (({"run_id": "run-2"}, "run.spec.approve"),    # not at the gate
                          ({"run_id": "run-x"}, "run.spec.approve"),    # another organisation's
                          ({"run_id": "nope"}, "run.spec.approve"),
                          ({}, "run.spec.approve"),
                          ({"run_id": "run-1"}, "leave.approve")):       # wrong action for this executor
        assert (await approve(params, type_))["execution"]["status"] == "failed"
    assert await pipeline_state.get_control("run-2") == "running"
    assert await pipeline_state.get_control("run-x") == "spec_review"


async def test_repeat_approval_starts_an_execution_that_was_never_claimed(svc, counting):
    await grant()
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    # The first approval was stored, then the process died before execution began.
    await set_row(req["id"], status="approved", decided_by=BOB, decided_hash=req["request_hash"])
    for _ in range(2):
        done = await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert done["execution"]["status"] == "succeeded" and len(counting.calls) == 1
