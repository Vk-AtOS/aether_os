"""Prime: authority by organisation role, no self-execution of money or external
effects, and INR-only amounts. Regression tests for the two HIGH findings.

Fixtures (svc, counting) are imported from tests/prime_helpers.py."""
# ruff: noqa: F811  (a fixture imported by name and then requested as an argument)
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from sqlalchemy import update

import aether_os.core.db as db
from aether_os.core.audit import chain
from aether_os.core.models import User
from aether_os.gateway.routers import prime_inbox_router as inbox_api
from aether_os.gateway.routers import prime_router as prime_api
from aether_os.prime import executors
from aether_os.prime.authz import PRIME
from aether_os.prime import Action, AutonomyLevel, Delegation, Limits, Outcome, authorize
from aether_os.prime.approvals import RequestError, compute_hash
from aether_os.prime.models import PrimeDelegation, PrimeRequest
from aether_os.prime.repository import _naive_utc
from aether_os.tests.prime_helpers import (  # noqa: F401  (svc and counting are fixtures)
    act, ALICE, API_KEY, BOB, BOB_IDS, counting, DAVE, grant, MEMBER, ORG, set_row, SYSTEM, svc,
)

pytestmark = pytest.mark.asyncio
DAVE_IDS = [DAVE, "dave@a.test"]


async def set_role(uid: str, role: str) -> None:
    async with db.get_session_factory()() as s:
        await s.execute(update(User).where(User.id == uid).values(role=role))
        await s.commit()


async def last(action: str) -> dict:
    return [e for e in await chain.read_entries(limit=1000) if e["action"] == action][-1]


async def load(request_id: str) -> PrimeRequest:
    async with db.get_session_factory()() as s:
        return await s.get(PrimeRequest, request_id)


# ── finding 1: authority before org-affecting actions ─────────────────────────

async def test_a_member_cannot_delegate_what_their_role_does_not_hold(svc):
    now = datetime.now(timezone.utc)
    body = prime_api.DelegationIn(scope=["invoice.approve"], autonomy=4, valid_from=now,
                                  valid_until=now + timedelta(days=2), deputy="bob@a.test",
                                  max_amount=Decimal("100"))
    with pytest.raises(HTTPException) as e:
        await prime_api.create_delegation(body, user=MEMBER)
    assert e.value.status_code == 403 and "do not hold" in e.value.detail
    refused = await last("prime.delegation.refuse")
    assert refused["actor"] == DAVE and refused["payload"]["authority"][0]["ok"] is False
    assert refused["payload"]["authority"][0]["role"] == "member"
    assert (await prime_api.list_delegations(user=MEMBER))["delegations"] == []

    # What a member does hold (the run gate) can be delegated, and the grant records why.
    ok = await prime_api.create_delegation(body.model_copy(update={
        "scope": ["run.spec.approve"], "max_amount": None}), user=MEMBER)
    assert ok["state"] == "active"
    assert (await last("prime.delegation.grant"))["payload"]["authority"][0]["ok"] is True


async def test_api_key_gets_no_authority_the_member_lacks(svc, counting):
    # A delegation stored before the authority rule existed (or written around it).
    now = datetime.now(timezone.utc)
    async with db.get_session_factory()() as s:
        s.add(PrimeDelegation(id="old", grantor=DAVE, deputy="bob@a.test", scope=["invoice.approve"],
                              max_amount="1000", currency="INR", autonomy=4,
                              valid_from=_naive_utc(now - timedelta(hours=1)),
                              valid_until=_naive_utc(now + timedelta(days=1))))
        await s.commit()
    out = await inbox_api.submit_request(inbox_api.RequestIn(
        type="invoice.approve", amount=Decimal("10"), on_behalf_of=DAVE), user=API_KEY)
    assert out["outcome"] == "REFUSE" and "holds no authority" in out["reason"]
    assert out["request"] is None and counting.calls == []
    logged = await last("prime.decision")
    assert logged["payload"]["authority"] == {"person": DAVE, "role": "member", "executor": "dry_run",
                                              "ok": False, "reason": logged["payload"]["authority"]["reason"]}


async def test_member_cannot_reach_the_webhook_executor(svc):
    await grant(grantor=DAVE, scope={"run.spec.approve"}, limits=None, autonomy=AutonomyLevel.ACT_SILENTLY)
    out = await svc.submit(Action(type="run.spec.approve", on_behalf_of=DAVE, requested_by="system:api_key",
                                  params={"webhook_id": "wh"}), ORG, "webhook")
    assert out["outcome"] == "REFUSE" and "executor 'webhook'" in out["reason"]


