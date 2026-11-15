"""KAN-20: GET /prime/requests/{id} carries everything an approver needs to decide."""
# ruff: noqa: F811
from __future__ import annotations

from decimal import Decimal

import pytest

from aether_os.core import db
from aether_os.prime import approvals
from aether_os.prime.approvals import RequestError
from aether_os.tests.prime_helpers import (  # noqa: F401
    act, ALICE, BOB, BOB_IDS, CAROL, counting, DAVE, grant, MEMBER, ORG, OTHER_ORG, svc,
)

pytestmark = pytest.mark.asyncio


async def _invoice(svc):
    await grant()
    out = await svc.submit(act("invoice.approve", amount=Decimal("250"), currency="INR"), ORG, "counting")
    return out["request"]


async def test_detail_has_policy_risk_money_roles_and_ledger(svc, counting):
    req = await _invoice(svc)
    view = await svc.get(req["id"], BOB, BOB_IDS, ORG)
    d = view["detail"]
    assert view["request_hash"] == req["request_hash"]            # the hash the approval binds to
    async with db.get_session_factory()() as s:
        row = await s.get(approvals.PrimeRequest, req["id"])
    assert approvals.compute_hash(row) == view["request_hash"]
    assert d["risk_class"] == "high" and d["policy"]["source"] == "prime.authz"
    assert d["policy"]["autonomy"]["name"] == "ACT_WITH_APPROVAL" and d["policy"]["second_person_required"]
    assert d["money"]["amount"] == "250" and d["money"]["delegation_limit"] == "1000"
    assert d["money"]["within_delegation_limit"] and d["money"]["counted_against"] == "delegation"
    assert d["eligible_roles"] == ["admin", "owner"]
    assert [e["action"] for e in d["ledger"]] == ["prime.approval.request"]


async def test_personal_data_is_pseudonymised_unless_the_viewer_may_see_it(svc, counting):
    await grant(deputy="dave@a.test")
    out = await svc.submit(act("leave.approve", params={"employee": "Priya Nair", "days": 3}), ORG, "counting")
    rid = out["request"]["id"]
    clear = await svc.get(rid, ALICE, [ALICE], ORG)               # owner
    assert clear["action"]["params"]["employee"] == "Priya Nair"
    assert clear["detail"]["data_touched"][0]["value"] == "Priya Nair"
    masked = await svc.get(rid, DAVE, [DAVE, "dave@a.test"], ORG)  # a member deputy
    assert "Priya" not in str(masked)
    assert masked["action"]["params"]["employee"].startswith("person-")
    assert masked["detail"]["data_touched"][0]["pseudonymised"]
    assert masked["request_hash"] == clear["request_hash"]       # display only; the bound hash is unchanged


async def test_no_secret_in_the_payload_and_other_orgs_see_nothing(svc, counting):
    await grant()
    key = "sk-abcdefghijklmnopqrstuvwx1234"
    out = await svc.submit(act("leave.approve", params={"note": f"token={key}"}), ORG, "counting")
    view = await svc.get(out["request"]["id"], ALICE, [ALICE], ORG)
    assert key not in str(view)
    with pytest.raises(RequestError) as e:
        await svc.get(out["request"]["id"], BOB, BOB_IDS, OTHER_ORG)
    assert e.value.status == 404


async def test_pseudonym_is_keyed_per_org_and_not_reproducible_without_the_key(svc, counting):
    """Root cause (security review): an unkeyed sha256(org+value)[:8] let anyone confirm a known
    email or name by brute force, and 8 hex digits collide."""
    import hashlib
    from aether_os.prime import detail
    a = await detail.pseudonym(ORG, "priya@x.test")
    assert a == await detail.pseudonym(ORG, "priya@x.test")                 # stable inside an org
    assert a != await detail.pseudonym(OTHER_ORG, "priya@x.test")           # differs between orgs
    assert len(a) >= len("person-") + 32
    old = "person-" + hashlib.sha256(f"{ORG}\0priya@x.test".encode()).hexdigest()[:8]
    assert a != old and not a.startswith(old)                               # the old public formula no longer matches
