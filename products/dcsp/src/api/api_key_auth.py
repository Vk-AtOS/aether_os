from __future__ import annotations
from typing import Optional
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader
from src.database import SessionLocal
from src.db.api_key_repo import verify_api_key

API_KEY_HEADER = APIKeyHeader(
    name="X-API-Key", auto_error=False)

async def get_api_key_tenant(
    api_key: Optional[str] = Security(
        API_KEY_HEADER)
) -> dict:
    """
    FastAPI dependency: validates X-API-Key header.
    Returns tenant info dict if valid.
    Raises 401 if missing or invalid.
    """
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="X-API-Key header required")
    
    session = SessionLocal()
    try:
        key_obj = verify_api_key(session, api_key)
        if not key_obj:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired API key")
        
        from src.db.tenant_repo import \
            get_tenant_by_id
        tenant = get_tenant_by_id(
            session, key_obj.tenant_id)
        if not tenant or not tenant.is_active:
            raise HTTPException(
                status_code=403,
                detail="Tenant inactive or not found")
        
        return {
            "tenant_id": tenant.id,
            "tenant_name": tenant.name,
            "tenant_slug": tenant.slug,
            "tenant_plan": tenant.plan,
            "api_key_id": key_obj.id,
            "api_key_name": key_obj.name
        }
    finally:
        session.close()
