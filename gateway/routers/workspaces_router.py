"""
AetherOS — Workspaces Router
GET /workspaces
POST /workspaces
GET /workspaces/{workspace_id}
PUT /workspaces/{workspace_id}
DELETE /workspaces/{workspace_id}
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

router = APIRouter(tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_shared: bool = False
    preferences: Optional[Dict[str, Any]] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_shared: Optional[bool] = None
    preferences: Optional[Dict[str, Any]] = None


def _current_user():
    return Depends(get_current_user)


@router.get("/workspaces")
async def list_workspaces(limit: int = 100, offset: int = 0, user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Workspace
    from aether_os.core.services.run_service import clamp_limit
    from sqlalchemy import select as _sel
    sf = get_session_factory()
    async with sf() as sess:
        rows = (await sess.execute(
            _sel(Workspace).where(Workspace.org_id == user["org_id"]).order_by(Workspace.created_at)
            .limit(clamp_limit(limit)).offset(max(offset, 0))
        )).scalars().all()
    return [
        {
            "id": w.id, "name": w.name, "description": w.description,
            "is_shared": w.is_shared, "preferences": w.preferences,
            "created_by": w.created_by,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in rows
    ]


@router.post("/workspaces", status_code=201)
async def create_workspace(body: WorkspaceCreate, user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Workspace
    sf = get_session_factory()
    async with sf() as sess:
        w = Workspace(
            org_id=user["org_id"],
            name=body.name,
            description=body.description,
            is_shared=body.is_shared,
            preferences=body.preferences,
            created_by=user["user_id"],
        )
        sess.add(w)
        await sess.commit()
        await sess.refresh(w)
    return {
        "id": w.id, "name": w.name, "description": w.description,
        "is_shared": w.is_shared, "preferences": w.preferences,
        "created_by": w.created_by,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str, user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Workspace
    sf = get_session_factory()
    async with sf() as sess:
        w = await sess.get(Workspace, workspace_id)
    if not w or w.org_id != user["org_id"]:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {
        "id": w.id, "name": w.name, "description": w.description,
        "is_shared": w.is_shared, "preferences": w.preferences,
        "created_by": w.created_by,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


@router.put("/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: str, body: WorkspaceUpdate, user: Dict[str, Any] = _current_user()
):
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Workspace
    sf = get_session_factory()
    async with sf() as sess:
        w = await sess.get(Workspace, workspace_id)
        if not w or w.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if body.name is not None:
            w.name = body.name
        if body.description is not None:
            w.description = body.description
        if body.is_shared is not None:
            w.is_shared = body.is_shared
        if body.preferences is not None:
            w.preferences = body.preferences
        await sess.commit()
        await sess.refresh(w)
    return {
        "id": w.id, "name": w.name, "description": w.description,
        "is_shared": w.is_shared, "preferences": w.preferences,
        "created_by": w.created_by,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Workspace
    sf = get_session_factory()
    async with sf() as sess:
        w = await sess.get(Workspace, workspace_id)
        if not w or w.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Workspace not found")
        await sess.delete(w)
        await sess.commit()
