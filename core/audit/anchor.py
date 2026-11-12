"""
AetherOS — anchoring the audit chains outside the database.

anchor_chain(chain_id) verifies a chain (incrementally, from its last checkpoint) and,
only if it checks out, signs its head (core/audit/checkpoints.py), appends the
checkpoint to the local anchor file and stores it in `audit_checkpoints`. The stored
checkpoints are also the starting point of the next incremental verify.

How a customer keeps the platform honest: download GET /prime/ledger/anchor/export
regularly and keep it. Each checkpoint is signed; the export carries the public key.
Later, POST any kept checkpoint to /prime/ledger/anchor/verify: if the chain was
shortened or rewritten behind it, verification fails, and the platform cannot produce
a new signature for a different history without the customer noticing that their
older checkpoint no longer matches.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from aether_os.core.audit import chain, checkpoints
from aether_os.core.audit.checkpoints import AuditCheckpoint
from aether_os.core.db import get_session_factory

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 600


class ChainBroken(Exception):
    def __init__(self, result: chain.ChainVerification) -> None:
        super().__init__(f"chain {result.chain_id} failed verification: {result.reason}")
        self.result = result


async def latest(cid: str) -> Optional[Dict[str, Any]]:
    async with get_session_factory()() as session:
        row = (await session.execute(
            select(AuditCheckpoint).where(AuditCheckpoint.chain_id == cid)
            .order_by(AuditCheckpoint.chain_seq.desc()).limit(1))).scalars().first()
    return checkpoints.to_dict(row) if row else None


async def anchor_chain(cid: str) -> Optional[Dict[str, Any]]:
    """Sign the verified head of one chain. None for an empty chain. Raises ChainBroken
    (and signs nothing) if the chain does not verify: a broken chain is never anchored."""
    result = await chain.verify_chain(cid)
    if not result.ok:
        raise ChainBroken(result)
    if result.head_seq == 0:
        return None
    current = await latest(cid)
    if current and current["chain_seq"] == result.head_seq:
        return current
    cp = checkpoints.sign(cid, result.head_seq, result.head_hash, time.time())
    # File first: a checkpoint in the file but not the table is still a true statement.
    checkpoints.append_to_file(cp)
    try:
        async with get_session_factory()() as session:
            session.add(AuditCheckpoint(**cp))
            await session.commit()
    except IntegrityError as e:  # another process anchored this same head first
        logger.info("chain %s head %s already anchored: %s", cid, result.head_seq, e)
        return await latest(cid)
    return cp


async def anchor_all() -> Dict[str, Any]:
    """Anchor every chain. A chain that fails verification is reported, not signed."""
    out: Dict[str, Any] = {"anchored": 0, "broken": []}
    for cid in await chain.chain_ids():
        try:
            if await anchor_chain(cid):
                out["anchored"] += 1
        except ChainBroken as e:
            logger.critical("AUDIT CHAIN BROKEN, not anchored: %s", e)
            out["broken"].append({"chain_id": cid, "reason": e.result.reason,
                                  "broken_seq": e.result.broken_seq})
    return out


async def export(cid: str) -> Dict[str, Any]:
    """Everything a customer needs to keep their own proof of this chain's history."""
    key = checkpoints.signing_key(create=True)
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(AuditCheckpoint).where(AuditCheckpoint.chain_id == cid)
            .order_by(AuditCheckpoint.chain_seq))).scalars().all()
    return {"chain_id": cid, "key_id": checkpoints.key_id(key),
            "public_key_pem": checkpoints.public_key_pem(key),
            "genesis": await chain.genesis(),
            "checkpoints": [checkpoints.to_dict(r) for r in rows]}


async def check_file() -> List[Dict[str, Any]]:
    """Verify every chain against the newest checkpoint for it in the local anchor
    file. Catches a database rollback that also removed checkpoint rows.

    ponytail: reads the whole file; split it per chain if it gets large.
    """
    path = checkpoints.anchor_file_path()
    newest: Dict[str, Dict[str, Any]] = {}
    problems: List[Dict[str, Any]] = []
    if not path.exists():
        async with get_session_factory()() as session:
            stored = (await session.execute(select(func.count()).select_from(AuditCheckpoint))).scalar_one()
        if stored:  # a missing file is only fine while there is nothing to compare against
            problems.append({"chain_id": None,
                             "reason": f"anchor file missing while {stored} checkpoints exist in the database"})
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for n, line in enumerate(lines, 1):
        try:
            cp = json.loads(line)
            cid, seq = str(cp["chain_id"]), int(cp["chain_seq"])
        except (ValueError, KeyError, TypeError) as e:
            problems.append({"chain_id": None, "reason": f"anchor file line {n} unreadable: {e}"})
            continue
        if seq >= newest.get(cid, {}).get("chain_seq", -1):
            newest[cid] = cp
    for cid, cp in sorted(newest.items()):
        result = await chain.verify_chain(cid, checkpoint=cp)
        if not result.ok:
            problems.append({"chain_id": cid, "reason": result.reason, "truncated": result.truncated})
    return problems


# The newest check_file() outcome of this process (None until the first run).
# ponytail: per process; with several workers each reports its own last run.
_last_file_check: Optional[Dict[str, Any]] = None


async def run_file_check() -> Dict[str, Any]:
    """check_file(), remembered as the last result. A failure to run the check is
    itself recorded as not ok, never as a clean pass."""
    global _last_file_check
    try:
        problems = await check_file()
        result = {"at": time.time(), "ok": not problems, "problems": problems}
    except Exception as e:  # unreadable file etc.: report it, the next run retries
        logger.error("ledger anchor file check could not run: %s", type(e).__name__)
        result = {"at": time.time(), "ok": False,
                  "problems": [{"chain_id": None, "reason": f"check could not run: {type(e).__name__}"}]}
    if result["problems"]:
        logger.critical("AUDIT ANCHOR FILE CHECK FAILED: %s", result["problems"])
    _last_file_check = result
    return result


GENERIC_REASON = "anchor file check incomplete"


def last_file_check(cid: Optional[str] = None, detail: bool = False) -> Optional[Dict[str, Any]]:
    """The last file-check result. Without `cid`, everything. With `cid`, that chain's
    problems (an organisation must not learn about other organisations' chains) plus any
    problem that names no chain (missing/unreadable file, the check itself failed): that
    affects EVERY chain, so none is reported ok. Its detail is shown only with `detail`
    (superadmin); everyone else gets a generic reason."""
    if _last_file_check is None:
        return None
    if cid is None:
        return _last_file_check
    mine = []
    for p in _last_file_check["problems"]:
        if p.get("chain_id") == cid:
            mine.append(p)
        elif p.get("chain_id") is None:
            mine.append(p if detail else {"chain_id": cid, "reason": GENERIC_REASON})
    return {"at": _last_file_check["at"], "ok": not mine, "problems": mine}


def interval_seconds() -> int:
    return int(os.environ.get("AETHER_LEDGER_ANCHOR_INTERVAL", DEFAULT_INTERVAL_SECONDS))


async def run_periodically(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            summary = await anchor_all()
            logger.info("ledger anchor run: %s", summary)
            await run_file_check()
        except Exception as e:  # the loop must survive a bad run; the next one retries
            logger.error("ledger anchor run failed: %s", e)


@asynccontextmanager
async def periodic_lifespan(_app: Any) -> AsyncIterator[None]:
    """Router lifespan: anchor every AETHER_LEDGER_ANCHOR_INTERVAL seconds (0 = off)."""
    interval = interval_seconds()
    task = asyncio.create_task(run_periodically(interval)) if interval > 0 else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
