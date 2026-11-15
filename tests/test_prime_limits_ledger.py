"""Prime per-organisation limits and the ledger browser.

Fixtures (svc, counting) are imported from tests/prime_helpers.py."""
# ruff: noqa: F811  (a fixture imported by name and then requested as an argument)
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from sqlalchemy import update

from aether_os.core.audit import chain
from aether_os.core.audit.chain import AuditChainEntry
import aether_os.core.db as db
from aether_os.gateway.routers import prime_ledger_router as ledger_api
from aether_os.gateway.routers import prime_router as prime_api
from aether_os.prime import authorize, Delegation, DelegationRepository, ledger_view, limits, Limits
from aether_os.prime.approvals import RequestError
from aether_os.prime.authz import HARD_MAX_DELEGATION_DURATION, HARD_PAYMENT_CEILING
from aether_os.prime.models import PrimeOrgLimits
from aether_os.tests.prime_helpers import (  # noqa: F401  (svc and counting are fixtures)
    act, actions, ADMIN, ALICE, API_KEY, BOB, BOB_IDS, CAROL, counting, grant, MALLORY, MEMBER, ORG, OTHER_ORG, OUTSIDER, OWNER, svc, DAVE,
)

pytestmark = pytest.mark.asyncio


# ── limits ────────────────────────────────────────────────────────────────────



async def test_limits_default_then_admin_changes_are_validated_and_ledgered(svc):
    assert await limits.get_limits(ORG) == limits.DEFAULT_LIMITS == limits.OrgLimits(Decimal("500000"), 30)
    shown = await prime_api.read_limits(user=MEMBER)
    assert shown["payment_ceiling"] == "500000" and shown["max_delegation_days"] == 30
    assert shown["hard_payment_ceiling"] == str(HARD_PAYMENT_CEILING) and not shown["can_edit"]

    for who in (MEMBER, API_KEY):
        with pytest.raises(HTTPException) as e:
            await prime_api.write_limits(prime_api.LimitsIn(payment_ceiling=1000, max_delegation_days=5), user=who)
        assert e.value.status_code == 403
    for bad in (dict(payment_ceiling=HARD_PAYMENT_CEILING + 1, max_delegation_days=30),
                dict(payment_ceiling=1000, max_delegation_days=HARD_MAX_DELEGATION_DURATION.days + 1)):
        with pytest.raises(HTTPException) as e:
            await prime_api.write_limits(prime_api.LimitsIn(**bad), user=ADMIN)
        assert e.value.status_code == 400
    for bad in (dict(payment_ceiling=0, max_delegation_days=30), dict(payment_ceiling=5, max_delegation_days=0)):
        with pytest.raises(ValidationError):
            prime_api.LimitsIn(**bad)
    assert await actions() == []

    await prime_api.write_limits(prime_api.LimitsIn(payment_ceiling=2000, max_delegation_days=60), user=ADMIN)
    assert await limits.get_limits(ORG) == limits.OrgLimits(Decimal("2000"), 60)
    assert await limits.get_limits(OTHER_ORG) == limits.DEFAULT_LIMITS
    entry = (await chain.read_entries())[-1]
    assert entry["action"] == "prime.limits.change" and entry["actor"] == CAROL
    assert entry["payload"] == {"org_id": ORG,
                                "from": {"payment_ceiling": "500000", "max_delegation_days": 30,
                                         "request_ttl_hours": 72},
                                "to": {"payment_ceiling": "2000", "max_delegation_days": 60,
                                       "request_ttl_hours": 72}}
    await prime_api.write_limits(prime_api.LimitsIn(payment_ceiling=2000, max_delegation_days=60), user=ADMIN)
    assert await actions() == ["prime.limits.change"]          # no change, no entry
    assert (await prime_api.meta(user=MEMBER))["payment_ceiling"] == "2000"


