"""KAN-22: edit-before-approve. The approval stays bound to what the approver saw."""
# ruff: noqa: F811
from __future__ import annotations

from decimal import Decimal

import pytest

from aether_os.core.audit import chain
from aether_os.prime import approvals
from aether_os.prime.approvals import RequestError
from aether_os.prime.edits import edit_request
from aether_os.tests.prime_helpers import (  # noqa: F401
    act, ALICE, BOB, BOB_IDS, counting, grant, ORG, set_row, svc,
)

pytestmark = pytest.mark.asyncio


async def _invoice(svc):
    await grant()
    return (await svc.submit(act("invoice.approve", amount=Decimal("250"), currency="INR",
                                 params={"note": "march"}), ORG, "counting"))["request"]


async def _edit(svc, req, uid=BOB, ids=BOB_IDS, **kw):
    return await edit_request(svc, req["id"], uid, ids, ORG, kw.pop("hash", req["request_hash"]),
                              kw.pop("reason", "typo in amount"), **kw)


async def test_edit_makes_a_new_revision_and_the_old_hash_can_no_longer_be_approved(svc, counting):
    req = await _invoice(svc)
    out = await _edit(svc, req, amount=Decimal("300"))
    assert out["revision"] == 1 and out["approvals_reset"] and out["action"]["amount"] == "300"
    assert out["request_hash"] != req["request_hash"] and out["edited_by"] == [BOB]
    with pytest.raises(RequestError) as e:                      # an approval of the old content
        await svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=True)
    assert e.value.status == 409 and counting.calls == []
    done = await svc.decide(req["id"], ALICE, [ALICE], ORG, out["request_hash"], approve=True)
    assert done["state"] == "approved" and counting.calls[0].action.amount == Decimal("300")


async def test_the_editor_cannot_be_the_sole_approver_of_their_own_edit(svc, counting):
    req = await _invoice(svc)
    out = await _edit(svc, req, params={"note": "april"})
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, out["request_hash"], approve=True)
    assert e.value.status == 403 and "edited" in str(e.value) and counting.calls == []
    # the defence also holds at execution: a row approved by its editor does not run
    await set_row(req["id"], status="approved", decided_by=BOB, decided_hash=out["request_hash"])
    await svc._execute(req["id"])
    assert counting.calls == [] and (await svc._load(req["id"])).exec_status == "failed"


async def test_external_effect_still_needs_someone_other_than_requester_and_grantor(svc, counting, monkeypatch):
    monkeypatch.setattr(approvals, "EXTERNAL_EFFECT", frozenset({"counting"}))
    req = await _invoice(svc)
    out = await _edit(svc, req, amount=Decimal("260"))
    with pytest.raises(RequestError) as e:                      # the person it is for cannot approve
        await svc.decide(req["id"], ALICE, [ALICE], ORG, out["request_hash"], approve=True)
    assert e.value.status == 409 and counting.calls == []


async def test_edit_that_breaks_a_limit_or_the_schema_is_refused(svc, counting):
    req = await _invoice(svc)
    with pytest.raises(RequestError) as e:
        await _edit(svc, req, amount=Decimal("5000"))           # delegated limit is 1000
    assert e.value.status == 409 and "limit" in str(e.value)
    with pytest.raises(RequestError) as e:
        await _edit(svc, req, params={"webhook_id": "x"})       # not an editable field
    assert e.value.status == 422
    with pytest.raises(RequestError) as e:
        await _edit(svc, req, reason="  ")
    assert e.value.status == 422
    with pytest.raises(RequestError) as e:
        await _edit(svc, req)                                   # nothing changed
    assert e.value.status == 422
    assert (await svc._load(req["id"])).revision == 0


async def test_edit_needs_authority_visibility_and_the_hash_that_was_shown(svc, counting):
    req = await _invoice(svc)
    with pytest.raises(RequestError) as e:
        await _edit(svc, req, hash="0" * 64, amount=Decimal("260"))
    assert e.value.status == 409
    with pytest.raises(RequestError) as e:                      # carol is not owner or deputy
        await _edit(svc, req, uid="carol", ids=["carol"], amount=Decimal("260"))
    assert e.value.status == 404
    await svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=True)
    with pytest.raises(RequestError) as e:                      # no longer pending
        await _edit(svc, req, amount=Decimal("260"))
    assert e.value.status == 409


async def test_edit_is_in_the_ledger_with_who_before_after_and_reason(svc, counting):
    req = await _invoice(svc)
    await _edit(svc, req, amount=Decimal("300"), params={"note": "april"}, reason="wrong month")
    e = next(x for x in await chain.read_entries(limit=100) if x["action"] == "prime.approval.edit")
    assert e["actor"] == BOB and e["payload"]["reason"] == "wrong month"
    assert e["payload"]["changes"]["before"] == {"amount": "250", "params": {"note": "march"}}
    assert e["payload"]["changes"]["after"] == {"amount": "300", "params": {"note": "april"}}
    assert e["payload"]["old_hash"] == req["request_hash"]
    shown = (await svc.get(req["id"], ALICE, [ALICE], ORG))["detail"]["ledger"]
    assert any(x["action"] == "prime.approval.edit" and x["changes"] for x in shown)


async def test_edit_and_approve_race_has_exactly_one_winner_and_never_a_stale_approval(svc, counting, monkeypatch):
    real = approvals.audit_chain.append
    req = await _invoice(svc)

    async def edit_during_decision(*a, **kw):                   # the edit lands between read and write
        out = await real(*a, **kw)
        if kw.get("action") == "prime.approval.decision":
            monkeypatch.setattr(approvals.audit_chain, "append", real)
            await _edit(svc, req, amount=Decimal("300"))
        return out
    monkeypatch.setattr(approvals.audit_chain, "append", edit_during_decision)
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=True)
    assert e.value.status == 409
    row = await svc._load(req["id"])
    assert row.status == "pending" and row.revision == 1 and counting.calls == []

    async def decide_during_edit(*a, **kw):                     # the decision lands between read and write
        out = await real(*a, **kw)
        if kw.get("action") == "prime.approval.edit":
            await set_row(req["id"], status="approved", decided_by=ALICE)
        return out
    cur = await svc._load(req["id"])
    monkeypatch.setattr(approvals.audit_chain, "append", decide_during_edit)
    with pytest.raises(RequestError) as e:
        await _edit(svc, {"id": req["id"], "request_hash": cur.request_hash}, amount=Decimal("310"))
    assert e.value.status == 409
    assert (await svc._load(req["id"])).amount == "300"        # the losing edit changed nothing
