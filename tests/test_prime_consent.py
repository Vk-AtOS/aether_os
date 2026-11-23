"""KAN-228: consent to Prime learning and the data rights. Default off; one switch per source plus an overall switch;
off stops collection and deletes what was learned; see, export and erase; the person alone may read their data
(admin 403); ledger entries for consent changes, exports, erasures and refusals; retention purge."""
# ruff: noqa: F811
from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, update

from aether_os.core import db
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers import prime_data_router
from aether_os.prime import consent, learned, retention
from aether_os.prime.learned import _now
from aether_os.prime.models import PrimeConsent, PrimeLearnedItem
from aether_os.tests.prime_helpers import (  # noqa: F401
    ADMIN, ALICE, API_KEY, CAROL, DAVE, MALLORY, MEMBER, ORG, OTHER_ORG, OUTSIDER, actions, svc,
)

pytestmark = pytest.mark.asyncio
V = consent.NOTICE_VERSION


@pytest_asyncio.fixture
async def http(svc):
    who = {"user": MEMBER}
    app = FastAPI()
    app.include_router(prime_data_router.router)
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        client.who = who
        yield client


async def turn(http, source, enabled, version=V):
    return await http.put("/prime/data/me/consent", json={"source": source, "enabled": enabled, "notice_version": version})


async def items(org=ORG, user=DAVE):
    async with db.get_session_factory()() as s:
        return (await s.execute(select(PrimeLearnedItem).where(
            PrimeLearnedItem.org_id == org, PrimeLearnedItem.user_id == user))).scalars().all()


async def seed(source="git", n=1, user=DAVE, summary="pushed a fix"):
    return [await learned.record(ORG, user, source, "commit", f"{summary} {i}") for i in range(n)]


# ── 1. default off ─────────────────────────────────────────────────────────────

async def test_everything_is_off_by_default_and_nothing_is_collected(http):
    assert not any([await consent.allowed(ORG, DAVE, s) for s in consent.SOURCES])
    assert await seed() == [None] and await items() == []
    got = (await http.get("/prime/data/me")).json()
    assert [(s["source"], s["enabled"], s["enabled_at"]) for s in got["switches"]] == \
        [(s, False, None) for s in consent.SWITCHES]
    assert got["counts"] == {s: 0 for s in consent.SOURCES} and got["newest"] == []
    assert got["notice_version"] == V and "performance reviews" in got["notice"]
    assert all(s["purpose"] for s in got["switches"]) and got["retention_days"] == retention.DEFAULT_RETENTION_DAYS


async def test_a_source_alone_or_the_overall_switch_alone_allows_nothing(http):
    await turn(http, "git", True)
    assert not await consent.allowed(ORG, DAVE, "git")
    await turn(http, "git", False)
    await turn(http, "all", True)
    assert not any([await consent.allowed(ORG, DAVE, s) for s in consent.SOURCES])


# ── 2. per-source on / off ─────────────────────────────────────────────────────

async def test_each_source_is_switched_separately_and_recorded(http):
    assert (await turn(http, "all", True)).status_code == 200
    got = (await turn(http, "git", True)).json()
    assert await consent.allowed(ORG, DAVE, "git")
    assert not await consent.allowed(ORG, DAVE, "jira") and not await consent.allowed(ORG, DAVE, "attendance")
    git = next(s for s in got["switches"] if s["source"] == "git")
    assert git["enabled"] and git["enabled_at"] and git["notice_version"] == V
    async with db.get_session_factory()() as s:
        row = await s.get(PrimeConsent, (ORG, DAVE, "git"))
    assert row.changed_by == DAVE and row.purpose == consent.PURPOSES["git"] and row.notice_version == V
    assert await seed("git") != [None] and await seed("jira") == [None]
    assert [i.source for i in await items()] == ["git"]
    entry = [e for e in await actions() if e == "prime.consent.change"]
    assert len(entry) == 2


