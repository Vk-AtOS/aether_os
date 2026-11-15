"""
AetherOS — personal data kept out of the audit chains.

Chain entries never hold a raw email address or IP address. They hold a reference
{"subject": <random id>, "hmac": HMAC-SHA256(org pepper, value)}. The raw value lives
in `audit_subjects`, the per-organisation pepper in `audit_org_peppers`; both are
ordinary deletable tables outside the chain.

Erasure:
  erase_subject  deletes one subject row (and records a tombstone hmac), so entries
                 that reference it stay verifiable but resolve to "[erased]".
  erase_org      deletes the organisation's pepper and every subject row, after which
                 no reference of that organisation can be resolved or recomputed.
Rows written before this module existed still hold raw values (they cannot be
rewritten: append-only). `overlay()` hides erased values on every read instead.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.audit import chain
from aether_os.core.db import Base, get_session_factory

logger = logging.getLogger(__name__)

PII_METADATA_KEYS = ("email", "ip", "ip_address")
ERASED = "[erased]"
WITHHELD = "[withheld]"   # stored instead of a raw value when pseudonymising failed
_SUBJECT_PREFIX = "sub_"


class AuditOrgPepper(Base):
    __tablename__ = "audit_org_peppers"
    chain_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pepper: Mapped[str] = mapped_column(String(64), nullable=False)  # 32 random bytes, hex
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class AuditSubject(Base):
    __tablename__ = "audit_subjects"
    __table_args__ = (UniqueConstraint("chain_id", "kind", "value_hmac", name="uq_audit_subject_value"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chain_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class AuditErasure(Base):
    """Tombstones: which values were erased, so raw copies in old rows can be hidden.
    A row with kind NULL means the whole organisation was erased."""
    __tablename__ = "audit_erasures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    value_hmac: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    erased_at: Mapped[float] = mapped_column(Float, nullable=False)


def kind_of(value: Any) -> Optional[str]:
    """'email', 'ip', or None when the value is not personal data we pseudonymise."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if "@" in v and len(v) <= 320:
        return "email"
    try:
        ipaddress.ip_address(v)
        return "ip"
    except ValueError:
        return None


def _normal(kind: str, value: str) -> str:
    v = value.strip()
    return str(ipaddress.ip_address(v)) if kind == "ip" else v.lower()


