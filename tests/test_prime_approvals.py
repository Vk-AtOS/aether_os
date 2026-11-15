"""Prime approval inbox: who sees and decides what, over the service and over HTTP.

Fixtures (svc, counting) are imported from tests/prime_helpers.py."""
# ruff: noqa: F811  (a fixture imported by name and then requested as an argument)
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
import httpx
from pydantic import ValidationError
import pytest

from aether_os.core.audit import chain
from aether_os.gateway.routers import prime_inbox_router as inbox_api
from aether_os.gateway.routers import prime_ledger_router as ledger_api
from aether_os.gateway.routers import prime_router as prime_api
from aether_os.prime import approvals, AutonomyLevel, DelegationRepository
from aether_os.prime.approvals import RequestError
from aether_os.tests.prime_helpers import (  # noqa: F401  (svc and counting are fixtures)
    act, actions, ADMIN, ALICE, API_KEY, BOB, BOB_IDS, CAROL, counting, DEPUTY, grant, MALLORY, MEMBER, ORG, OWNER, OTHER_ORG, OUTSIDER, set_row, svc, SYSTEM,
)

pytestmark = pytest.mark.asyncio


# ── inbox, approve, reject ────────────────────────────────────────────────────

async def test_approval_flow_quotes_the_hash_is_idempotent_and_ledgered(svc, counting):
    d = await grant()
    out = await svc.submit(act("invoice.approve", amount=Decimal("250"), currency="INR"), ORG, "counting")
    req = out["request"]
    assert out["outcome"] == "NEEDS_APPROVAL" and req["state"] == "pending"
    assert req["action"] == {"type": "invoice.approve", "on_behalf_of": ALICE, "requested_by": SYSTEM,
                             "amount": "250", "currency": "INR", "params": {}}
    assert req["expires_at"] and req["execution"] is None and counting.calls == []

    # Owner and the active deputy see it; nobody else does.
    for uid, ids in ((ALICE, [ALICE]), (BOB, BOB_IDS)):
        page = await svc.inbox(uid, ids, ORG)
        assert [r["id"] for r in page["requests"]] == [req["id"]] and page["total"] == 1
        assert page["requests"][0]["can_approve"]
    assert (await svc.inbox(CAROL, [CAROL], ORG))["total"] == 0
    assert (await svc.inbox(BOB, BOB_IDS, OTHER_ORG))["total"] == 0
    with pytest.raises(RequestError) as e:
        await svc.get(req["id"], CAROL, [CAROL], ORG)
    assert e.value.status == 404

    with pytest.raises(RequestError) as e:      # a hash that is not the one shown
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, "0" * 64, approve=True)
    assert e.value.status == 409 and counting.calls == []

    done = await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True, reason="ok")
    assert done["state"] == "approved" and done["decided_by"] == BOB and done["decision_reason"] == "ok"
    assert done["execution"]["status"] == "succeeded" and done["execution"]["result"] == {"done": True}
    assert len(counting.calls) == 1
    assert counting.calls[0].idempotency_key == f"prime-{req['request_hash']}"
    assert counting.calls[0].approved_by == BOB

    before = await actions()
    again = await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert again["state"] == "approved" and len(counting.calls) == 1 and await actions() == before
    for uid, ids, approve in ((BOB, BOB_IDS, False), (ALICE, [ALICE], True)):
        with pytest.raises(RequestError) as e:  # a different answer, or a different person
            await svc.decide(req["id"], uid, ids, ORG, req["request_hash"], approve=approve)
        assert e.value.status == 409
    assert len(counting.calls) == 1

    assert before == ["prime.delegation.grant", "prime.request", "prime.decision",
                      "prime.approval.request", "prime.approval.decision",
                      "prime.execution.start", "prime.execution.result"]
    entries = await chain.read_entries()
    decision, result = entries[4], entries[6]
    assert decision["actor"] == BOB and decision["payload"]["status"] == "approved"
    assert decision["payload"]["request_hash"] == req["request_hash"]
    assert decision["payload"]["delegation_id"] == d.id and decision["payload"]["org_id"] == ORG
    assert result["payload"]["execution"] == "succeeded"
    assert (await chain.verify()).ok
    assert (await svc.inbox(BOB, BOB_IDS, ORG, state="pending"))["total"] == 0
    assert (await svc.inbox(BOB, BOB_IDS, ORG, state="decided"))["total"] == 1


