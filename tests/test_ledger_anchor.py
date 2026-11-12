"""Signed checkpoints: key handling, incremental verify, and detection of a cut or
rewritten tail, including when the attacker also removes the checkpoint rows."""
from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from aether_os.core.audit import anchor, chain, checkpoints
from aether_os.core.audit.chain import AuditChainEntry
from aether_os.core.audit.checkpoints import AuditCheckpoint
from aether_os.gateway.routers import ledger_anchor_router as api
from aether_os.tests.gateway_env import gateway_env
from aether_os.tests.ledger_helpers import anchor_env, ledger_sqlite  # noqa: F401

pytestmark = pytest.mark.asyncio
ORG = "org-a"
ADMIN = {"user_id": "carol", "org_id": ORG, "role": "admin"}
MEMBER = {"user_id": "alice", "org_id": ORG, "role": "member"}


async def _fill(n, org=ORG):
    for i in range(n):
        await chain.append("u", "thing", {"org_id": org, "i": i})


async def _cut_tail(sf, org, keep):
    async with sf() as s:
        await s.execute(delete(AuditChainEntry).where(AuditChainEntry.chain_id == org,
                                                      AuditChainEntry.chain_seq > keep))
        await s.commit()


async def test_key_is_created_owner_only_and_a_readable_key_is_refused(anchor_env):
    assert checkpoints.signing_key(create=False) is None
    key = checkpoints.signing_key(create=True)
    path = checkpoints.key_path()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert checkpoints.key_id(key) == checkpoints.key_id(checkpoints.signing_key())
    os.chmod(path, 0o644)
    with pytest.raises(PermissionError):
        checkpoints.signing_key()


async def test_anchor_signs_stores_and_appends_to_the_file(ledger_sqlite):
    await _fill(3)
    cp = await anchor.anchor_chain(ORG)
    assert cp["chain_seq"] == 3 and checkpoints.signature_ok(cp)
    assert await anchor.anchor_chain(ORG) == cp          # same head: no second checkpoint
    lines = checkpoints.anchor_file_path().read_text().splitlines()
    assert [json.loads(x) for x in lines] == [cp]
    assert stat.S_IMODE(os.stat(checkpoints.anchor_file_path()).st_mode) == 0o600
    for field, value in (("chain_seq", 2), ("head_hash", "0" * 64), ("chain_id", "org-b")):
        assert not checkpoints.signature_ok({**cp, field: value})
    assert await anchor.anchor_chain("no-such-org") is None


async def test_verify_is_incremental_from_the_last_checkpoint(ledger_sqlite):
    await _fill(5)
    await anchor.anchor_chain(ORG)
    await _fill(3)
    inc = await chain.verify(ORG)
    assert inc.ok and inc.entries_checked == 3 and inc.head_seq == 8 and inc.checkpoint_seq == 5
    full = await chain.verify(ORG, full=True)
    assert full.ok and full.entries_checked == 8


async def test_cut_tail_is_reported_as_truncation(ledger_sqlite):
    await _fill(5)
    await anchor.anchor_chain(ORG)
    await _cut_tail(ledger_sqlite, ORG, keep=3)
    r = await chain.verify(ORG)
    assert not r.ok and r.truncated and "truncated" in r.reason and r.head_seq == 3
    assert (await chain.verify()).ok   # the structural walk alone cannot see it


async def test_rewritten_tail_is_reported_as_divergence(ledger_sqlite):
    await _fill(5)
    await anchor.anchor_chain(ORG)
    await _cut_tail(ledger_sqlite, ORG, keep=3)
    await _fill(4)                     # history re-grown past the checkpoint
    for full in (False, True):
        r = await chain.verify(ORG, full=full)
        assert not r.ok and "signed checkpoint" in r.reason and not r.truncated


async def test_customer_copy_and_anchor_file_catch_a_cut_that_also_removed_checkpoints(ledger_sqlite):
    await _fill(5)
    await anchor.anchor_chain(ORG)
    kept = (await anchor.export(ORG))["checkpoints"][-1]      # the customer's copy
    async with ledger_sqlite() as s:                          # attacker: drop rows and checkpoints
        await s.execute(delete(AuditCheckpoint))
        await s.commit()
    await _cut_tail(ledger_sqlite, ORG, keep=2)
    assert (await chain.verify(ORG)).ok                       # the database alone is fooled
    r = await chain.verify(ORG, checkpoint=kept)
    assert not r.ok and r.truncated
    problems = await anchor.check_file()
    assert [p["chain_id"] for p in problems] == [ORG] and problems[0]["truncated"]


async def test_forged_checkpoint_is_refused(ledger_sqlite):
    await _fill(2)
    cp = await anchor.anchor_chain(ORG)
    r = await chain.verify(ORG, checkpoint={**cp, "chain_seq": 9})
    assert not r.ok and "not validly signed" in r.reason


async def test_broken_chain_is_never_anchored(ledger_sqlite):
    await _fill(3)
    await chain.append("u", "thing", {"org_id": "org-b"})
    async with ledger_sqlite() as s:
        await s.execute(delete(AuditChainEntry).where(AuditChainEntry.chain_id == ORG,
                                                      AuditChainEntry.chain_seq == 2))
        await s.commit()
    with pytest.raises(anchor.ChainBroken):
        await anchor.anchor_chain(ORG)
    summary = await anchor.anchor_all()
    assert summary["anchored"] == 1 and [b["chain_id"] for b in summary["broken"]] == [ORG]
    async with ledger_sqlite() as s:
        assert (await s.execute(select(AuditCheckpoint.chain_id))).scalars().all() == ["org-b"]