async def test_turning_a_source_off_stops_collection_and_deletes_what_it_learned(http):
    for s in ("all", "git", "calendar"):
        await turn(http, s, True)
    await seed("git", 2)
    await seed("calendar", 1)
    got = (await turn(http, "git", False)).json()
    assert got["erased"] == 2 and not await consent.allowed(ORG, DAVE, "git")
    assert [i.source for i in await items()] == ["calendar"]
    assert next(s for s in got["switches"] if s["source"] == "git")["enabled_at"] is None
    assert await seed("git") == [None]                                 # collection stopped
    got = (await turn(http, "all", False)).json()                      # overall off: everything goes, every switch off
    assert got["erased"] == 1 and await items() == []
    assert not any(s["enabled"] for s in got["switches"])


async def test_switching_on_needs_the_current_notice(http):
    r = await turn(http, "all", True, version="1999-01-01")
    assert r.status_code == 409 and "notice" in r.json()["detail"]
    assert not (await http.get("/prime/data/me")).json()["switches"][0]["enabled"]
    assert (await turn(http, "nope", True)).status_code == 422


async def test_consent_holds_only_for_an_active_person_of_that_organisation(http):
    async with db.get_session_factory()() as s:          # rows naming a person of another organisation
        for src in ("all", "git"):
            s.add(PrimeConsent(org_id=ORG, user_id=MALLORY, source=src, enabled=True, changed_by=MALLORY,
                               changed_at=_now(), notice_version=V, purpose="x"))
        await s.commit()
    assert not await consent.allowed(ORG, MALLORY, "git") and not await consent.allowed(OTHER_ORG, MALLORY, "git")
    assert not await consent.allowed(ORG, DAVE, "keystrokes") and not await consent.allowed(None, DAVE, "git")
    with pytest.raises(PermissionError):
        await consent.set_switch(ORG, DAVE, "git", True, CAROL, V)    # nobody switches it on for someone else


# ── 3. see, export, erase ──────────────────────────────────────────────────────

async def test_the_screen_shows_counts_and_newest_items_pseudonymised(http):
    for s in ("all", "git", "jira"):
        await turn(http, s, True)
    await seed("git", 3)
    await learned.record(ORG, DAVE, "jira", "ticket", "KAN-1 assigned by alice@a.test",
                         {"email": "alice@a.test", "key": "KAN-1"})
    got = (await http.get("/prime/data/me")).json()
    assert got["counts"] == {"git": 3, "jira": 1, "calendar": 0, "attendance": 0}
    assert len(got["newest"]) == 4 and "alice@a.test" not in str(got)
    jira = next(i for i in got["newest"] if i["source"] == "jira")
    assert jira["data"]["key"] == "KAN-1" and jira["data"]["email"] != "alice@a.test"


async def test_export_returns_everything_and_is_ledgered(http):
    for s in ("all", "attendance"):
        await turn(http, s, True)
    await seed("attendance", 2, summary="checked in 09:30")
    got = (await http.get("/prime/data/me/export")).json()
    assert got["user_id"] == DAVE and got["org_id"] == ORG and len(got["learned"]) == 2
    assert {s["source"]: s["enabled"] for s in got["consent"]["switches"]}["attendance"] is True
    assert "prime.data.export" in await actions()


async def test_erase_one_source_then_all_keeps_consent_and_is_ledgered(http):
    for s in ("all", "git", "jira"):
        await turn(http, s, True)
    await seed("git", 2)
    await seed("jira", 1)
    assert (await http.delete("/prime/data/me/learned", params={"source": "git"})).json() == {"erased": 2, "source": "git"}
    assert [i.source for i in await items()] == ["jira"]
    assert (await http.delete("/prime/data/me/learned")).json() == {"erased": 1, "source": "all"}
    assert await items() == [] and await consent.allowed(ORG, DAVE, "git")
    assert (await http.delete("/prime/data/me/learned", params={"source": "screen"})).status_code == 422
    assert (await actions()).count("prime.data.erase") == 2


async def test_account_and_org_erasure_remove_items_and_consents(http):
    for s in ("all", "git"):
        await turn(http, s, True)
    await seed("git", 2)
    assert await learned.erase_person(ORG, DAVE) == 2
    async with db.get_session_factory()() as s:
        assert (await s.execute(select(PrimeConsent).where(PrimeConsent.user_id == DAVE))).first() is None
    await retention.set_retention_days(ORG, 90, CAROL)
    assert await learned.erase_org(ORG) == 0 and await retention.retention_days(ORG) == retention.DEFAULT_RETENTION_DAYS


