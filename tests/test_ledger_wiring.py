"""Wiring of the per-organisation ledger into the product: org-scoped /activity and
/verify, erasure on account and organisation deletion, exports that understand the
pseudonyms, the back-fill operations, the scheduled anchor-file check, and no raw
personal data in logs. Real chain code on a throwaway SQLite file; identity injected."""
from __future__ import annotations

import logging

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import aether_os.core.db as db
from aether_os.core.audit import anchor, backfill, chain, deletion, subjects
from aether_os.core.audit.ledger import DecisionLedger
from aether_os.core.models import APIKey, AuditLog, Organisation, Run, User
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers import (
    account_router, account_settings_router, admin_platform_router, admin_router,
    ledger_anchor_router, ledger_ops_router, prime_router,
)
from aether_os.tests.ledger_helpers import anchor_env, ledger_sqlite  # noqa: F401

pytestmark = pytest.mark.asyncio
A, B = "org-a", "org-b"
EMAIL, IP = "Alice@Example.test", "203.0.113.9"
ALICE = {"user_id": "u-alice", "org_id": A, "role": "owner"}
MEMBER = {"user_id": "u-mem", "org_id": A, "role": "member"}
BOB = {"user_id": "u-bob", "org_id": B, "role": "admin"}
ROOT = {"user_id": "u-root", "org_id": A, "role": "superadmin"}


@pytest_asyncio.fixture
async def world(ledger_sqlite, monkeypatch):
    async with db.get_engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(
            c, tables=[t.__table__ for t in (Organisation, User, APIKey, Run)]))
    async with ledger_sqlite() as s:
        s.add_all([Organisation(id=o, name=o, slug=o) for o in (A, B)])
        await s.flush()
        s.add_all([User(id="u-alice", org_id=A, email=EMAIL, password_hash="x", role="owner"),
                   User(id="u-mem", org_id=A, email="mem@example.test", password_hash="x"),
                   User(id="u-bob", org_id=B, email="bob@example.test", password_hash="x", role="admin")])
        await s.commit()

    async def no_redis(_uid, keep_family=None):
        return None
    monkeypatch.setattr(account_router, "revoke_user_sessions", no_redis)
    who = {"user": ALICE}
    app = FastAPI()
    for m in (prime_router, ledger_anchor_router, ledger_ops_router, account_router,
              account_settings_router, admin_router, admin_platform_router):
        app.include_router(m.router)
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
        http.who = who
        yield http


async def _login(org=A, user="u-alice", email=EMAIL, ip=IP):
    await DecisionLedger().async_log_audit_event(
        org, user, "login_failed", metadata={"email": email}, ip_address=ip)


# ── item 1: isolation ────────────────────────────────────────────────────────

async def test_activity_reads_only_the_callers_org(world):
    for org in (A, B):  # the same person id exists in both orgs' chains
        await chain.append("u-alice", "prime.decision", {"org_id": org, "on_behalf_of": "u-alice", "n": org})
    await chain.append("u-alice", "login", {"org_id": A})  # not a prime.* event
    got = (await world.get("/prime/activity")).json()["entries"]
    assert [e["payload"]["n"] for e in got] == [A]
    world.who["user"] = {**ALICE, "org_id": None}
    assert (await world.get("/prime/activity")).status_code == 403


async def test_verify_checks_only_the_callers_chain_and_full_is_admin_only(world):
    for i in range(3):
        await chain.append("u", "x", {"org_id": A, "i": i})
        await chain.append("u", "x", {"org_id": B, "i": i})
    async with db.get_session_factory()() as s:  # break org-b by raw SQL (the ORM refuses updates)
        await s.execute(text("UPDATE audit_chain SET actor='forged' WHERE chain_id=:c AND chain_seq=2"), {"c": B})
        await s.commit()
    ok = (await world.get("/prime/ledger/verify")).json()
    assert ok["ok"] and ok["entries_checked"] == 3 and ok["chain_id"] == A and ok["head_seq"] == 3
    world.who["user"] = BOB
    assert not (await world.get("/prime/ledger/verify", params={"full": True})).json()["ok"]
    world.who["user"] = MEMBER
    assert (await world.get("/prime/ledger/verify")).json()["ok"]
    assert (await world.get("/prime/ledger/verify", params={"full": True})).status_code == 403
    world.who["user"] = {**MEMBER, "org_id": None}
    assert (await world.get("/prime/ledger/verify")).status_code == 403


# ── item 2: erasure on deletion ──────────────────────────────────────────────

