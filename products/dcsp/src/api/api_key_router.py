from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from src.database import SessionLocal
from src.db.api_key_repo import (
    create_api_key, list_api_keys,
    revoke_api_key, get_api_key_by_id
)
from src.db.tenant_repo import get_tenant_by_slug
from src.api.auth_router import get_current_user
from datetime import datetime

router = APIRouter(
    prefix="/admin/api-keys",
    tags=["api-keys"])

class ApiKeyCreate(BaseModel):
    name: str
    tenant_slug: str = "default"
    expires_at: Optional[str] = None

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

@router.post("",
    dependencies=[Depends(get_current_user)])
async def create_key(
    body: ApiKeyCreate,
    db=Depends(get_db)
):
    tenant = get_tenant_by_slug(
        db, body.tenant_slug)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{body.tenant_slug}' not found")
    
    expires_at = None
    if body.expires_at:
        try:
            expires_at = datetime.fromisoformat(
                body.expires_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid expires_at format. Use ISO 8601.")
    
    key_obj, raw_key = create_api_key(
        db, tenant.id, body.name, expires_at)
    
    return {
        "id": key_obj.id,
        "name": key_obj.name,
        "key": raw_key,  # Only shown once
        "key_prefix": key_obj.key_prefix,
        "tenant_slug": tenant.slug,
        "created_at": key_obj.created_at.isoformat(),
        "expires_at": key_obj.expires_at.isoformat()
            if key_obj.expires_at else None,
        "warning": "Save this key now. It will not be shown again."
    }

@router.get("",
    dependencies=[Depends(get_current_user)])
async def list_keys(
    tenant_slug: str = "default",
    db=Depends(get_db)
):
    tenant = get_tenant_by_slug(
        db, tenant_slug)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_slug}' not found")
    keys = list_api_keys(db, tenant.id)
    return [{
        "id": k.id,
        "name": k.name,
        "key_prefix": k.key_prefix,
        "tenant_id": k.tenant_id,
        "created_at": k.created_at.isoformat(),
        "last_used_at": k.last_used_at.isoformat()
            if k.last_used_at else None,
        "expires_at": k.expires_at.isoformat()
            if k.expires_at else None,
        "is_active": k.is_active
    } for k in keys]

@router.delete("/{key_id}",
    dependencies=[Depends(get_current_user)])
async def revoke_key(
    key_id: str,
    tenant_slug: str = "default",
    db=Depends(get_db)
):
    tenant = get_tenant_by_slug(
        db, tenant_slug)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found")
    result = revoke_api_key(
        db, key_id, tenant.id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="API key not found or belongs to different tenant")
    return {"success": True, "key_id": key_id}