async def test_checkpoint_rows_are_append_only(ledger_sqlite):
    await _fill(1)
    await anchor.anchor_chain(ORG)
    async with ledger_sqlite() as s:
        row = (await s.execute(select(AuditCheckpoint))).scalar_one()
        row.head_hash = "f" * 64
        with pytest.raises(RuntimeError, match="append-only"):
            await s.commit()


async def test_periodic_lifespan_anchors(ledger_sqlite, monkeypatch):
    await _fill(2)
    monkeypatch.setenv("AETHER_LEDGER_ANCHOR_INTERVAL", "0")
    async with anchor.periodic_lifespan(None):      # 0 = off
        await asyncio.sleep(0.05)
    assert await anchor.latest(ORG) is None
    monkeypatch.setattr(anchor, "interval_seconds", lambda: 0.02)
    async with anchor.periodic_lifespan(None):
        for _ in range(100):
            if await anchor.latest(ORG):
                break
            await asyncio.sleep(0.02)
    assert (await anchor.latest(ORG))["chain_seq"] == 2


async def test_router_scopes_to_the_callers_org(ledger_sqlite):
    await _fill(2)
    await _fill(1, org="org-b")
    with pytest.raises(HTTPException) as e:
        await api.anchor_now(user=MEMBER)
    assert e.value.status_code == 403
    made = await api.anchor_now(user=ADMIN)
    assert made["chain_id"] == ORG and made["checkpoint"]["chain_seq"] == 2
    latest = await api.latest_checkpoint(user=MEMBER)
    assert latest["checkpoint"] == made["checkpoint"] and "PUBLIC KEY" in latest["public_key_pem"]
    exported = await api.export_checkpoints(user=ADMIN)
    assert exported["checkpoints"] == [made["checkpoint"]] and exported["genesis"]["legacy_tail_seq"] == 0
    ok = await api.verify_chain(api.VerifyIn(full=True), user=ADMIN)
    assert ok["ok"] and ok["entries_checked"] == 2
    kept = api.CheckpointIn(**made["checkpoint"])
    assert (await api.verify_chain(api.VerifyIn(checkpoint=kept), user=ADMIN))["ok"]
    other = api.CheckpointIn(**{**made["checkpoint"], "chain_id": "org-b"})
    with pytest.raises(HTTPException) as e:
        await api.verify_chain(api.VerifyIn(checkpoint=other), user=ADMIN)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await api.check_anchor_file(user=ADMIN)
    assert e.value.status_code == 403
    assert (await api.check_anchor_file(user={**ADMIN, "role": "superadmin"}))["ok"]


async def test_gateway_runs_the_anchor_lifespan(tmp_path, monkeypatch):
    """The registration line in gateway/api.py mounts the router and its lifespan."""
    started = []

    async def _record(interval):
        started.append(interval)

    def _run_gateway():  # TestClient runs its own event loop, so off this one
        with gateway_env(tmp_path) as env:
            assert env.client.get("/prime/ledger/anchor/latest").status_code == 401
            assert env.client.get("/prime/ledger/anchor/latest", headers=env.auth).status_code == 200

    monkeypatch.setattr(anchor, "run_periodically", _record)
    monkeypatch.setenv("AETHER_LEDGER_ANCHOR_INTERVAL", "3600")
    monkeypatch.setenv("AETHER_LEDGER_SIGNING_KEY", str(tmp_path / "ledger.pem"))
    await asyncio.to_thread(_run_gateway)
    assert started == [3600]


# ── a problem that names no chain counts against every chain ─────────────────

async def test_missing_anchor_file_with_checkpoints_is_a_problem(ledger_sqlite, monkeypatch):
    await _fill(2)
    await anchor.anchor_chain(ORG)
    checkpoints.anchor_file_path().unlink()
    problems = await anchor.check_file()
    assert any(p["chain_id"] is None and "missing" in p["reason"] for p in problems)
    monkeypatch.setattr(anchor, "_last_file_check", None)
    await anchor.run_file_check()
    other = anchor.last_file_check("org-zzz")                  # a chain that has no problem of its own
    assert not other["ok"] and other["problems"] == [{"chain_id": "org-zzz", "reason": anchor.GENERIC_REASON}]
    assert "missing" in anchor.last_file_check("org-zzz", detail=True)["problems"][0]["reason"]


async def test_missing_anchor_file_without_checkpoints_is_fine(ledger_sqlite):
    assert await anchor.check_file() == []


async def test_unreadable_anchor_file_fails_every_chain(ledger_sqlite, monkeypatch):
    await _fill(1)
    await anchor.anchor_chain(ORG)
    monkeypatch.setattr(anchor, "_last_file_check", None)
    os.chmod(checkpoints.anchor_file_path(), 0)
    try:
        res = await anchor.run_file_check()
    finally:
        os.chmod(checkpoints.anchor_file_path(), 0o600)
    if os.geteuid() == 0:
        pytest.skip("root reads anything")
    assert not res["ok"]
    for cid in (ORG, "org-b"):
        view = anchor.last_file_check(cid)
        assert not view["ok"] and view["problems"][0]["reason"] == anchor.GENERIC_REASON
    assert "could not run" in anchor.last_file_check(ORG, detail=True)["problems"][0]["reason"]


def test_a_chain_problem_only_affects_its_own_chain(monkeypatch):
    monkeypatch.setattr(anchor, "_last_file_check", {"at": 1.0, "ok": False, "problems": [
        {"chain_id": "a", "reason": "cut"}]})
    assert not anchor.last_file_check("a")["ok"]
    assert anchor.last_file_check("b") == {"at": 1.0, "ok": True, "problems": []}