def _hmac(pepper: str, kind: str, value: str) -> str:
    return hmac.new(bytes.fromhex(pepper), f"{kind}:{_normal(kind, value)}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _is_ref(value: Any) -> bool:
    return (isinstance(value, dict) and isinstance(value.get("subject"), str)) or (
        isinstance(value, str) and value.startswith(_SUBJECT_PREFIX) and len(value) == 36)


def _ref_id(value: Any) -> str:
    return value["subject"] if isinstance(value, dict) else value


async def _pepper(session: AsyncSession, cid: str) -> Optional[str]:
    row = await session.get(AuditOrgPepper, cid)
    return row.pepper if row else None


async def _ensure_pepper(cid: str) -> str:
    for _ in range(3):
        async with get_session_factory()() as s:
            found = await _pepper(s, cid)
            if found:
                return found
            pepper = secrets.token_hex(32)
            s.add(AuditOrgPepper(chain_id=cid, pepper=pepper, created_at=time.time()))
            try:
                await s.commit()
                return pepper
            except IntegrityError as e:  # another writer created it first
                # Class name only: SQLAlchemy's message can carry the bound parameters.
                logger.info("audit pepper for %s created concurrently: %s", cid, type(e).__name__)
    raise RuntimeError(f"could not create the audit pepper for {cid}")


async def label(org_id: Any, value: Any) -> str:
    """A display-only pseudonym for a value of this organisation: HMAC-SHA256 under the
    organisation's server-side pepper (full 128-bit prefix). Not reproducible without the
    pepper, differs between organisations, and stores nothing. Erasing the org pepper
    (erase_org) makes every label unrecomputable. Raises if the pepper cannot be had."""
    pepper = await _ensure_pepper(chain.chain_id_for(org_id))
    return "person-" + _hmac(pepper, "label", str(value))[:32]


async def pseudonymise(org_id: Any, kind: str, value: str) -> Dict[str, str]:
    """The chain-safe reference for one email or IP of this organisation."""
    cid = chain.chain_id_for(org_id)
    pepper = await _ensure_pepper(cid)
    digest = _hmac(pepper, kind, value)
    for _ in range(3):
        async with get_session_factory()() as s:
            found = (await s.execute(select(AuditSubject.id).where(
                AuditSubject.chain_id == cid, AuditSubject.kind == kind,
                AuditSubject.value_hmac == digest))).scalar()
            if found:
                return {"subject": found, "hmac": digest}
            sid = _SUBJECT_PREFIX + secrets.token_hex(16)
            s.add(AuditSubject(id=sid, chain_id=cid, kind=kind, value_hmac=digest,
                               value=value.strip(), created_at=time.time()))
            try:
                await s.commit()
                return {"subject": sid, "hmac": digest}
            except IntegrityError as e:
                # Never str(e): it can include the raw email/IP being pseudonymised.
                logger.info("audit subject created concurrently: %s", type(e).__name__)
    raise RuntimeError("could not record the audit subject")


async def scrub(org_id: Any, ip_address: Any, metadata: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    """(ip_address, metadata) with every email/IP replaced by its reference. Touches
    the database only when there is personal data to replace."""
    ip_kind = kind_of(ip_address)
    ip_out = await pseudonymise(org_id, ip_kind, ip_address) if ip_kind else ip_address
    meta = dict(metadata)
    for key in PII_METADATA_KEYS:
        k = kind_of(meta.get(key))
        if k:
            meta[key] = await pseudonymise(org_id, k, meta[key])
    return ip_out, meta


def withhold(ip_address: Any, metadata: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    """Fail-closed fallback when pseudonymising fails: drop the personal values."""
    meta = {k: (WITHHELD if k in PII_METADATA_KEYS and kind_of(v) else v) for k, v in metadata.items()}
    return (WITHHELD if kind_of(ip_address) else ip_address), meta


async def reveal(org_id: Any, values: List[Any]) -> List[Any]:
    """Read overlay: references become their raw value (or "[erased]"); raw values in
    old rows become "[erased]" when that value or the whole organisation was erased."""
    cid = chain.chain_id_for(org_id)
    ids = {_ref_id(v) for v in values if _is_ref(v)}
    raws = [v for v in values if not _is_ref(v) and kind_of(v)]
    found: Dict[str, str] = {}
    erased_all, erased = False, set()
    pepper: Optional[str] = None
    async with get_session_factory()() as s:
        if ids:
            found = dict((await s.execute(select(AuditSubject.id, AuditSubject.value).where(
                AuditSubject.chain_id == cid, AuditSubject.id.in_(ids)))).all())
        if raws:
            pepper = await _pepper(s, cid)
            hashes = {_hmac(pepper, kind_of(v), v) for v in raws} if pepper else set()
            tombs = (await s.execute(select(AuditErasure.kind, AuditErasure.value_hmac).where(
                AuditErasure.chain_id == cid,
                or_(AuditErasure.kind.is_(None), AuditErasure.value_hmac.in_(hashes))))).all()
            erased_all = any(k is None for k, _ in tombs)
            erased = {h for _, h in tombs if h}
    out: List[Any] = []
    for v in values:
        if _is_ref(v):
            out.append(found.get(_ref_id(v), ERASED))
        elif kind_of(v) and (erased_all or (pepper and _hmac(pepper, kind_of(v), v) in erased)):
            out.append(ERASED)
        else:
            out.append(v)
    return out


async def overlay(org_id: Any, records: List[Dict[str, Any]], ip_key: str = "ip_address",
                  meta_key: str = "metadata") -> List[Dict[str, Any]]:
    """Copies of event records (chain payloads or audit_log rows) as they may be shown:
    personal values resolved, erased ones replaced by "[erased]"."""
    out = [dict(r) for r in records]
    slots: List[Tuple[Dict[str, Any], str]] = []
    for r in out:
        if ip_key in r:
            slots.append((r, ip_key))
        if isinstance(r.get(meta_key), dict):
            r[meta_key] = dict(r[meta_key])
            slots += [(r[meta_key], k) for k in PII_METADATA_KEYS if k in r[meta_key]]
    revealed = await reveal(org_id, [c[k] for c, k in slots])
    for (c, k), v in zip(slots, revealed):
        c[k] = v
    return out


async def overlay_entries(org_id: Any, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chain entries (as read_entries/ledger_view return them) with the overlay applied
    to each payload. Hashes are untouched, so verification is unaffected."""
    payloads = await overlay(org_id, [e["payload"] for e in entries])
    return [{**e, "payload": p} for e, p in zip(entries, payloads)]


async def display_columns(org_id: Any, rows: List[Any]) -> List[Tuple[str, str]]:
    """(ip_address, metadata JSON) text for audit_log rows (anything with .ip_address and
    .log_metadata) as an export may show them: references resolved, erased values
    "[erased]". Exports must use this, never the stored columns."""
    recs = []
    for r in rows:
        try:
            meta = json.loads(r.log_metadata) if r.log_metadata else None
        except ValueError:
            meta = None
        recs.append({"ip_address": r.ip_address, "metadata": meta})
    out: List[Tuple[str, str]] = []
    for r, shown in zip(rows, await overlay(org_id, recs)):
        meta = shown["metadata"]
        out.append((shown["ip_address"] or "",
                    json.dumps(meta, sort_keys=True) if isinstance(meta, dict) else (r.log_metadata or "")))
    return out


def _event_org(cid: str) -> Optional[str]:
    return None if cid == chain.PLATFORM_CHAIN else cid


async def erase_subject(org_id: Any, subject: str, by: str) -> Dict[str, Any]:
    """Erase one person's email or IP (given raw, or as a subject id) in one organisation.

    The subject row is deleted and a tombstone kept, atomically with a ledger entry
    "audit.subject_erased" that holds only the subject id and kind.
    """
    cid = chain.chain_id_for(org_id)
    subject = (subject or "").strip()
    if subject.startswith(_SUBJECT_PREFIX):
        async with get_session_factory()() as s:
            row = (await s.execute(select(AuditSubject).where(
                AuditSubject.id == subject, AuditSubject.chain_id == cid))).scalars().first()
        if row is None:
            raise LookupError("no such subject in this organisation")
        kind, digest, sid = row.kind, row.value_hmac, row.id
    else:
        kind = kind_of(subject)
        if not kind:
            raise ValueError("subject must be an email address, an IP address or a subject id")
        digest = _hmac(await _ensure_pepper(cid), kind, subject)
        async with get_session_factory()() as s:
            sid = (await s.execute(select(AuditSubject.id).where(
                AuditSubject.chain_id == cid, AuditSubject.kind == kind,
                AuditSubject.value_hmac == digest))).scalar()

    async def _apply(session: AsyncSession, entry: chain.AuditChainEntry) -> None:
        session.add(AuditErasure(chain_id=cid, kind=kind, value_hmac=digest, subject_id=sid,
                                 erased_at=entry.timestamp))
        if sid:
            await session.execute(delete(AuditSubject).where(AuditSubject.id == sid))

    entry = await chain.append(actor=by, action="audit.subject_erased", also=_apply,
                               payload={"org_id": _event_org(cid), "subject": sid, "kind": kind})
    return {"subject": sid, "kind": kind, "matched": sid is not None, "entry_seq": entry.seq}


async def erase_org(org_id: Any, by: str) -> Dict[str, Any]:
    """Erase every subject and the pepper of one organisation (e.g. when it is deleted).
    Afterwards none of its references can be resolved or recomputed."""
    cid = chain.chain_id_for(org_id)
    counted: Dict[str, int] = {}

    async def _apply(session: AsyncSession, entry: chain.AuditChainEntry) -> None:
        counted["subjects"] = (await session.execute(
            delete(AuditSubject).where(AuditSubject.chain_id == cid))).rowcount
        await session.execute(delete(AuditErasure).where(AuditErasure.chain_id == cid))
        await session.execute(delete(AuditOrgPepper).where(AuditOrgPepper.chain_id == cid))
        session.add(AuditErasure(chain_id=cid, kind=None, value_hmac=None, subject_id=None,
                                 erased_at=entry.timestamp))

    entry = await chain.append(actor=by, action="audit.org_erased", also=_apply,
                               payload={"org_id": _event_org(cid), "scope": "organisation"})
    return {"subjects_erased": counted.get("subjects", 0), "entry_seq": entry.seq}