async def test_org_limits_are_enforced(svc):
    now = datetime.now(timezone.utc)
    body = prime_api.DelegationIn(scope=["invoice.approve"], autonomy=4, valid_from=now,
                                  valid_until=now + timedelta(days=45), deputy="Bob@A.test", max_amount=1500)
    with pytest.raises(HTTPException) as e:                     # default: 30 days
        await prime_api.create_delegation(body, user=OWNER)
    assert e.value.status_code == 400 and "30 days" in e.value.detail

    await limits.set_limits(ORG, CAROL, Decimal("2000"), 60)
    with pytest.raises(HTTPException) as e:                     # limit above the org ceiling
        await prime_api.create_delegation(body.model_copy(update={"max_amount": Decimal("2001")}), user=OWNER)
    assert e.value.status_code == 400
    created = await prime_api.create_delegation(body, user=OWNER)
    assert created["deputy"] == "bob@a.test"

    ok = await svc.submit(act("invoice.approve", amount=Decimal("1500"), currency="INR"), ORG)
    assert ok["outcome"] == "EXECUTE"
    await limits.set_limits(ORG, CAROL, Decimal("1000"), 60)    # lowered: applies at once
    over = await svc.submit(act("invoice.approve", amount=Decimal("1500"), currency="INR"), ORG)
    assert over["outcome"] == "REFUSE" and "ceiling" in over["reason"]


async def test_lowered_ceiling_blocks_a_pending_approval(svc, counting):
    await grant(limits=Limits(max_amount=Decimal("900"), currency="INR"))
    req = (await svc.submit(act("invoice.approve", amount=Decimal("800"), currency="INR"), ORG, "counting"))["request"]
    await limits.set_limits(ORG, CAROL, Decimal("500"), 30)
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)
    assert e.value.status == 409 and "ceiling" in str(e.value) and counting.calls == []


async def test_hard_bounds_hold_whatever_is_stored_or_passed(svc):
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        Delegation(grantor=ALICE, deputy=BOB, autonomy=4, scope={"leave.approve"}, valid_from=now,
                   valid_until=now + HARD_MAX_DELEGATION_DURATION + timedelta(seconds=1))
    d = Delegation(grantor=ALICE, deputy=BOB, autonomy=4, scope={"invoice.approve"},
                   # Past the bound Limits itself enforces, to show authorize() holds on its own.
                   limits=Limits.model_construct(max_amount=HARD_PAYMENT_CEILING * 10, currency="INR"),
                   valid_from=now - timedelta(hours=1), valid_until=now + timedelta(days=1))
    a = act("invoice.approve", amount=HARD_PAYMENT_CEILING + 1, currency="INR")
    assert authorize(a, now, [d], payment_ceiling=HARD_PAYMENT_CEILING * 100).outcome.value == "REFUSE"
    await DelegationRepository().add(
        d.model_copy(update={"limits": Limits(max_amount=Decimal("5"), currency="INR")}), org_id=ORG)
    # A row written past the bound (not through set_limits) makes Prime refuse, not trust it.
    async with db.get_session_factory()() as s:
        s.add(PrimeOrgLimits(org_id=ORG, payment_ceiling=str(HARD_PAYMENT_CEILING * 2),
                             max_delegation_days=30, updated_by="x"))
        await s.commit()
    out = await svc.submit(act("invoice.approve", amount=Decimal("1"), currency="INR"), ORG)
    assert out["outcome"] == "REFUSE" and "could not be loaded" in out["reason"]


# ── ledger browser ────────────────────────────────────────────────────────────