async def test_nobody_approves_their_own_request(svc, counting):
    await grant()
    mine = (await svc.submit(act(requested_by=ALICE), ORG, "counting"))["request"]
    assert not (await svc.get(mine["id"], ALICE, [ALICE], ORG))["can_decide"]
    for approve in (True, False):
        with pytest.raises(RequestError) as e:
            await svc.decide(mine["id"], ALICE, [ALICE], ORG, mine["request_hash"], approve=approve)
        assert e.value.status == 403
    # Also when the request was made under the deputy's email identity.
    theirs = (await svc.submit(act(requested_by="bob@a.test"), ORG, "counting"))["request"]
    with pytest.raises(RequestError) as e:
        await svc.decide(theirs["id"], BOB, BOB_IDS, ORG, theirs["request_hash"], approve=True)
    assert e.value.status == 403 and counting.calls == []


async def test_reject_is_recorded_and_runs_nothing(svc, counting):
    await grant()
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    done = await svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=False, reason="no")
    assert done["state"] == "rejected" and done["execution"] is None and counting.calls == []
    assert (await chain.read_entries())[-1]["payload"]["status"] == "rejected"
    with pytest.raises(RequestError):
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert counting.calls == []


async def test_expired_request_is_not_approved(svc, counting):
    await grant()
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    # expires_at is part of the hash, so move the clock instead of editing the row.
    real_now = approvals._now
    approvals._now = lambda: real_now() + approvals.REQUEST_TTL + timedelta(days=3)
    try:
        assert (await svc.inbox(ALICE, [ALICE], ORG, state="pending"))["total"] == 0
        page = await svc.inbox(ALICE, [ALICE], ORG, state="expired")
        assert page["requests"][0]["state"] == "expired" and not page["requests"][0]["can_decide"]
        with pytest.raises(RequestError) as e:
            await svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=True)
        assert e.value.status == 409 and "expired" in str(e.value)
    finally:
        approvals._now = real_now
    assert counting.calls == []


async def test_request_expires_no_later_than_its_delegation(svc):
    d = await grant(valid_until=datetime.now(timezone.utc) + timedelta(hours=2))
    req = (await svc.submit(act(), ORG))["request"]
    assert datetime.fromisoformat(req["expires_at"]) == d.valid_until


async def test_revoked_delegation_removes_the_deputy_and_blocks_approval(svc, counting):
    d = await grant()
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    await DelegationRepository().revoke(d.id, by=ALICE, now=datetime.now(timezone.utc), org_id=ORG)
    assert (await svc.inbox(BOB, BOB_IDS, ORG))["total"] == 0
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert e.value.status == 404
    with pytest.raises(RequestError) as e:      # the owner cannot approve past a revocation either
        await svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=True)
    assert e.value.status == 409 and "revoked" in str(e.value) and counting.calls == []
    done = await svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=False)
    assert done["state"] == "rejected"


async def test_same_identity_in_another_org_sees_nothing(svc, counting):
    await grant(deputy=MALLORY)
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    assert (await svc.inbox(MALLORY, [MALLORY], OTHER_ORG))["total"] == 0
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], MALLORY, [MALLORY], OTHER_ORG, req["request_hash"], approve=True)
    assert e.value.status == 404 and counting.calls == []


async def test_edited_request_matches_no_approval(svc, counting):
    await grant()
    req = (await svc.submit(act("invoice.approve", amount=Decimal("10"), currency="INR"), ORG, "counting"))["request"]
    await set_row(req["id"], amount="999")
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert e.value.status == 409 and counting.calls == []


async def test_edit_after_approval_is_refused_at_execution(svc, counting):
    await grant()
    req = (await svc.submit(act(), ORG, "counting"))["request"]
    await set_row(req["id"], status="approved", decided_by=BOB, decided_hash=req["request_hash"],
                  params={"swapped": True})
    await svc._execute(req["id"])
    seen = await svc.get(req["id"], ALICE, [ALICE], ORG)
    assert seen["execution"]["status"] == "failed" and counting.calls == []
    assert "no longer matches" in seen["execution"]["result"]["error"]
    assert (await chain.read_entries())[-1]["payload"]["execution"] == "failed"


async def test_refused_and_recommend_only_create_no_request(svc):
    out = await svc.submit(act("person.terminate"), ORG)
    assert out["outcome"] == "REFUSE" and out["request"] is None
    await grant(AutonomyLevel.RECOMMEND)
    out = await svc.submit(act(), ORG)
    assert out["outcome"] == "RECOMMEND_ONLY" and out["request"] is None
    assert (await svc.inbox(ALICE, [ALICE], ORG, state="all"))["total"] == 0