async def test_role_lost_after_submit_blocks_approval_and_execution(svc, counting):
    await grant()
    pending = (await svc.submit(act("invoice.approve", amount=Decimal("10"), currency="INR"), ORG, "counting"))["request"]
    approved = (await svc.submit(act("invoice.approve", amount=Decimal("20"), currency="INR"), ORG, "counting"))["request"]
    await set_row(approved["id"], status="approved", decided_by=BOB, decided_hash=approved["request_hash"])
    await set_role(ALICE, "member")

    with pytest.raises(RequestError) as e:                   # at approval
        await svc.decide(pending["id"], BOB, BOB_IDS, ORG, pending["request_hash"], approve=True)
    assert e.value.status == 409 and "holds no authority" in str(e.value)
    assert (await last("prime.approval.refuse"))["actor"] == BOB

    await svc._execute(approved["id"])                       # immediately before execution
    row = await load(approved["id"])
    assert row.exec_status == "failed" and "holds no authority" in row.exec_result["error"]
    assert counting.calls == []
    result = await last("prime.execution.result")
    assert result["payload"]["authority"][0] == {**result["payload"]["authority"][0], "person": ALICE, "ok": False}


async def test_deputy_without_authority_cannot_approve_but_can_reject(svc, counting):
    await grant(deputy="dave@a.test")
    req = (await svc.submit(act("invoice.approve", amount=Decimal("10"), currency="INR"), ORG, "counting"))["request"]
    seen = await svc.get(req["id"], DAVE, DAVE_IDS, ORG)
    assert not seen["can_approve"] and "holds no authority" in seen["blocked_reason"]
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], DAVE, DAVE_IDS, ORG, req["request_hash"], approve=True)
    assert e.value.status == 403 and counting.calls == []
    done = await svc.decide(req["id"], DAVE, DAVE_IDS, ORG, req["request_hash"], approve=False)
    assert done["state"] == "rejected"


async def test_grantor_asking_for_money_still_needs_a_second_person(svc, counting):
    await grant(AutonomyLevel.ACT_SILENTLY)
    out = await svc.submit(act("invoice.approve", requested_by=ALICE, amount=Decimal("10"), currency="INR"),
                           ORG, "counting")
    assert out["outcome"] == "NEEDS_APPROVAL" and "second person" in out["reason"]
    assert out["request"]["state"] == "pending" and counting.calls == []
    with pytest.raises(RequestError):                        # not by herself
        await svc.decide(out["request"]["id"], ALICE, [ALICE], ORG, out["request"]["request_hash"], approve=True)
    done = await svc.decide(out["request"]["id"], BOB, BOB_IDS, ORG, out["request"]["request_hash"], approve=True)
    assert done["execution"]["status"] == "succeeded" and len(counting.calls) == 1

    # Neither monetary nor external: her own level-4 delegation still acts at once.
    leave = await svc.submit(act(requested_by=ALICE), ORG, "counting")
    assert leave["outcome"] == "EXECUTE" and len(counting.calls) == 2


async def test_self_requested_money_marked_approved_by_prime_is_refused_at_execution(svc, counting):
    await grant()
    req = (await svc.submit(act("invoice.approve", requested_by=ALICE, amount=Decimal("10"), currency="INR"),
                            ORG, "counting"))["request"]
    await set_row(req["id"], status="approved", decided_by="prime", decided_hash=req["request_hash"])
    await svc._execute(req["id"])
    row = await load(req["id"])
    assert row.exec_status == "failed" and "other than the requester" in row.exec_result["error"]
    assert counting.calls == []


# ── finding 2: currency and amount ────────────────────────────────────────────

@pytest.mark.parametrize("amount,currency", [
    ("400000", "JPY"),          # small-unit currency under an INR ceiling
    ("6000000", "IDR"),
    ("10", "USD"),              # large-unit currency inside an INR limit
    ("NaN", "INR"), ("Infinity", "INR"), ("-5", "INR"), ("1.001", "INR"), ("1E-1000", "INR"),
])
async def test_authorize_refuses_other_currencies_and_bad_amounts(amount, currency):
    now = datetime.now(timezone.utc)
    d = Delegation(grantor=ALICE, deputy=BOB, autonomy=4, scope={"invoice.approve"},
                   limits=Limits(max_amount=Decimal("500000"), currency="INR"),
                   valid_from=now - timedelta(hours=1), valid_until=now + timedelta(days=1))
    # Built without validation: authorize() must hold even for an Action no model checked.
    a = Action.model_construct(id="a", type="invoice.approve", on_behalf_of=ALICE, requested_by="x",
                               amount=Decimal(amount), currency=currency, params={})
    assert authorize(a, now, [d]).outcome is Outcome.REFUSE


