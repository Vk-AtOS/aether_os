from __future__ import annotations
import pytest
from src.database import SessionLocal
from src.db.tenant_repo import create_tenant
from src.db.api_key_repo import (
    generate_api_key,
    create_api_key,
    verify_api_key,
    list_api_keys,
    revoke_api_key,
    get_api_key_by_id
)
import uuid

@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()

@pytest.fixture
def tenant(db):
    return create_tenant(
        db, f"APIKeyTenant {uuid.uuid4().hex[:6]}")

def test_generate_api_key_format():
    raw, key_hash, prefix = generate_api_key()
    assert raw.startswith("dcsp_")
    assert len(raw) == 69  # dcsp_ + 64 hex
    assert len(key_hash) == 64
    assert prefix == raw[:8]

def test_generate_unique_keys():
    key1, _, _ = generate_api_key()
    key2, _, _ = generate_api_key()
    assert key1 != key2

def test_create_api_key(db, tenant):
    key_obj, raw_key = create_api_key(
        db, tenant.id, "Test Key")
    assert key_obj.id is not None
    assert key_obj.name == "Test Key"
    assert key_obj.tenant_id == tenant.id
    assert key_obj.is_active is True
    assert key_obj.key_prefix == raw_key[:8]
    assert raw_key.startswith("dcsp_")

def test_verify_valid_api_key(db, tenant):
    key_obj, raw_key = create_api_key(
        db, tenant.id, "Verify Test")
    verified = verify_api_key(db, raw_key)
    assert verified is not None
    assert verified.id == key_obj.id

def test_verify_invalid_api_key(db):
    result = verify_api_key(db, "dcsp_invalid000")
    assert result is None

def test_verify_updates_last_used(db, tenant):
    key_obj, raw_key = create_api_key(
        db, tenant.id, "LastUsed Test")
    assert key_obj.last_used_at is None
    verify_api_key(db, raw_key)
    db.refresh(key_obj)
    assert key_obj.last_used_at is not None

def test_list_api_keys(db, tenant):
    create_api_key(db, tenant.id, "Key One")
    create_api_key(db, tenant.id, "Key Two")
    keys = list_api_keys(db, tenant.id)
    assert len(keys) >= 2

def test_revoke_api_key(db, tenant):
    key_obj, raw_key = create_api_key(
        db, tenant.id, "Revoke Test")
    result = revoke_api_key(
        db, key_obj.id, tenant.id)
    assert result is True
    # Verify revoked key no longer works
    verified = verify_api_key(db, raw_key)
    assert verified is None

def test_revoke_wrong_tenant(db):
    tenant_a = create_tenant(
        db, f"KeyA {uuid.uuid4().hex[:6]}")
    tenant_b = create_tenant(
        db, f"KeyB {uuid.uuid4().hex[:6]}")
    key_obj, _ = create_api_key(
        db, tenant_a.id, "Cross Tenant Key")
    # Tenant B tries to revoke Tenant A's key
    result = revoke_api_key(
        db, key_obj.id, tenant_b.id)
    assert result is False

def test_expired_key_rejected(db, tenant):
    from datetime import timedelta
    import datetime as dt
    past = dt.datetime.utcnow() - timedelta(hours=1)
    key_obj, raw_key = create_api_key(
        db, tenant.id, "Expired Key",
        expires_at=past)
    result = verify_api_key(db, raw_key)
    assert result is None

def test_get_api_key_by_id(db, tenant):
    key_obj, _ = create_api_key(
        db, tenant.id, "ById Test")
    found = get_api_key_by_id(db, key_obj.id)
    assert found is not None
    assert found.id == key_obj.id
