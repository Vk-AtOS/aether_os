from __future__ import annotations
from fastapi import Request
from src.database import SessionLocal
from src.db.tenant_repo import get_tenant_by_slug, get_tenant_by_id

DEFAULT_TENANT_SLUG = "default"

def get_tenant_from_request(
    request: Request
) -> dict | None:
    """
    Extract tenant from request.
    Priority:
    1. X-Tenant-ID header
    2. X-Tenant-Slug header
    3. Fall back to default tenant
    """
    session = SessionLocal()
    try:
        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            t = get_tenant_by_id(session, tenant_id)
            if t and t.is_active:
                return {
                    "id": t.id,
                    "name": t.name,
                    "slug": t.slug,
                    "plan": t.plan
                }
        
        slug = request.headers.get("X-Tenant-Slug")
        if slug:
            t = get_tenant_by_slug(session, slug)
            if t and t.is_active:
                return {
                    "id": t.id,
                    "name": t.name,
                    "slug": t.slug,
                    "plan": t.plan
                }
        
        # Fall back to default tenant
        t = get_tenant_by_slug(session, DEFAULT_TENANT_SLUG)
        if t:
            return {
                "id": t.id,
                "name": t.name,
                "slug": t.slug,
                "plan": t.plan
            }
        return None
    finally:
        session.close()
