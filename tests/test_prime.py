"""Prime core: real authorize(), real ledger, isolated SQLite database."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError

import aether_os.core.db as db
from aether_os.core.audit import chain
from aether_os.core.audit.chain import AuditChainEntry
from aether_os.core.models import Organisation, User
from aether_os.prime import (
    ACTION_TYPES, MAX_DELEGATION_DURATION, NEVER, PAYMENT_CEILING, Action,
    AutonomyLevel, Delegation, DelegationRepository, Limits, Outcome, PrimeService,
    authorize,
)
from aether_os.prime.authz import HARD_MAX_DELEGATION_DURATION
from aether_os.prime.models import PrimeDelegation, PrimeOrgLimits

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
NOW = T0 + timedelta(days=1)
UNTIL = T0 + timedelta(days=7)
ACTING = {Outcome.EXECUTE, Outcome.EXECUTE_AND_NOTIFY}


def delegation(**kw) -> Delegation:
    base = dict(
        grantor="ceo", deputy="coo", autonomy=AutonomyLevel.ACT_SILENTLY,
        scope={"leave.approve", "invoice.approve", "deploy.staging"},
        limits=Limits(max_amount=Decimal("1000"), currency="INR"),
        valid_from=T0, valid_until=UNTIL,
    )
    base.update(kw)
    return Delegation(**base)


def action(type_="leave.approve", **kw) -> Action:
    return Action(type=type_, on_behalf_of=kw.pop("on_behalf_of", "ceo"),
                  requested_by="model:planner", **kw)


def invoice(amount: str, currency: str = "INR") -> Action:
    return action("invoice.approve", amount=Decimal(amount), currency=currency)


# ── NEVER list ────────────────────────────────────────────────────────────────

def test_never_list_covers_the_required_categories():
    assert {"person.terminate", "person.hire", "pay.change", "contract.sign",
            "delegation.modify", "autonomy.change", "ledger.delete", "ledger.alter",
            "security.disable"} <= NEVER
    assert not NEVER & set(ACTION_TYPES)


@pytest.mark.parametrize("never_type", sorted(NEVER))
def test_every_never_action_is_refused_even_with_level4_delegation_naming_it(never_type):
    d = delegation(scope=set(NEVER) | set(ACTION_TYPES), autonomy=AutonomyLevel.ACT_SILENTLY,
                   limits=Limits(max_amount=PAYMENT_CEILING * 10, currency="INR"))
    decision = authorize(action(never_type, amount=Decimal("1"), currency="INR"), NOW, [d])
    assert decision.outcome is Outcome.REFUSE
    assert "NEVER" in decision.reason


@pytest.mark.parametrize("type_", sorted(t for t, monetary in ACTION_TYPES.items() if monetary))
def test_payment_above_ceiling_is_refused_whatever_the_delegation_limit(type_):
    d = delegation(scope=set(ACTION_TYPES), limits=Limits(max_amount=PAYMENT_CEILING * 10, currency="INR"))
    at = authorize(action(type_, amount=PAYMENT_CEILING, currency="INR"), NOW, [d])
    over = authorize(action(type_, amount=PAYMENT_CEILING + 1, currency="INR"), NOW, [d])
    assert at.outcome is Outcome.EXECUTE
    assert over.outcome is Outcome.REFUSE and "ceiling" in over.reason


# ── fail closed ───────────────────────────────────────────────────────────────

def test_unknown_action_type_is_refused():
    d = delegation(scope={"coffee.order"})
    assert authorize(action("coffee.order"), NOW, [d]).outcome is Outcome.REFUSE


def test_no_delegation_at_all_is_refused():
    decision = authorize(action(), NOW)
    assert decision.outcome is Outcome.REFUSE and decision.delegation_id is None
    assert authorize(action(), NOW, []).outcome is Outcome.REFUSE


def test_someone_elses_delegation_gives_no_authority():
    d = delegation(grantor="cfo", deputy="coo")
    assert authorize(action(on_behalf_of="ceo"), NOW, [d]).outcome is Outcome.REFUSE


def test_expiry_boundaries():
    d = delegation()
    tick = timedelta(microseconds=1)
    assert authorize(action(), UNTIL - tick, [d]).outcome is Outcome.EXECUTE
    for when in (UNTIL, UNTIL + tick):
        decision = authorize(action(), when, [d])
        assert decision.outcome is Outcome.REFUSE
        assert "expired" in decision.reason and decision.delegation_id == d.id


def test_not_yet_valid_boundaries():
    d = delegation()
    tick = timedelta(microseconds=1)
    before = authorize(action(), T0 - tick, [d])
    assert before.outcome is Outcome.REFUSE and "not valid until" in before.reason
    assert authorize(action(), T0, [d]).outcome is Outcome.EXECUTE


def test_revoked_delegation_is_refused():
    d = delegation()
    assert authorize(action(), NOW, [d]).outcome is Outcome.EXECUTE
    revoked = d.revoke(by="ceo", now=NOW)
    decision = authorize(action(), NOW, [revoked])
    assert decision.outcome is Outcome.REFUSE
    assert "revoked" in decision.reason and decision.delegation_id == d.id


def test_amount_at_limit_executes_and_one_unit_over_does_not():
    d = delegation()
    assert authorize(invoice("1000"), NOW, [d]).outcome is Outcome.EXECUTE
    over = authorize(invoice("1000.01"), NOW, [d])
    assert over.outcome is Outcome.ROUTE_TO_DEPUTY and over.deputy == "coo"
    assert authorize(invoice("1001"), NOW, [d]).outcome is Outcome.ROUTE_TO_DEPUTY


def test_missing_limit_never_executes_a_monetary_action():
    d = delegation(limits=None)
    decision = authorize(invoice("1"), NOW, [d])
    assert decision.outcome is Outcome.ROUTE_TO_DEPUTY and "no amount limit" in decision.reason
    assert authorize(action("leave.approve"), NOW, [d]).outcome is Outcome.EXECUTE


@pytest.mark.parametrize("bad", [
    dict(),                                        # no amount, no currency
    dict(amount=Decimal("5")),                     # no currency
    dict(amount=Decimal("0"), currency="INR"),
    dict(amount=Decimal("-5"), currency="INR"),
])
def test_malformed_monetary_action_is_refused(bad):
    assert authorize(action("invoice.approve", **bad), NOW, [delegation()]).outcome is Outcome.REFUSE


def test_other_currency_never_executes():
    assert authorize(invoice("5", "USD"), NOW, [delegation()]).outcome is Outcome.REFUSE
    with pytest.raises(ValidationError):
        Limits(max_amount=Decimal("1000"), currency="USD")


def test_out_of_scope_action_routes_to_the_deputy():
    d = delegation(scope={"leave.approve"})
    decision = authorize(action("deploy.staging"), NOW, [d])
    assert decision.outcome is Outcome.ROUTE_TO_DEPUTY
    assert decision.deputy == "coo" and decision.delegation_id == d.id
    assert "coo" in decision.reason


@pytest.mark.parametrize("level,expected", [
    (AutonomyLevel.OBSERVE, Outcome.REFUSE),
    (AutonomyLevel.RECOMMEND, Outcome.RECOMMEND_ONLY),
    (AutonomyLevel.ACT_WITH_APPROVAL, Outcome.NEEDS_APPROVAL),
    (AutonomyLevel.ACT_THEN_NOTIFY, Outcome.EXECUTE_AND_NOTIFY),
    (AutonomyLevel.ACT_SILENTLY, Outcome.EXECUTE),
])
def test_each_autonomy_level_maps_to_its_outcome(level, expected):
    d = delegation(autonomy=level)
    for a in (action("leave.approve"), invoice("1000")):
        decision = authorize(a, NOW, [d])
        assert decision.outcome is expected
        assert decision.delegation_id == d.id and decision.reason


def test_autonomy_levels_are_0_to_4():
    assert [int(level) for level in AutonomyLevel] == [0, 1, 2, 3, 4]


def test_most_restrictive_matching_delegation_wins():
    low = delegation(autonomy=AutonomyLevel.RECOMMEND)
    high = delegation(autonomy=AutonomyLevel.ACT_SILENTLY)
    for order in ([low, high], [high, low]):
        decision = authorize(action(), NOW, order)
        assert decision.outcome is Outcome.RECOMMEND_ONLY and decision.delegation_id == low.id


def test_fail_closed_sweep_never_acts_without_a_live_in_scope_delegation():
    """Brute force: no combination of dead/out-of-scope/over-limit inputs acts."""
    dead = [
        [],
        [delegation().revoke("ceo", NOW)],
        [delegation(valid_from=NOW + timedelta(days=1), valid_until=NOW + timedelta(days=2))],
        [delegation(valid_from=T0 - timedelta(days=5), valid_until=T0)],
        [delegation(grantor="cfo")],
        [delegation(scope={"nothing.real"})],
        [delegation(limits=None, scope={"invoice.approve"})],
        [delegation(autonomy=AutonomyLevel.OBSERVE)],
    ]
    types = sorted(NEVER) + ["mystery.action", "invoice.approve"]
    for ds in dead:
        for t in types:
            a = action(t, amount=Decimal("5000"), currency="INR")
            assert authorize(a, NOW, ds).outcome not in ACTING, (t, ds)


def test_naive_now_is_rejected():
    with pytest.raises(ValueError):
        authorize(action(), datetime(2026, 11, 2), [delegation()])


# ── Delegation validation ─────────────────────────────────────────────────────

def test_open_ended_delegation_is_rejected():
    with pytest.raises(ValidationError):
        Delegation(grantor="ceo", deputy="coo", autonomy=1, scope={"leave.approve"}, valid_from=T0)
    with pytest.raises(ValidationError):
        delegation(valid_until=None)


def test_delegation_duration_is_capped():
    # The model holds the bound no setting can pass; the organisation's limit
    # (default MAX_DELEGATION_DURATION) is enforced when the delegation is stored.
    assert delegation(valid_until=T0 + HARD_MAX_DELEGATION_DURATION)
    with pytest.raises(ValidationError):
        delegation(valid_until=T0 + HARD_MAX_DELEGATION_DURATION + timedelta(seconds=1))


@pytest.mark.asyncio
async def test_default_duration_limit_is_enforced_when_stored(prime_db):
    await prime_db.add(delegation(valid_until=T0 + MAX_DELEGATION_DURATION), ORG_T)
    with pytest.raises(ValueError, match="30 days"):
        await prime_db.add(delegation(valid_until=T0 + MAX_DELEGATION_DURATION + timedelta(seconds=1)), ORG_T)
    assert len(await prime_db.for_grantor("ceo")) == 1


@pytest.mark.parametrize("bad", [
    dict(valid_until=T0),                       # zero length
    dict(valid_until=T0 - timedelta(days=1)),   # ends before it starts
    dict(valid_from=datetime(2026, 11, 1)),     # naive datetime
    dict(deputy="ceo"),                         # deputy is the grantor
    dict(deputy="prime"),                       # deputy must be human
    dict(deputy=""),
    dict(scope=set()),
    dict(autonomy=5),
    dict(grantee="someone-else"),
    dict(limits=Limits.model_construct(max_amount=Decimal("-1"), currency="INR").model_dump()),
])
def test_invalid_delegations_are_rejected(bad):
    with pytest.raises(ValidationError):
        delegation(**bad)


# ── PrimeService + repository on a real (SQLite) database ─────────────────────

ORG_T = "org_t"


@pytest_asyncio.fixture
async def prime_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/prime.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[
            AuditChainEntry.__table__, PrimeDelegation.__table__, PrimeOrgLimits.__table__,
            Organisation.__table__, User.__table__]))
    async with db.get_session_factory()() as s:
        s.add(Organisation(id=ORG_T, name=ORG_T, slug=ORG_T))
        await s.flush()
        for uid in ("ceo", "alice", "bob"):
            s.add(User(id=uid, org_id=ORG_T, email=f"{uid}@t.test", password_hash="x", role="owner"))
        await s.commit()
    yield DelegationRepository()
    await engine.dispose()


def live_delegation(**kw) -> Delegation:
    now = datetime.now(timezone.utc)
    return delegation(valid_from=now - timedelta(hours=1), valid_until=now + timedelta(days=1), **kw)


@pytest.mark.asyncio
async def test_repository_round_trip_and_revoke(prime_db):
    d = live_delegation()
    await prime_db.add(d, ORG_T)
    assert await prime_db.for_grantor("ceo") == [d]
    assert await prime_db.for_grantor("cfo") == []

    assert await prime_db.revoke(d.id, by="ceo", now=datetime.now(timezone.utc))
    stored = (await prime_db.for_grantor("ceo"))[0]
    assert stored.revoked_at is not None and stored.revoked_by == "ceo"
    assert not await prime_db.revoke("no-such-id", by="ceo", now=datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_decide_writes_request_and_decision_for_an_allowed_action(prime_db):
    d = live_delegation()
    await prime_db.add(d, ORG_T)
    a = invoice("250")
    decision = await PrimeService(prime_db).decide(a, ORG_T)

    assert decision.outcome is Outcome.EXECUTE and decision.delegation_id == d.id
    entries = await chain.read_entries()
    assert [e["action"] for e in entries] == [
        "prime.delegation.grant", "prime.request", "prime.decision"]
    _grant, request, logged = entries
    assert request["actor"] == "model:planner"
    assert request["payload"]["id"] == a.id and request["payload"]["type"] == "invoice.approve"
    assert request["payload"]["amount"] == "250"
    assert logged["actor"] == "prime"
    assert logged["payload"] == {"action_id": a.id, "on_behalf_of": a.on_behalf_of,
                                 "outcome": "EXECUTE", "reason": decision.reason,
                                 "delegation_id": d.id, "deputy": None, "org_id": ORG_T,
                                 "authority": {"person": "ceo", "role": "owner", "executor": "dry_run",
                                               "ok": True, "reason": ""}}
    assert (await chain.verify()).ok


@pytest.mark.asyncio
async def test_decide_writes_request_and_decision_for_a_refused_action(prime_db):
    await prime_db.add(live_delegation(), ORG_T)
    a = action("person.terminate")
    decision = await PrimeService(prime_db).decide(a, ORG_T)

    assert decision.outcome is Outcome.REFUSE
    entries = await chain.read_entries()
    assert [e["action"] for e in entries] == [
        "prime.delegation.grant", "prime.request", "prime.decision"]
    assert entries[2]["payload"]["outcome"] == "REFUSE"
    assert entries[2]["payload"]["action_id"] == a.id
    assert (await chain.verify()).entries_checked == 3  # grant + request + decision


@pytest.mark.asyncio
async def test_decide_refuses_after_revocation_and_with_no_delegation(prime_db):
    service = PrimeService(prime_db)
    assert (await service.decide(action(), ORG_T)).outcome is Outcome.REFUSE   # nothing stored
    d = live_delegation()
    await prime_db.add(d, ORG_T)
    assert (await service.decide(action(), ORG_T)).outcome is Outcome.EXECUTE
    await prime_db.revoke(d.id, by="ceo", now=datetime.now(timezone.utc))
    assert (await service.decide(action(), ORG_T)).outcome is Outcome.REFUSE
    # 1 grant + 1 revoke + 3 decisions x (request + decision)
    assert (await chain.verify()).entries_checked == 8


@pytest.mark.asyncio
async def test_decide_fails_closed_and_still_logs_when_delegations_cannot_be_loaded(prime_db):
    class BrokenRepository(DelegationRepository):
        async def for_grantor(self, grantor):
            raise ConnectionError("db down")

    decision = await PrimeService(BrokenRepository()).decide(action(), ORG_T)
    assert decision.outcome is Outcome.REFUSE
    assert [e["action"] for e in await chain.read_entries()] == ["prime.request", "prime.decision"]


# ── HTTP router: a person can only see and revoke their own delegations ───────

@pytest.mark.asyncio
async def test_router_isolates_delegations_between_users(prime_db):
    from fastapi import HTTPException
    from aether_os.gateway.routers import prime_router as pr

    alice, bob = {"user_id": "alice", "org_id": ORG_T}, {"user_id": "bob", "org_id": ORG_T}
    now = datetime.now(timezone.utc)
    body = pr.DelegationIn(scope=["leave.approve"], autonomy=3, valid_from=now,
                           valid_until=now + timedelta(days=2), deputy="deputy@example.test")
    created = await pr.create_delegation(body, user=alice)

    assert (await pr.list_delegations(user=bob))["delegations"] == []
    with pytest.raises(HTTPException) as exc:           # Bob cannot revoke Alice's
        await pr.revoke_delegation(created["id"], user=bob)
    assert exc.value.status_code == 404
    assert (await pr.list_delegations(user=alice))["delegations"][0]["state"] == "active"

    assert (await pr.check_action(pr.ActionIn(type="leave.approve"), user=alice))["outcome"] == "EXECUTE_AND_NOTIFY"
    assert (await pr.check_action(pr.ActionIn(type="leave.approve"), user=bob))["outcome"] == "REFUSE"
    assert all(e["payload"].get("on_behalf_of") != "alice" and e["actor"] != "alice"
               for e in (await pr.activity(user=bob))["entries"])

    with pytest.raises(HTTPException) as exc:           # NEVER types cannot be delegated
        await pr.create_delegation(body.model_copy(update={"scope": ["person.hire"]}), user=alice)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:           # API keys are not people
        await pr.list_delegations(user={"org_id": "o", "sub": "api_key"})
    assert exc.value.status_code == 403
