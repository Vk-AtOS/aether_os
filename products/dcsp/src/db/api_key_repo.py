from __future__ import annotations
import hashlib
import secrets
from typing import Optional, List
from sqlalchemy.orm import Session
from src.models import ApiKey
from datetime import datetime
import uuid

def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    Returns (raw_key, key_hash, key_prefix)
    raw_key format: dcsp_<32 random hex chars>
    """
    raw = f"dcsp_{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(
        raw.encode()).hexdigest()
    key_prefix = raw[:8]
    return raw, key_hash, key_prefix

def create_api_key(
    session: Session,
    tenant_id: str,
    name: str,
    expires_at: Optional[datetime] = None
) -> tuple[ApiKey, str]:
    """
    Create a new API key for a tenant.
    Returns (ApiKey model, raw_key_string)
    raw_key is only returned once — not stored.
    """
    raw_key, key_hash, key_prefix = \
        generate_api_key()
    api_key = ApiKey(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_at=datetime.utcnow(),
        is_active=True,
        expires_at=expires_at
    )
    session.add(api_key)
    session.commit()
    session.refresh(api_key)
    return api_key, raw_key

def verify_api_key(
    session: Session,
    raw_key: str
) -> Optional[ApiKey]:
    """
    Verify a raw API key against stored hashes.
    Updates last_used_at if valid.
    Returns ApiKey if valid and active,
    None otherwise.
    """
    key_hash = hashlib.sha256(
        raw_key.encode()).hexdigest()
    api_key = session.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active == True
    ).first()
    
    if not api_key:
        return None
    
    # Check expiry
    if api_key.expires_at and \
            api_key.expires_at < datetime.utcnow():
        return None
    
    # Update last used
    api_key.last_used_at = datetime.utcnow()
    session.commit()
    return api_key

def list_api_keys(
    session: Session,
    tenant_id: str
) -> List[ApiKey]:
    """List all active API keys for a tenant."""
    return session.query(ApiKey).filter(
        ApiKey.tenant_id == tenant_id,
        ApiKey.is_active == True
    ).order_by(
        ApiKey.created_at.desc()
    ).all()

def revoke_api_key(
    session: Session,
    key_id: str,
    tenant_id: str
) -> bool:
    """
    Revoke an API key.
    Ensures key belongs to the tenant.
    """
    api_key = session.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.tenant_id == tenant_id
    ).first()
    if not api_key:
        return False
    api_key.is_active = False
    session.commit()
    return True

def get_api_key_by_id(
    session: Session,
    key_id: str
) -> Optional[ApiKey]:
    return session.query(ApiKey).filter(
        ApiKey.id == key_id
    ).first()


def list_api_keys_for_tenant(
    session: Session,
    tenant_id: str,
) -> List[ApiKey]:
    """Alias used by profile page — same as list_api_keys."""
    return list_api_keys(session, tenant_id)
