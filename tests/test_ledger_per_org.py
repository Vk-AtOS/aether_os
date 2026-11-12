"""Per-organisation audit chains, the link to the legacy chain, and the back-fill of
old audit_log rows. Real chain code on a throwaway SQLite file."""
from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import delete, select, update

from aether_os.core.audit import backfill, chain
from aether_os.core.audit.chain import AuditChainEntry
from aether_os.core.models import AuditLog
from aether_os.tests.ledger_helpers import add_legacy_rows, anchor_env, ledger_sqlite  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_each_org_gets_its_own_gap_free_chain(ledger_sqlite):
    for i in range(3):
        for org in ("org-a", "org-b"):
            await chain.append("u", "thing", {"org_id": org, "i": i})
    await chain.append("sys", "boot", {})                      # no org: platform chain
    await chain.append("sys", "policy.denied", {"org_id": "-"})  # sentinel: platform chain

    entries = await chain.read_entries()
    by_chain = {}
    for e in entries:
        by_chain.setdefault(e["chain_id"], []).append(e)
    assert set(by_chain) == {"org-a", "org-b", chain.PLATFORM_CHAIN}
    for rows in by_chain.values():
        assert [e["chain_seq"] for e in rows] == list(range(1, len(rows) + 1))
        assert rows[0]["prev_hash"] == chain.GENESIS_HASH   # legacy chain is empty here
        for prev, cur in zip(rows, rows[1:]):
            assert cur["prev_hash"] == prev["entry_hash"]

    for org in ("org-a", "org-b"):
        r = await chain.verify(org)
        assert r.ok and r.entries_checked == 3 and r.head_seq == 3, r
    assert (await chain.verify(None)).entries_checked == 2
    assert (await chain.verify()).entries_checked == 8


async def test_reserved_chain_names_are_refused(ledger_sqlite):
    for bad in (chain.LEGACY_CHAIN, chain.PLATFORM_CHAIN, "x" * 65):
        with pytest.raises(ValueError):
            await chain.append("u", "thing", {"org_id": bad})


async def test_new_chains_continue_the_legacy_chain(ledger_sqlite):
    tail = await add_legacy_rows(ledger_sqlite, 3)
    await chain.append("u", "thing", {"org_id": "org-a"})
    await chain.append("u", "thing", {"org_id": "org-b"})
    first = {e["chain_id"]: e for e in await chain.read_entries() if e["chain_seq"] == 1}
    assert first["org-a"]["prev_hash"] == tail == first["org-b"]["prev_hash"]
    assert (await chain.genesis()) == {"legacy_tail_seq": 3, "legacy_tail_hash": tail}
    assert (await chain.verify()).ok and (await chain.verify()).entries_checked == 5
    assert (await chain.verify("org-a", full=True)).ok

    # Cutting the legacy tail breaks the first link of every new chain.
    async with ledger_sqlite() as s:
        await s.execute(delete(AuditChainEntry).where(AuditChainEntry.seq == 3))
        await s.commit()
    r = await chain.verify("org-a", full=True)
    assert not r.ok and "prev_hash" in r.reason
    assert not (await chain.verify()).ok


async def test_moving_an_entry_to_another_orgs_chain_is_detected(ledger_sqlite):
    await chain.append("u", "thing", {"org_id": "org-a"})
    await chain.append("u", "thing", {"org_id": "org-a"})
    e = (await chain.read_entries())[0]
    async with ledger_sqlite() as s:        # relabel org-a's first entry as org-b's
        await s.execute(update(AuditChainEntry).where(AuditChainEntry.seq == e["seq"])
                        .values(chain_id="org-b"))
        await s.commit()
    rb = await chain.verify("org-b", full=True)
    assert not rb.ok and "does not belong" in rb.reason
    assert not (await chain.verify("org-a", full=True)).ok   # org-a now starts at entry 2


async def test_entry_link_is_the_previous_entry_of_the_same_chain(ledger_sqlite):
    await chain.append("u", "a1", {"org_id": "org-a"})
    await chain.append("u", "b1", {"org_id": "org-b"})
    await chain.append("u", "a2", {"org_id": "org-a"})
    a1, b1, a2 = await chain.read_entries()
    link = await chain.entry_link(a2["seq"])
    assert link["previous"] == {"seq": a1["seq"], "entry_hash": a1["entry_hash"]}
    assert link["link_ok"] and link["hash_ok"]
    assert (await chain.entry_link(b1["seq"]))["previous"] == {"seq": None, "entry_hash": chain.GENESIS_HASH}
    assert await chain.entry_link(999) is None


async def _old_row(sf, rid, org, ts, ip="", meta=None, prev_hash=None):
    async with sf() as s:
        s.add(AuditLog(id=rid, org_id=org, user_id="u-" + rid, action="login", resource_type="session",
                       resource_id="s", log_metadata=json.dumps(meta or {}), ip_address=ip,
                       created_at=ts, prev_hash=prev_hash))
        await s.commit()


async def test_backfill_imports_unchained_rows_once_in_order(ledger_sqlite):
    now = time.time()
    await _old_row(ledger_sqlite, "r2", "org-a", now - 50, ip="10.1.1.1", meta={"email": "a@x.test"},
                   prev_hash="f" * 64)                       # old non-verifiable hash scheme
    await _old_row(ledger_sqlite, "r1", "org-a", now - 90)   # older, written first
    await _old_row(ledger_sqlite, "r3", "-", now - 10, meta={"chain_linked": False})
    linked = await chain.append("u", "login", {"org_id": "org-a"})
    await _old_row(ledger_sqlite, "r4", "org-a", now, prev_hash=linked.entry_hash)  # already chained

    assert await backfill.backfill() == 3
    assert await backfill.backfill() == 0                    # idempotent

    imported = [e for e in await chain.read_entries() if "imported" in e["payload"]]
    assert [e["payload"]["imported"]["audit_log_id"] for e in imported] == ["r1", "r2", "r3"]
    assert all(e["payload"]["imported"]["content_chained_at_write"] is False for e in imported)
    assert imported[0]["timestamp"] == pytest.approx(now - 90)
    assert [e["chain_id"] for e in imported] == ["org-a", "org-a", chain.PLATFORM_CHAIN]
    text = json.dumps(imported)
    assert "10.1.1.1" not in text and "a@x.test" not in text   # pseudonymised on the way in
    assert imported[1]["payload"]["ip_address"]["subject"].startswith("sub_")
    assert (await chain.verify()).ok
    async with ledger_sqlite() as s:
        assert len((await s.execute(select(backfill.AuditBackfill))).scalars().all()) == 3