# ── 5. access: the person alone ────────────────────────────────────────────────

@pytest.mark.parametrize("who", [ADMIN, {**ADMIN, "role": "owner"}, {**ADMIN, "role": "superadmin"}, MEMBER])
async def test_nobody_reads_or_changes_another_persons_data_whatever_the_role(http, who):
    http.who["user"] = {**MEMBER, "user_id": DAVE}
    for s in ("all", "git"):
        await turn(http, s, True)
    await seed("git", 1)
    http.who["user"] = who if who is not MEMBER else {**MEMBER, "user_id": ALICE, "role": "member"}
    target = DAVE
    calls = [http.get(f"/prime/data/{target}"), http.get(f"/prime/data/{target}/export"),
             http.delete(f"/prime/data/{target}/learned"),
             http.put(f"/prime/data/{target}/consent", json={"source": "git", "enabled": False, "notice_version": V})]
    for call in calls:
        r = await call
        assert r.status_code == 403 and "that person alone" in r.json()["detail"]
    assert len(await items()) == 1 and await consent.allowed(ORG, DAVE, "git")       # nothing changed
    assert (await actions()).count("prime.data.refuse") == 4
    assert "prime.data.export" not in await actions()


async def test_the_person_may_use_their_own_id_and_an_api_key_may_not_read_anyone(http):
    assert (await http.get(f"/prime/data/{DAVE}")).status_code == 200
    http.who["user"] = API_KEY
    assert (await http.get("/prime/data/me")).status_code == 403
    http.who["user"] = {**MEMBER, "org_id": None}
    assert (await http.get("/prime/data/me")).status_code == 403


# ── 6. retention and the purge job ─────────────────────────────────────────────

async def test_retention_setting_is_admin_only_bounded_and_ledgered(http):
    assert (await http.get("/prime/data-retention")).json()["retention_days"] == 365
    assert (await http.put("/prime/data-retention", json={"retention_days": 30})).status_code == 403
    http.who["user"] = ADMIN
    assert (await http.put("/prime/data-retention", json={"retention_days": 0})).status_code == 422
    assert (await http.put("/prime/data-retention", json={"retention_days": 30})).json() == {"retention_days": 30}
    assert await retention.retention_days(ORG) == 30 and await retention.retention_days(OTHER_ORG) == 365
    assert "prime.data.retention.change" in await actions()


async def test_purge_deletes_expired_items_per_organisation_and_withdrawn_sources(http):
    for s in ("all", "git", "jira"):
        await turn(http, s, True)
    await seed("git", 2)
    await seed("jira", 1)
    async with db.get_session_factory()() as s:      # one git item is 400 days old, the other 100
        rows = (await s.execute(select(PrimeLearnedItem).where(PrimeLearnedItem.source == "git"))).scalars().all()
        rows[0].learned_at = _now() - timedelta(days=400)
        rows[1].learned_at = _now() - timedelta(days=100)
        await s.commit()
    assert await retention.purge() == {"expired": 1, "withdrawn": 0}
    assert len(await items()) == 2
    await retention.set_retention_days(ORG, 30, CAROL)
    assert await retention.purge() == {"expired": 1, "withdrawn": 0}
    async with db.get_session_factory()() as s:      # consent withdrawn behind the switch's back (e.g. a race)
        await s.execute(update(PrimeConsent).where(PrimeConsent.source == "jira").values(enabled=False))
        await s.commit()
    assert await retention.purge() == {"expired": 0, "withdrawn": 1}
    assert await items() == [] and (await actions()).count("prime.data.purge") == 3
    assert await retention.purge() == {"expired": 0, "withdrawn": 0}


async def test_purge_interval_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("PRIME_LEARNING_PURGE_INTERVAL", "0")
    assert retention.interval_seconds() == 0
    async with retention.periodic_lifespan(None):    # 0 = off: starts and stops without a task
        pass
