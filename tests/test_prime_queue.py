"""KAN-26: approver queues by role, urgency order, badge counts, reminders, expiry notices."""
# ruff: noqa: F811
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from aether_os.core.audit import chain
from aether_os.prime import limits, reminders
from aether_os.prime.approvals import RequestError, _now
from aether_os.prime.repository import DelegationRepository
from aether_os.tests.prime_helpers import (  # noqa: F401
    act, ALICE, BOB, BOB_IDS, CAROL, counting, DAVE, grant, ORG, set_row, svc,
)

pytestmark = pytest.mark.asyncio
DAVE_IDS = [DAVE, "dave@a.test"]


class Outbox:
    def __init__(self):
        self.sent = []

    async def __call__(self, to, subject, text):
        self.sent.append((to, subject))


async def test_each_approver_sees_only_what_their_role_may_decide(svc, counting):
    await grant(deputy="dave@a.test", scope={"leave.approve", "deploy.staging"})
    leave = (await svc.submit(act("leave.approve", params={"days": 2}), ORG, "counting"))["request"]
    deploy = (await svc.submit(act("deploy.staging"), ORG, "counting"))["request"]
    owner = await svc.inbox(ALICE, [ALICE], ORG)
    assert {r["id"] for r in owner["requests"]} == {leave["id"], deploy["id"]}
    member = await svc.inbox(DAVE, DAVE_IDS, ORG)                 # a member may decide deploys, not leave
    assert [r["id"] for r in member["requests"]] == [deploy["id"]] and member["total"] == 1
    assert (await svc.counts(DAVE, DAVE_IDS, ORG)) == {"pending": 1, "urgent": 0}
    assert (await svc.counts(ALICE, [ALICE], ORG))["pending"] == 2


async def test_queue_is_sorted_by_urgency_and_flags_it(svc, counting):
    await grant()
    first = (await svc.submit(act("leave.approve"), ORG, "counting"))["request"]
    second = (await svc.submit(act("leave.approve"), ORG, "counting"))["request"]
    await set_row(first["id"], expires_at=_now() + timedelta(hours=50))
    await set_row(second["id"], expires_at=_now() + timedelta(hours=3))
    page = await svc.inbox(ALICE, [ALICE], ORG)
    assert [r["id"] for r in page["requests"]] == [second["id"], first["id"]]
    assert [r["urgency"] for r in page["requests"]] == ["urgent", "normal"]
    assert (await svc.counts(ALICE, [ALICE], ORG)) == {"pending": 2, "urgent": 1}


async def test_deputy_queue_follows_the_delegation_window(svc, counting):
    d = await grant()
    req = (await svc.submit(act("leave.approve"), ORG, "counting"))["request"]
    assert (await svc.inbox(BOB, BOB_IDS, ORG))["total"] == 1
    await DelegationRepository().revoke(d.id, ALICE, datetime.now(timezone.utc), ORG)
    assert (await svc.inbox(BOB, BOB_IDS, ORG))["total"] == 0      # no longer the deputy's
    assert (await svc.inbox(ALICE, [ALICE], ORG))["requests"][0]["id"] == req["id"]


async def test_request_lifetime_is_per_organisation_and_bounded(svc, counting):
    await limits.set_limits(ORG, CAROL, Decimal("500000"), 30, request_ttl_hours=24)
    await grant()
    req = (await svc.submit(act("leave.approve"), ORG, "counting"))["request"]
    left = datetime.fromisoformat(req["expires_at"]).replace(tzinfo=None) - _now()
    assert timedelta(hours=23) < left <= timedelta(hours=24)
    for bad in (0, limits.HARD_MAX_REQUEST_TTL_HOURS + 1):
        with pytest.raises(ValueError):
            await limits.set_limits(ORG, CAROL, Decimal("500000"), 30, request_ttl_hours=bad)
    assert (await limits.get_limits(ORG)).request_ttl_hours == 24


async def test_reminder_goes_out_once_even_if_two_workers_sweep_together(svc, counting):
    await grant()
    req = (await svc.submit(act("leave.approve"), ORG, "counting"))["request"]
    await set_row(req["id"], expires_at=_now() + timedelta(hours=2), created_at=_now() - timedelta(hours=70))
    box = Outbox()
    runs = await asyncio.gather(reminders.sweep(notify=box), reminders.sweep(notify=box))
    assert sum(r["reminded"] for r in runs) == 1
    assert sorted(to for to, _ in box.sent) == ["alice@a.test", "bob@a.test"]
    assert (await reminders.sweep(notify=box))["reminded"] == 0
    assert "prime.approval.reminder" in [e["action"] for e in await chain.read_entries(limit=200)]


async def test_expired_request_fails_closed_and_the_requester_is_told_once(svc, counting):
    await grant()
    req = (await svc.submit(act("leave.approve", requested_by=DAVE), ORG, "counting"))["request"]
    await set_row(req["id"], expires_at=_now() - timedelta(minutes=1))
    box = Outbox()
    assert (await reminders.sweep(notify=box))["expired"] == 1
    assert "dave@a.test" in [to for to, _ in box.sent]
    assert (await reminders.sweep(notify=box))["expired"] == 0
    assert (await svc.get(req["id"], ALICE, [ALICE], ORG))["state"] == "expired"
    with pytest.raises(RequestError) as e:
        await svc.decide(req["id"], ALICE, [ALICE], ORG, req["request_hash"], approve=True)
    assert e.value.status == 409 and counting.calls == []


async def test_a_failing_mailer_does_not_stop_the_sweep(svc, counting):
    await grant()
    req = (await svc.submit(act("leave.approve"), ORG, "counting"))["request"]
    await set_row(req["id"], expires_at=_now() + timedelta(hours=1), created_at=_now() - timedelta(hours=70))

    async def broken(*a):
        raise OSError("smtp down")
    assert (await reminders.sweep(notify=broken))["reminded"] == 1