async def test_out_of_scope_goes_to_the_deputy_inbox(svc, counting):
    await grant(scope={"leave.approve"})
    out = await svc.submit(act("deploy.staging"), ORG, "counting")
    assert out["outcome"] == "ROUTE_TO_DEPUTY" and out["request"]["state"] == "pending"
    page = await svc.inbox(BOB, BOB_IDS, ORG)
    assert page["requests"][0]["action"]["type"] == "deploy.staging"


async def test_pending_first_and_pagination(svc, counting):
    await grant()
    ids = [(await svc.submit(act(params={"n": n}), ORG, "counting"))["request"] for n in range(5)]
    await svc.decide(ids[4]["id"], BOB, BOB_IDS, ORG, ids[4]["request_hash"], approve=False)
    page = await svc.inbox(BOB, BOB_IDS, ORG, state="all", limit=2)
    assert page["total"] == 5 and all(r["state"] == "pending" for r in page["requests"])
    seen = []
    for offset in (0, 2, 4):
        seen += (await svc.inbox(BOB, BOB_IDS, ORG, state="all", limit=2, offset=offset))["requests"]
    assert len({r["id"] for r in seen}) == 5 and seen[-1]["state"] == "rejected"


# ── HTTP layer: who may ask, see and decide ───────────────────────────────────

async def test_router_submit_inbox_decide_and_deputies(svc):
    now = datetime.now(timezone.utc)
    created = await prime_api.create_delegation(prime_api.DelegationIn(
        scope=["leave.approve"], autonomy=2, valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(days=2), deputy="bob@a.test"), user=OWNER)

    for bad_user, body in ((OWNER, inbox_api.RequestIn(type="leave.approve", on_behalf_of=BOB)),
                           (API_KEY, inbox_api.RequestIn(type="leave.approve")),
                           (API_KEY, inbox_api.RequestIn(type="leave.approve", on_behalf_of=MALLORY))):
        with pytest.raises(HTTPException) as e:
            await inbox_api.submit_request(body, user=bad_user)
        assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await inbox_api.submit_request(inbox_api.RequestIn(type="leave.approve", executor="nope"), user=OWNER)
    assert e.value.status_code == 400
    with pytest.raises(ValidationError):
        inbox_api.RequestIn(type="leave.approve", params={"blob": "x" * 9000})

    out = await inbox_api.submit_request(
        inbox_api.RequestIn(type="leave.approve", on_behalf_of=ALICE, params={"days": 2}), user=API_KEY)
    req = out["request"]
    assert req["action"]["requested_by"] == "system:api_key" and req["state"] == "pending"

    assert (await inbox_api.inbox(user=DEPUTY, state="pending", limit=50, offset=0))["total"] == 1
    assert (await inbox_api.inbox(user=ADMIN, state="all", limit=50, offset=0))["total"] == 0  # admin is no approver
    for who, code in ((OUTSIDER, 404), (ADMIN, 404), (API_KEY, 403)):
        with pytest.raises(HTTPException) as e:
            await inbox_api.approve_request(req["id"], inbox_api.DecisionIn(request_hash=req["request_hash"]), user=who)
        assert e.value.status_code == code
    with pytest.raises(HTTPException) as e:
        await inbox_api.approve_request(req["id"], inbox_api.DecisionIn(request_hash="f" * 64), user=DEPUTY)
    assert e.value.status_code == 409
    done = await inbox_api.approve_request(
        req["id"], inbox_api.DecisionIn(request_hash=req["request_hash"], reason="fine"), user=DEPUTY)
    assert done["state"] == "approved" and done["execution"]["status"] == "succeeded"
    assert (await inbox_api.get_request(req["id"], user=OWNER))["decided_by"] == BOB

    mine = await inbox_api.deputies(user=OWNER)
    assert [d["id"] for d in mine["given"]] == [created["id"]] and mine["received"] == []
    did = [(e["action"], e["actor"]) for e in mine["given"][0]["activity"]]
    assert ("prime.approval.decision", BOB) in did and ("prime.execution.result", "prime") in did
    theirs = await inbox_api.deputies(user=DEPUTY)
    assert theirs["given"] == [] and theirs["received"][0]["grantor"] == ALICE
    assert {e["actor"] for e in theirs["received"][0]["activity"]} == {BOB}
    assert (await inbox_api.deputies(user=ADMIN)) == {"given": [], "received": []}

    await prime_api.revoke_delegation(created["id"], user=OWNER)
    assert (await inbox_api.deputies(user=DEPUTY))["received"][0]["state"] == "revoked"


