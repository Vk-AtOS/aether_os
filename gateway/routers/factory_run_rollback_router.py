"""
AetherOS — restore a run's files from a snapshot (KAN-161).

  POST /factory/runs/{run_id}/snapshots/{snapshot_id}/rollback

Admin or owner only (it overwrites generated code for everyone on the run), scoped to the
caller's organisation (another org's run or snapshot is a 404, never a 403 that confirms it
exists), audited, and written through safe_fs so a stored path or a planted link can never
reach outside the run's project directory.
"""
from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import get_session_factory
from aether_os.core.errors import SandboxViolation
from aether_os.core.models import Run, Snapshot
from aether_os.core.run_app import safe_fs
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers.factory_run_files_router import _resolve_project_dir

logger = logging.getLogger(__name__)
router = APIRouter(tags=["run-files"])


def _relative(path: str) -> PurePosixPath:
    """The snapshot's stored path as a safe relative path, else 422."""
    p = PurePosixPath((path or "").replace("\\", "/"))
    if not path or p.is_absolute() or ".." in p.parts or not p.parts:
        raise HTTPException(status_code=422, detail="Snapshot has no restorable relative path")
    return p


@router.post("/factory/runs/{run_id}/snapshots/{snapshot_id}/rollback")
async def rollback_to_snapshot(
    run_id: str,
    snapshot_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Write the snapshot's stored content back over the file it was taken from."""
    if user.get("role") not in ("owner", "admin"):  # D7: server-side, UI hiding is not security
        raise HTTPException(status_code=403, detail="Only org owners/admins may roll back a run")
    org_id = user.get("org_id")
    async with get_session_factory()() as sess:
        run = await sess.get(Run, run_id)
        snap = await sess.get(Snapshot, snapshot_id)
    # The same 404 for every refusal: a caller outside the org learns nothing about the ids.
    if (not run or run.org_id != org_id or not snap or snap.run_id != run_id
            or (snap.org_id is not None and snap.org_id != org_id)):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    if snap.content is None:
        raise HTTPException(status_code=409, detail="Snapshot has no stored content")
    rel = _relative(snap.file_path)
    _, root_dir = await _resolve_project_dir(run_id, org_id)
    try:
        if len(rel.parts) > 1:
            safe_fs.safe_makedirs(root_dir, root_dir / PurePosixPath(*rel.parts[:-1]))
        safe_fs.safe_write_text(root_dir, root_dir / rel, snap.content)
    except SandboxViolation as exc:
        logger.warning("rollback refused for run %s snapshot %s: %s", run_id, snapshot_id, exc)
        raise HTTPException(status_code=403, detail="Path is outside the run directory") from exc
    except OSError as exc:
        logger.warning("rollback write failed for run %s snapshot %s: %s", run_id, snapshot_id, exc)
        raise HTTPException(status_code=500, detail="Could not restore the file") from exc
    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id=user.get("user_id") or user.get("sub") or "-",
        action="run.rollback", resource_type="run", resource_id=run_id,
        metadata={"snapshot_id": snapshot_id, "file_path": str(rel)},
    )
    return {"run_id": run_id, "snapshot_id": snapshot_id, "restored": str(rel), "size": len(snap.content)}
