"""Ledger operations for platform administrators (superadmin only): the audit_log
back-fill into the per-organisation chains, and finishing erasures that did not complete.
Logic lives in core/audit (backfill.py, deletion.py); this file is HTTP only.
Every endpoint needs a signed-in superadmin.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from aether_os.core.audit import backfill, chain, deletion
from aether_os.gateway.dependencies import get_current_user

router = APIRouter(prefix="/prime/ledger", tags=["ledger"])


def _superadmin(user: Dict[str, Any]) -> str:
    if user.get("role") != "superadmin" or not user.get("user_id"):
        raise HTTPException(status_code=403, detail="Superadmin only")
    return str(user["user_id"])


@router.post("/backfill")
async def run_backfill(
    dry_run: bool = Query(default=True, description="Default true: report only, write nothing"),
    batch: int = Query(default=500, ge=1, le=2000),
    max_batches: int = Query(default=20, ge=1, le=1000, description="Batches this call may run; call again to continue"),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Import audit_log rows that never reached a chain. Dry run is the default; a real
    run is idempotent and resumable (`remaining` says how much is left), and is itself
    ledgered. Run the dry run first and proceed only when it reports clean."""
    by = _superadmin(user)
    report = await backfill.run(batch, dry_run=dry_run, max_batches=max_batches)
    if not dry_run:
        await chain.append(actor=by, action="audit.backfill_run", payload={
            "org_id": None, "imported": report["imported"], "failed": report["failed"],
            "remaining": report["remaining"]})
    return report


@router.post("/erasure/retry")
async def retry_erasures(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Erase the ledger personal data of deleted organisations whose erasure did not
    complete. Idempotent; reports which organisations are done and which still fail."""
    by = _superadmin(user)
    return await deletion.retry_pending(by)