async def test_deputy_named_from_another_org_is_not_shown_the_delegation(svc):
    await grant(deputy="mallory@b.test")
    assert (await inbox_api.deputies(user=OUTSIDER))["received"] == []


# ── over real HTTP (FastAPI parsing and JSON), identity injected ──────────────

async def test_endpoints_over_http(svc):
    from fastapi import FastAPI
    from aether_os.gateway.dependencies import get_current_user

    who = {"user": OWNER}
    app = FastAPI()
    for module in (prime_api, inbox_api, ledger_api):
        app.include_router(module.router)
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
        r = await http.post("/prime/delegations", json={
            "scope": ["invoice.approve"], "autonomy": 2, "deputy": "bob@a.test", "max_amount": "900",
            "valid_from": (now - timedelta(minutes=1)).isoformat(),
            "valid_until": (now + timedelta(days=3)).isoformat()})
        assert r.status_code == 201
        r = await http.post("/prime/requests", json={"type": "invoice.approve", "amount": "120.50",
                                                     "params": {"invoice": "INV-1"}})
        assert r.status_code == 201
        req = r.json()["request"]
        assert req["action"]["amount"] == "120.50" and req["state"] == "pending"

        assert (await http.get("/prime/inbox", params={"state": "bogus"})).status_code == 422
        assert (await http.get("/prime/inbox", params={"limit": 500})).status_code == 422
        assert (await http.post(f"/prime/requests/{req['id']}/approve", json={})).status_code == 422
        assert (await http.post(f"/prime/requests/{req['id']}/approve",
                                json={"request_hash": req["request_hash"]})).status_code == 403  # own request

        who["user"] = DEPUTY
        page = (await http.get("/prime/inbox")).json()
        assert page["total"] == 1 and page["requests"][0]["id"] == req["id"]
        r = await http.post(f"/prime/requests/{req['id']}/approve",
                            json={"request_hash": req["request_hash"], "reason": "checked"})
        assert r.status_code == 200 and r.json()["execution"]["status"] == "succeeded"
        assert (await http.get("/prime/deputies")).json()["received"][0]["activity"]
        who["user"] = MEMBER   # not an organisation admin
        assert (await http.put("/prime/limits", json={"payment_ceiling": 1, "max_delegation_days": 1})).status_code == 403

        who["user"] = ADMIN
        assert (await http.put("/prime/limits", json={"payment_ceiling": "750000", "max_delegation_days": 45, "request_ttl_hours": 72})).json() == {
            "payment_ceiling": "750000", "max_delegation_days": 45, "request_ttl_hours": 72}
        assert (await http.put("/prime/limits", json={"payment_ceiling": "99999999", "max_delegation_days": 45})).status_code == 400
        page = (await http.get("/prime/ledger/entries", params={
            "event": "prime.approval", "since": (now - timedelta(hours=1)).isoformat(), "limit": 1})).json()
        assert page["whole_org"] and len(page["entries"]) == 1 and page["next_before"]
        older = (await http.get("/prime/ledger/entries", params={
            "event": "prime.approval", "before": page["next_before"]})).json()
        # The owner's refused attempt to approve her own request is ledgered too.
        assert [e["action"] for e in older["entries"]] == ["prime.approval.refuse", "prime.approval.request"]
        one = (await http.get(f"/prime/ledger/entries/{page['entries'][0]['seq']}")).json()
        assert one["link_ok"] and one["hash_ok"] and one["action"] == "prime.approval.decision"
        assert (await http.get("/prime/ledger/verify")).json()["ok"]
        assert "aetheros.run_gate" in (await http.get("/prime/meta")).json()["executors"]


async def test_decision_cannot_land_on_a_request_changed_after_it_was_read(svc, counting, monkeypatch):
    """Root cause (KAN-22 race): the decision UPDATE matched on status only, so a request whose
    hash changed between the read and the write was still marked approved with the OLD hash."""
    await grant()
    req = (await svc.submit(act("invoice.approve", amount=Decimal("250"), currency="INR"), ORG,
                            "counting"))["request"]
    real = approvals.audit_chain.append

    async def append(*a, **kw):
        out = await real(*a, **kw)
        if kw.get("action") == "prime.approval.decision":
            await set_row(req["id"], request_hash="f" * 64)     # someone changed the request meanwhile
        return out
    monkeypatch.setattr(approvals.audit_chain, "append", append)
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert e.value.status == 409
    monkeypatch.setattr(approvals.audit_chain, "append", real)
    row = await svc._load(req["id"])
    assert row.status == "pending" and row.decided_by is None and counting.calls == []
