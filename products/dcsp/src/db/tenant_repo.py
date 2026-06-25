from __future__ import annotations
from typing import Optional, List
from sqlalchemy.orm import Session
from src.models import Tenant
import uuid, re
from datetime import datetime

def slugify(name: str) -> str:
    """Convert name to URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug[:50]

def create_tenant(
    session: Session,
    name: str,
    plan: str = "free"
) -> Tenant:
    slug = slugify(name)
    # Ensure slug uniqueness
    existing = session.query(Tenant).filter(
        Tenant.slug == slug).first()
    if existing:
        slug = f"{slug}-{str(uuid.uuid4())[:8]}"
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=name,
        slug=slug,
        plan=plan,
        created_at=datetime.utcnow(),
        is_active=True
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant

def get_tenant_by_id(
    session: Session,
    tenant_id: str
) -> Optional[Tenant]:
    return session.query(Tenant).filter(
        Tenant.id == tenant_id).first()

def get_tenant_by_slug(
    session: Session,
    slug: str
) -> Optional[Tenant]:
    return session.query(Tenant).filter(
        Tenant.slug == slug).first()

def list_tenants(
    session: Session,
    active_only: bool = True
) -> List[Tenant]:
    q = session.query(Tenant)
    if active_only:
        q = q.filter(Tenant.is_active == True)
    return q.order_by(
        Tenant.created_at.desc()).all()

def deactivate_tenant(
    session: Session,
    tenant_id: str
) -> bool:
    tenant = get_tenant_by_id(
        session, tenant_id)
    if not tenant:
        return False
    tenant.is_active = False
    session.commit()
    return True

def update_tenant_plan(
    session: Session,
    tenant_id: str,
    plan: str
) -> Optional[Tenant]:
    tenant = get_tenant_by_id(
        session, tenant_id)
    if not tenant:
        return None
    tenant.plan = plan
    session.commit()
    session.refresh(tenant)
    return tenant