async def test_account_deletion_erases_the_person_and_can_be_retried(world, monkeypatch):
    await _login()
    await _login(user="u-mem", email="mem@example.test", ip="198.51.100.1")
    real = subjects.erase_subject

    async def broken(*a, **k):
        raise RuntimeError(f"db down for {EMAIL}")
    monkeypatch.setattr(subjects, "erase_subject", broken)
    r = await world.delete("/account")
    assert r.status_code == 503 and EMAIL not in r.text and "retry" in r.json()["detail"]
    async with db.get_session_factory()() as s:      # nothing was deleted: still a live account
        u = await s.get(User, "u-alice")
        assert u.is_active and u.email == EMAIL

    monkeypatch.setattr(subjects, "erase_subject", real)
    assert (await world.delete("/account")).status_code == 200
    async with db.get_session_factory()() as s:
        assert not (await s.get(User, "u-alice")).is_active
    logs = {r["user_id"]: r for r in (await DecisionLedger().async_get_audit_logs(A))["logs"]
            if r["action"] == "login_failed"}
    assert logs["u-alice"]["metadata"]["email"] == subjects.ERASED and logs["u-alice"]["ip_address"] == subjects.ERASED
    assert logs["u-mem"]["metadata"]["email"] == "mem@example.test"   # others untouched
    erasures = [e for e in await chain.read_entries() if e["action"] == "audit.subject_erased"]
    assert erasures and all(set(e["payload"]) == {"org_id", "subject", "kind"} for e in erasures)
    assert EMAIL not in str(erasures) and IP not in str(erasures)
    again = await deletion.erase_person(A, "u-alice", by="u-alice")   # idempotent
    assert again == {"subjects_erased": 0}
    assert (await chain.verify(A, full=True)).ok


