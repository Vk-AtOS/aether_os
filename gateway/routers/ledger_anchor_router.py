"""Ledger anchors and erasure, next to the Prime ledger browser (/prime/ledger).

Signed checkpoints of an organisation's audit chain, the export a customer keeps so
the platform cannot rewrite history unseen, verification against a kept checkpoint,
and erasure of a person's email/IP from what the ledger can reveal. Logic lives in
core/audit; this file is HTTP only. Every endpoint needs a signed-in user.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aether_os.core.audit import anchor, chain, checkpoints, subjects
from aether_os.gateway.dependencies import get_current_user

# The lifespan runs the periodic anchor job (AETHER_LEDGER_ANCHOR_INTERVAL, 0 = off).
router = APIRouter(prefix="/prime/ledger", tags=["ledger"], lifespan=anchor.periodic_lifespan)

_ADMINS = ("owner", "admin", "superadmin")


def _chain(user: Dict[str, Any]) -> str:
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="No organisation on this sign-in")
    try:
        return chain.chain_id_for(org_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _admin(user: Dict[str, Any]) -> str:
    """The caller's chain, if the caller administers that organisation."""
    cid = _chain(user)
    if user.get("role") not in _ADMINS or not user.get("user_id"):
        raise HTTPException(status_code=403, detail="Organisation admins only")
    return cid


class CheckpointIn(BaseModel):
    chain_id: str = Field(max_length=64)
    chain_seq: int = Field(ge=1)
    head_hash: str = Field(min_length=64, max_length=64)
    created_at: float
    key_id: str = Field(max_length=32)
    signature: str = Field(max_length=128)


class VerifyIn(BaseModel):
    full: bool = False
    checkpoint: Optional[CheckpointIn] = None


class EraseIn(BaseModel):
    subject: str = Field(min_length=1, max_length=320, description="Email, IP address or subject id")
    org_id: Optional[str] = Field(default=None, max_length=50, description="Superadmin only: another organisation")
    platform: bool = Field(default=False, description="Superadmin only: the platform chain")


@router.get("/anchor/latest")
async def latest_checkpoint(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """The newest signed checkpoint of the caller's organisation chain, and the key to check it."""
    cid = _chain(user)
    key = checkpoints.signing_key(create=False)
    # file_check: the last scheduled check of the local anchor file (this chain's
    # problems only; None until the first run, 600 s by default).
    return {"chain_id": cid, "checkpoint": await anchor.latest(cid),
            "file_check": anchor.last_file_check(cid),
            "key_id": checkpoints.key_id(key) if key else None,
            "public_key_pem": checkpoints.public_key_pem(key) if key else None}


@router.get("/anchor/export")
async def export_checkpoints(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Every signed checkpoint of the organisation's chain, the public key and the genesis
    link. Keep this file outside AetherOS: it is the customer's own proof."""
    return await anchor.export(_admin(user))


@router.post("/anchor")
async def anchor_now(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Verify the organisation's chain and sign its current head now."""
    cid = _admin(user)
    try:
        return {"chain_id": cid, "checkpoint": await anchor.anchor_chain(cid)}
    except anchor.ChainBroken as e:
        raise HTTPException(status_code=409, detail=f"chain does not verify: {e.result.reason}") from e


@router.post("/anchor/verify")
async def verify_chain(body: VerifyIn, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Verify the organisation's chain against its signed checkpoints and, if given, a
    checkpoint the customer kept. `truncated` means entries were removed from the end."""
    cid = _admin(user)
    kept = body.checkpoint.model_dump() if body.checkpoint else None
    if kept and kept["chain_id"] != cid:
        raise HTTPException(status_code=400, detail="checkpoint is for another organisation")
    r = await chain.verify_chain(cid, full=body.full, checkpoint=kept)
    return {"chain_id": cid, "ok": r.ok, "entries_checked": r.entries_checked,
            "broken_seq": r.broken_seq, "reason": r.reason, "head_seq": r.head_seq,
            "head_hash": r.head_hash, "checkpoint_seq": r.checkpoint_seq, "truncated": r.truncated}


@router.post("/anchor/check-file")
async def check_anchor_file(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Superadmin: verify every chain against the local anchor file."""
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin only")
    result = await anchor.run_file_check()
    return {"ok": result["ok"], "problems": result["problems"]}


@router.post("/subjects/erase")
async def erase_subject(body: EraseIn, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Erase a person's email or IP from what the ledger reveals in one organisation.
    Entries stay verifiable; reads show "[erased]" from now on."""
    cid = _admin(user)
    org: Optional[str] = None if cid == chain.PLATFORM_CHAIN else cid
    if body.platform or (body.org_id and body.org_id != org):
        if user.get("role") != "superadmin":
            raise HTTPException(status_code=403, detail="Only a superadmin can erase outside their organisation")
        org = None if body.platform else body.org_id
    try:
        return await subjects.erase_subject(org, body.subject, by=str(user["user_id"]))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
