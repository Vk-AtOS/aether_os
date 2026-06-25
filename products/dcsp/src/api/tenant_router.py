from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from src.database import SessionLocal
from src.db.tenant_repo import (
    create_tenant, get_tenant_by_id,
    list_tenants, deactivate_tenant,
    update_tenant_plan, get_tenant_by_slug
)
from src.api.auth_router import get_current_user

router = APIRouter(prefix="/admin/tenants",
    tags=["tenants"])

class TenantCreate(BaseModel):
    name: str
    plan: str = "free"

class TenantPlanUpdate(BaseModel):
    plan: str

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

@router.post("",
    dependencies=[Depends(get_current_user)])
async def create_new_tenant(
    body: TenantCreate,
    db=Depends(get_db)
):
    t = create_tenant(db, body.name, body.plan)
    return {
        "id": t.id,
        "name": t.name,
        "slug": t.slug,
        "plan": t.plan,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat()
    }

@router.get("",
    dependencies=[Depends(get_current_user)])
async def get_all_tenants(
    active_only: bool = True,
    db=Depends(get_db)
):
    tenants = list_tenants(db, active_only)
    return [{
        "id": t.id,
        "name": t.name,
        "slug": t.slug,
        "plan": t.plan,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat()
    } for t in tenants]

@router.get("/{tenant_id}",
    dependencies=[Depends(get_current_user)])
async def get_tenant(
    tenant_id: str,
    db=Depends(get_db)
):
    t = get_tenant_by_id(db, tenant_id)
    if not t:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found")
    return {
        "id": t.id,
        "name": t.name,
        "slug": t.slug,
        "plan": t.plan,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat()
    }

@router.patch("/{tenant_id}/plan",
    dependencies=[Depends(get_current_user)])
async def update_plan(
    tenant_id: str,
    body: TenantPlanUpdate,
    db=Depends(get_db)
):
    valid_plans = ["free", "pro", "enterprise"]
    if body.plan not in valid_plans:
        raise HTTPException(
            status_code=400,
            detail=f"Plan must be one of: {valid_plans}")
    t = update_tenant_plan(db, tenant_id, body.plan)
    if not t:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found")
    return {
        "id": t.id,
        "name": t.name,
        "plan": t.plan
    }

@router.delete("/{tenant_id}",
    dependencies=[Depends(get_current_user)])
async def delete_tenant(
    tenant_id: str,
    db=Depends(get_db)
):
    result = deactivate_tenant(db, tenant_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found")
    return {"success": True,
            "tenant_id": tenant_id}