async def test_org_deletion_erases_the_org_and_a_failure_is_retryable(world, monkeypatch):
    await _login()
    await _login(org=B, user="u-bob", email="bob@example.test")
    real = subjects.erase_org

    async def broken(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(subjects, "erase_org", broken)
    r = await world.delete("/org")
    assert r.status_code == 503 and "POST /prime/ledger/erasure/retry" in r.json()["detail"]
    async with db.get_session_factory()() as s:   # the deletion itself stands
        assert (await s.get(Organisation, A)).is_deleted
    assert await deletion.pending_org_erasures() == [A]

    monkeypatch.setattr(subjects, "erase_org", real)
    world.who["user"] = ALICE
    assert (await world.post("/prime/ledger/erasure/retry")).status_code == 403   # owner is not superadmin
    world.who["user"] = ROOT
    assert (await world.post("/prime/ledger/erasure/retry")).json() == {"erased": [A], "failed": []}
    assert (await world.post("/prime/ledger/erasure/retry")).json() == {"erased": [], "failed": []}
    assert await deletion.org_erased(A) and not await deletion.org_erased(B)
    assert (await chain.verify(A, full=True)).ok
    deleted = [e for e in await chain.read_entries() if e["action"] == "org.deleted"]
    assert [e["seq"] for e in deleted] < [e["seq"] for e in await chain.read_entries() if e["action"] == "audit.org_erased"]
    shown = (await DecisionLedger().async_get_audit_logs(A))["logs"]
    assert {r["metadata"].get("email") for r in shown if r["action"] == "login_failed"} == {subjects.ERASED}


async def test_data_export_holds_only_the_callers_own_entries(world):
    await _login()
    await _login(user="u-mem", email="mem@example.test")
    body = (await world.get("/account/data-export")).json()
    assert {r["user_id"] for r in body["audit_logs"]} == {"u-alice"}


# ── item 4: pseudonyms in exports ────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/admin/audit/export.csv", "/admin/audit-logs/export"])
async def test_csv_exports_show_the_subject_not_the_reference(world, path):
    await _login()
    ref = (await chain.read_entries())[0]["payload"]["ip_address"]["subject"]
    text_ = (await world.get(path)).text
    assert IP in text_ and ref not in text_ and "hmac" not in text_
    await subjects.erase_subject(A, EMAIL, by="u-alice")
    await subjects.erase_subject(A, IP, by="u-alice")
    text_ = (await world.get(path)).text
    # (user_email is the account's own record, not audit data; the audit columns are erased)
    assert IP not in text_ and ref not in text_ and subjects.ERASED in text_


# ── item 3: back-fill and anchor-file check ──────────────────────────────────

async def _old_rows(sf):
    rows = [("r1", A, '{"email": "old@x.test"}', "10.0.0.7"), ("r2", A, None, "self"), ("r3", B, "{}", None),
            ("r4", "o" * 70, "{}", None), ("r5", A, "free text, not json", None)]
    async with sf() as s:
        for i, (rid, org, meta, ip) in enumerate(rows):
            s.add(AuditLog(id=rid, org_id=org, user_id="u", action="old", resource_type="", resource_id="",
                           log_metadata=meta, ip_address=ip, created_at=10.0 + i))
        await s.commit()


async def test_backfill_dry_run_reports_and_writes_nothing(world, ledger_sqlite):
    await _old_rows(ledger_sqlite)
    world.who["user"] = ALICE
    assert (await world.post("/prime/ledger/backfill")).status_code == 403
    world.who["user"] = ROOT
    rep = (await world.post("/prime/ledger/backfill", params={"batch": 2})).json()   # dry_run is the default
    assert rep["dry_run"] and rep["pending_before"] == 5 and rep["batches"] == 3 and rep["imported"] == 0
    assert rep["by_chain"] == {A: 3, B: 1}
    assert rep["problems"] == {"org_id_cannot_name_a_chain": 1, "metadata_not_json": 1} and not rep["clean"]
    assert rep["remaining"] == 5 and await chain.read_entries() == []
    async with ledger_sqlite() as s:
        assert (await s.execute(select(subjects.AuditSubject))).first() is None   # no pseudonym created


async def test_backfill_run_is_batched_resumable_idempotent_and_ledgered(world, ledger_sqlite):
    await _old_rows(ledger_sqlite)
    world.who["user"] = ROOT
    first = (await world.post("/prime/ledger/backfill", params={"dry_run": False, "batch": 2, "max_batches": 1})).json()
    assert first["imported"] == 2 and first["remaining"] == 3
    rest = (await world.post("/prime/ledger/backfill", params={"dry_run": False, "batch": 2})).json()
    assert rest["imported"] == 2 and rest["failed"] == 1 and rest["remaining"] == 1   # the unchainable org
    assert (await backfill.run(2, dry_run=True))["pending_before"] == 1
    imported = [e for e in await chain.read_entries() if e["action"] == "old"]
    assert len(imported) == 4 and "old@x.test" not in str(imported)
    assert any(e["action"] == "audit.backfill_run" for e in await chain.read_entries())
    assert (await chain.verify(A, full=True)).ok


async def test_anchor_file_check_is_scheduled_and_exposed_per_chain(world, monkeypatch):
    calls = []

    async def fake_check():
        calls.append(1)
        return [{"chain_id": A, "reason": "cut", "truncated": True},
                {"chain_id": B, "reason": "other org"}]
    monkeypatch.setattr(anchor, "check_file", fake_check)
    monkeypatch.setattr(anchor, "_last_file_check", None)
    assert (await world.get("/prime/ledger/anchor/latest")).json()["file_check"] is None
    monkeypatch.setattr(anchor, "interval_seconds", lambda: 0.02)
    async with anchor.periodic_lifespan(None):
        for _ in range(100):
            if calls:
                break
            await anchor.asyncio.sleep(0.02)
    assert calls
    mine = (await world.get("/prime/ledger/anchor/latest")).json()["file_check"]
    assert not mine["ok"] and [p["chain_id"] for p in mine["problems"]] == [A]
    world.who["user"] = {**BOB, "org_id": "org-c"}
    other = (await world.get("/prime/ledger/anchor/latest")).json()["file_check"]
    assert other["ok"] and other["problems"] == []
    world.who["user"] = ROOT
    assert len((await world.post("/prime/ledger/anchor/check-file")).json()["problems"]) == 2


async def test_a_file_check_that_cannot_run_is_not_a_pass(world, monkeypatch):
    async def boom():
        raise OSError("disk")
    monkeypatch.setattr(anchor, "check_file", boom)
    res = await anchor.run_file_check()
    assert not res["ok"] and "OSError" in res["problems"][0]["reason"]


# ── logs never carry raw personal data ───────────────────────────────────────

async def test_integrity_error_paths_never_log_the_raw_value(world, monkeypatch, caplog):
    boom = IntegrityError("INSERT INTO audit_subjects (value) VALUES (?)", {"value": EMAIL}, Exception("dup"))
    assert EMAIL in str(boom)                      # the hazard is real
    real, hit = AsyncSession.commit, set()   # the pepper insert and the subject insert each collide once

    async def flaky(self):
        for obj in self.new:
            if isinstance(obj, (subjects.AuditOrgPepper, subjects.AuditSubject)) and type(obj) not in hit:
                hit.add(type(obj))
                raise boom
        return await real(self)
    monkeypatch.setattr(AsyncSession, "commit", flaky)
    with caplog.at_level(logging.DEBUG, logger="aether_os"):  # SQL echo of the real insert is not ours
        ref = await subjects.pseudonymise(A, "email", EMAIL)
        monkeypatch.setattr(subjects, "scrub", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(EMAIL)))
        await _login()
    assert ref["subject"].startswith("sub_") and len(hit) == 2
    assert "concurrently" in caplog.text and "IntegrityError" in caplog.text
    assert EMAIL not in caplog.text and EMAIL.lower() not in caplog.text and IP not in caplog.text