async def test_ledger_browser_is_org_scoped_filtered_and_paginated(svc):
    for i in range(7):
        await chain.append(actor=DAVE if i % 2 else BOB, action=f"thing.{'a' if i < 4 else 'b'}",
                           payload={"org_id": ORG, "i": i}, timestamp=1000.0 + i)
    await chain.append(actor=MALLORY, action="thing.a", payload={"org_id": OTHER_ORG}, timestamp=1003.5)
    await chain.append(actor=MALLORY, action="thing.a",          # names org_a only in a nested field
                       payload={"org_id": OTHER_ORG, "metadata": {"org_id": ORG}}, timestamp=1003.6)
    await chain.append(actor="prime", action="prime.decision", payload={"on_behalf_of": DAVE})  # no org

    full = await ledger_view.browse(ORG)
    assert [e["payload"]["i"] for e in full["entries"]] == [6, 5, 4, 3, 2, 1, 0] and full["next_before"] is None
    assert [e["actor"] for e in (await ledger_view.browse(OTHER_ORG))["entries"]] == [MALLORY, MALLORY]

    first = await ledger_view.browse(ORG, limit=3)
    second = await ledger_view.browse(ORG, limit=3, before_seq=first["next_before"])
    third = await ledger_view.browse(ORG, limit=3, before_seq=second["next_before"])
    assert [e["payload"]["i"] for p in (first, second, third) for e in p["entries"]] == [6, 5, 4, 3, 2, 1, 0]
    assert third["next_before"] is None

    assert {e["actor"] for e in (await ledger_view.browse(ORG, actor=DAVE))["entries"]} == {DAVE}
    assert [e["payload"]["i"] for e in (await ledger_view.browse(ORG, action_prefix="thing.b"))["entries"]] == [6, 5, 4]
    assert [e["payload"]["i"] for e in (await ledger_view.browse(ORG, since=1002.0, until=1004.0))["entries"]] == [4, 3, 2]

    page = await ledger_api.list_entries(actor=None, event="thing", since=datetime.fromtimestamp(1005, timezone.utc),
                                         until=None, before=None, limit=50, user=ADMIN)
    assert page["whole_org"] and [e["payload"]["i"] for e in page["entries"]] == [6, 5]
    own = await ledger_api.list_entries(actor=None, event=None, since=None, until=None, before=None, limit=50, user=MEMBER)
    assert not own["whole_org"] and {e["actor"] for e in own["entries"]} == {DAVE}
    other = await ledger_api.list_entries(actor=BOB, event=None, since=None, until=None, before=None, limit=50, user=MEMBER)
    assert other["entries"] == []
    with pytest.raises(HTTPException) as e:
        await ledger_api.list_entries(actor=None, event=None, since=None, until=None, before=None, limit=50, user=API_KEY)
    assert e.value.status_code == 403


async def test_ledger_entry_shows_its_link_and_hides_other_orgs(svc):
    await chain.append(actor=MALLORY, action="thing.a", payload={"org_id": OTHER_ORG, "secret": "theirs"})
    await chain.append(actor=DAVE, action="thing.a", payload={"org_id": ORG})
    await chain.append(actor=BOB, action="thing.a", payload={"org_id": ORG})
    stored = await chain.read_entries()

    # Each organisation has its own chain: org_a's first entry links to the genesis,
    # not to org_b's entry 1, and its second entry links to its first.
    got = await ledger_api.get_entry(2, user=ADMIN)
    assert got["link_ok"] and got["hash_ok"] and got["prev_hash"] == chain.GENESIS_HASH
    assert got["previous"] == {"seq": None, "entry_hash": chain.GENESIS_HASH}   # nothing of org_b's
    nxt = await ledger_api.get_entry(3, user=ADMIN)
    assert nxt["link_ok"] and nxt["previous"] == {"seq": 2, "entry_hash": stored[1]["entry_hash"]}
    first = await ledger_api.get_entry(1, user=OUTSIDER)
    assert first["previous"] == {"seq": None, "entry_hash": chain.GENESIS_HASH} and first["link_ok"]

    for seq, who in ((1, ADMIN), (2, OUTSIDER), (3, MEMBER), (99, ADMIN)):   # other org / not own / missing
        with pytest.raises(HTTPException) as e:
            await ledger_api.get_entry(seq, user=who)
        assert e.value.status_code == 404
    assert (await ledger_api.get_entry(2, user=MEMBER))["actor"] == DAVE

    async with db.get_session_factory()() as s:                 # an edited entry is reported
        await s.execute(update(AuditChainEntry).where(AuditChainEntry.seq == 3)
                        .values(payload='{"org_id":"org_a","x":1}'))
        await s.commit()
    assert not (await ledger_api.get_entry(3, user=ADMIN))["hash_ok"]
    assert not (await prime_api.verify_ledger(user=ADMIN))["ok"]
