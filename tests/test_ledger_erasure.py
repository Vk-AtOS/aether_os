"""Personal data out of the chain: pseudonymous references, erasure of a person and of
an organisation, and the read overlay for rows written before pseudonymisation."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from aether_os.core.audit import chain, subjects
from aether_os.core.audit.ledger import DecisionLedger
from aether_os.core.audit.subjects import AuditOrgPepper, AuditSubject
from aether_os.core.models import AuditLog
from aether_os.gateway.routers import ledger_anchor_router as api
from aether_os.tests.ledger_helpers import add_legacy_rows, anchor_env, ledger_sqlite  # noqa: F401

pytestmark = pytest.mark.asyncio
EMAIL, IP = "Alice@Example.test", "203.0.113.9"


async def _login(org="org-a", email=EMAIL, ip=IP):
    await DecisionLedger().async_log_audit_event(org, "u1", "login_failed", metadata={"email": email,
                                                 "reason": "bad"}, ip_address=ip)


async def test_chain_and_audit_log_hold_no_raw_email_or_ip(ledger_sqlite):
    await _login()
    await _login()            # same person again: same subject reference
    entries = await chain.read_entries()
    stored = json.dumps(entries)
    assert EMAIL not in stored and EMAIL.lower() not in stored and IP not in stored
    p1, p2 = entries[0]["payload"], entries[1]["payload"]
    assert p1["ip_address"] == p2["ip_address"] and p1["ip_address"]["subject"].startswith("sub_")
    assert len(p1["metadata"]["email"]["hmac"]) == 64 and p1["metadata"]["reason"] == "bad"
    async with ledger_sqlite() as s:
        rows = (await s.execute(select(AuditLog))).scalars().all()
    assert all(IP not in (r.ip_address or "") and EMAIL not in (r.log_metadata or "") for r in rows)

    shown = (await DecisionLedger().async_get_audit_logs("org-a"))["logs"]
    assert {(r["ip_address"], r["metadata"]["email"]) for r in shown} == {(IP, EMAIL)}
    assert (await chain.verify("org-a")).ok


async def test_references_are_per_organisation(ledger_sqlite):
    await _login("org-a")
    await _login("org-b")
    a, b = (e["payload"]["metadata"]["email"] for e in await chain.read_entries())
    assert a["subject"] != b["subject"] and a["hmac"] != b["hmac"]


async def test_erasing_a_person_keeps_the_chain_verifiable(ledger_sqlite):
    await _login()
    await _login("org-a", email="bob@example.test", ip="198.51.100.1")
    before = await chain.read_entries()
    out = await subjects.erase_subject("org-a", EMAIL.upper(), by="admin-1")
    assert out["matched"] and out["kind"] == "email"
    erasure = (await chain.read_entries())[-1]
    assert erasure["action"] == "audit.subject_erased" and erasure["actor"] == "admin-1"
    assert erasure["payload"] == {"org_id": "org-a", "subject": out["subject"], "kind": "email"}

    async with ledger_sqlite() as s:
        assert await s.get(AuditSubject, out["subject"]) is None
    shown = await subjects.overlay_entries("org-a", before)
    assert shown[0]["payload"]["metadata"]["email"] == subjects.ERASED
    assert shown[0]["payload"]["ip_address"] == IP                 # only the email was erased
    assert shown[1]["payload"]["metadata"]["email"] == "bob@example.test"
    logs = (await DecisionLedger().async_get_audit_logs("org-a"))["logs"]
    assert sorted(r["metadata"]["email"] for r in logs) == [subjects.ERASED, "bob@example.test"]
    r = await chain.verify("org-a", full=True)
    assert r.ok and r.entries_checked == 3

    by_id = await subjects.erase_subject("org-a", before[0]["payload"]["ip_address"]["subject"],
                                         by="admin-1")
    assert by_id["kind"] == "ip"
    with pytest.raises(LookupError):
        await subjects.erase_subject("org-b", by_id["subject"], by="x")
    with pytest.raises(ValueError):
        await subjects.erase_subject("org-a", "not personal", by="x")


async def test_old_rows_with_raw_values_are_hidden_after_erasure(ledger_sqlite):
    await add_legacy_rows(ledger_sqlite, 2)                       # payloads hold raw old@x.test / 10.0.0.7
    async with ledger_sqlite() as s:
        s.add(AuditLog(id="old", org_id="org-old", user_id="u", action="login", resource_type="",
                       resource_id="", log_metadata='{"email": "old@x.test"}', ip_address="10.0.0.7",
                       created_at=1.0))
        await s.commit()
    legacy = await chain.read_entries()
    assert (await subjects.overlay_entries("org-old", legacy))[0]["payload"]["ip_address"] == "10.0.0.7"

    out = await subjects.erase_subject("org-old", "10.0.0.7", by="admin")
    assert not out["matched"]                                     # never pseudonymised: tombstone only
    shown = await subjects.overlay_entries("org-old", legacy)
    assert {e["payload"]["ip_address"] for e in shown} == {subjects.ERASED}
    assert {e["payload"]["metadata"]["email"] for e in shown} == {"old@x.test"}
    row = (await DecisionLedger().async_get_audit_logs("org-old"))["logs"][0]
    assert row["ip_address"] == subjects.ERASED and row["metadata"]["email"] == "old@x.test"
    assert (await chain.read_entries())[:2] == legacy     # the stored rows are not rewritten
    assert (await chain.verify()).ok


async def test_erasing_an_organisation_removes_pepper_and_every_subject(ledger_sqlite):
    await add_legacy_rows(ledger_sqlite, 1)
    await _login("org-old")
    await _login("org-other")
    out = await subjects.erase_org("org-old", by="root")
    assert out["subjects_erased"] == 2
    async with ledger_sqlite() as s:
        assert await s.get(AuditOrgPepper, "org-old") is None
        assert {r.chain_id for r in (await s.execute(select(AuditSubject))).scalars()} == {"org-other"}
    shown = await subjects.overlay_entries("org-old", await chain.read_entries())
    old = [e for e in shown if e["payload"].get("org_id") == "org-old" and "ip_address" in e["payload"]]
    assert {e["payload"]["ip_address"] for e in old} == {subjects.ERASED}
    assert {e["payload"]["metadata"]["email"] for e in old} == {subjects.ERASED}
    assert (await chain.verify()).ok


async def test_pseudonymisation_failure_withholds_instead_of_storing_raw(ledger_sqlite, monkeypatch):
    async def _broken(*_a, **_k):
        raise RuntimeError("subjects table unavailable")
    monkeypatch.setattr(subjects, "pseudonymise", _broken)
    await _login()
    stored = json.dumps(await chain.read_entries())
    assert EMAIL not in stored and IP not in stored and subjects.WITHHELD in stored
    async with ledger_sqlite() as s:
        row = (await s.execute(select(AuditLog))).scalar_one()
    assert row.ip_address == subjects.WITHHELD and EMAIL not in row.log_metadata


async def test_erase_endpoint_is_admin_only_and_org_scoped(ledger_sqlite):
    await _login("org-a")
    member = {"user_id": "m", "org_id": "org-a", "role": "member"}
    admin = {"user_id": "a", "org_id": "org-a", "role": "admin"}
    for user, body in ((member, api.EraseIn(subject=EMAIL)),
                       (admin, api.EraseIn(subject=EMAIL, org_id="org-b")),
                       (admin, api.EraseIn(subject=EMAIL, platform=True))):
        with pytest.raises(HTTPException) as e:
            await api.erase_subject(body, user=user)
        assert e.value.status_code == 403
    for subject, code in (("nonsense", 400), ("sub_" + "0" * 32, 404)):
        with pytest.raises(HTTPException) as e:
            await api.erase_subject(api.EraseIn(subject=subject), user=admin)
        assert e.value.status_code == code
    done = await api.erase_subject(api.EraseIn(subject=EMAIL), user=admin)
    assert done["matched"]
    root = {"user_id": "r", "org_id": "org-z", "role": "superadmin"}
    assert (await api.erase_subject(api.EraseIn(subject=IP, org_id="org-a"), user=root))["matched"]
