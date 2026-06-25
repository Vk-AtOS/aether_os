from __future__ import annotations
import pytest
from src.database import SessionLocal
from src.db.tenant_repo import (
    create_tenant, get_tenant_by_id,
    get_tenant_by_slug, list_tenants,
    deactivate_tenant, update_tenant_plan,
    slugify
)

@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()

def test_slugify_basic():
    assert slugify("My Company") == "my-company"

def test_slugify_special_chars():
    assert slugify("Acme & Co!") == "acme-co"

def test_create_tenant(db):
    import uuid
    name = f"Test Corp {uuid.uuid4().hex[:6]}"
    t = create_tenant(db, name)
    assert t.id is not None
    assert t.slug.startswith("test-corp")
    assert t.plan == "free"
    assert t.is_active is True

def test_get_tenant_by_id(db):
    import uuid
    name = f"IDTest {uuid.uuid4().hex[:6]}"
    t = create_tenant(db, name)
    found = get_tenant_by_id(db, t.id)
    assert found is not None
    assert found.name == name

def test_get_tenant_by_slug(db):
    import uuid
    name = f"SlugTest {uuid.uuid4().hex[:6]}"
    t = create_tenant(db, name)
    found = get_tenant_by_slug(db, t.slug)
    assert found is not None

def test_list_tenants(db):
    import uuid
    create_tenant(db, f"List A {uuid.uuid4().hex[:6]}")
    create_tenant(db, f"List B {uuid.uuid4().hex[:6]}")
    tenants = list_tenants(db)
    assert len(tenants) >= 2

def test_deactivate_tenant(db):
    import uuid
    t = create_tenant(db, f"Deactivate {uuid.uuid4().hex[:6]}")
    result = deactivate_tenant(db, t.id)
    assert result is True
    found = get_tenant_by_id(db, t.id)
    assert found.is_active is False

def test_update_tenant_plan(db):
    import uuid
    t = create_tenant(db, f"Plan {uuid.uuid4().hex[:6]}")
    updated = update_tenant_plan(db, t.id, "enterprise")
    assert updated.plan == "enterprise"

def test_get_nonexistent_tenant(db):
    found = get_tenant_by_id(
        db, "nonexistent-id-xyz")
    assert found is None