@pytest.mark.parametrize("bad", [
    {"currency": "USD", "amount": "10"}, {"currency": "inr", "amount": "10"},
    {"amount": "1.001"}, {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": "-1"},
    {"amount": "6000000"},
])
async def test_input_models_accept_only_inr_and_sane_amounts(bad):
    for model in (inbox_api.RequestIn, prime_api.ActionIn):
        with pytest.raises(ValidationError):
            model(type="invoice.approve", **bad)
    if "currency" not in bad:
        with pytest.raises(ValidationError):
            prime_api.DelegationIn(scope=["invoice.approve"], autonomy=2, deputy="b",
                                   valid_from=datetime.now(timezone.utc),
                                   valid_until=datetime.now(timezone.utc) + timedelta(days=1),
                                   max_amount=bad["amount"])
    assert inbox_api.RequestIn(type="invoice.approve", amount="120.50", currency="INR").amount == Decimal("120.50")


async def test_submit_refuses_another_currency(svc, counting):
    await grant(AutonomyLevel.ACT_SILENTLY)
    out = await svc.submit(act("invoice.approve", amount=Decimal("900"), currency="USD"), ORG, "counting")
    assert out["outcome"] == "REFUSE" and "only INR" in out["reason"] and out["request"] is None
    assert counting.calls == []


async def test_currency_is_hashed_and_rechecked_at_approval_and_execution(svc, counting):
    await grant()
    reqs = [(await svc.submit(act("invoice.approve", amount=Decimal("10"), currency="INR", params={"n": n}),
                              ORG, "counting"))["request"] for n in range(2)]
    # Rewrite the currency and re-hash consistently, as a path that skipped submit() would.
    for i, req in enumerate(reqs):
        await set_row(req["id"], currency="JPY")
        new_hash = compute_hash(await load(req["id"]))
        assert new_hash != req["request_hash"]               # currency is in the hash
        extra = dict(status="approved", decided_by=BOB, decided_hash=new_hash) if i else {}
        await set_row(req["id"], request_hash=new_hash, **extra)
    with pytest.raises(RequestError) as e:
        await svc.decide(reqs[0]["id"], BOB, BOB_IDS, ORG, compute_hash(await load(reqs[0]["id"])), approve=True)
    assert e.value.status == 409 and "only INR" in str(e.value)
    await svc._execute(reqs[1]["id"])
    row = await load(reqs[1]["id"])
    assert row.exec_status == "failed" and "only INR" in row.exec_result["error"]
    assert counting.calls == []


# ── external effect: a human who is neither requester nor the person it is for ──

@pytest.fixture
def velaris(counting, monkeypatch):
    monkeypatch.setitem(executors.REGISTRY, "velaris.flow", counting)
    return counting


async def _ext(svc, level=AutonomyLevel.ACT_WITH_APPROVAL, requested_by=SYSTEM):
    await grant(level)
    out = await svc.submit(act(requested_by=requested_by), ORG, "velaris.flow")
    return out, out["request"]


@pytest.mark.parametrize("level", [AutonomyLevel.ACT_THEN_NOTIFY, AutonomyLevel.ACT_SILENTLY])
async def test_external_effect_is_never_auto_approved(svc, velaris, level):
    out, req = await _ext(svc, level)
    assert out["outcome"] == "NEEDS_APPROVAL" and req["state"] == "pending" and velaris.calls == []
    assert req["decided_by"] is None


async def test_external_effect_approver_cannot_be_the_person_it_is_for(svc, velaris):
    _, req = await _ext(svc)
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], ALICE, [ALICE, "alice@a.test"], ORG, req["request_hash"], approve=True)
    assert e.value.status == 409 and velaris.calls == []
    assert (await svc.get(req["id"], ALICE, [ALICE], ORG))["can_approve"] is False
    done = await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert done["execution"]["status"] == "succeeded" and len(velaris.calls) == 1


async def test_external_effect_approver_cannot_be_the_requester(svc, velaris):
    _, req = await _ext(svc, requested_by=BOB)
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert e.value.status == 403 and velaris.calls == []


async def test_external_effect_rechecked_before_execution(svc, velaris):
    _, req = await _ext(svc)
    for who in (ALICE, PRIME):      # a row whose approver is the grantor, or Prime itself
        await set_row(req["id"], status="approved", decided_by=who, exec_status=None,
                      decided_hash=req["request_hash"])
        await svc._execute(req["id"])
        row = await svc._load(req["id"])
        assert row.exec_status != "succeeded" and velaris.calls == []
        await set_row(req["id"], exec_status=None, exec_result=None)
