"""Which IR fields a generated CRUD API may expose (KAN-69 G1/G2)."""
from __future__ import annotations

# Fields a client may never write or read through a generated CRUD API (KAN-69 G1/G2): credentials and
# privilege flags always, the tenant key whenever tenancy is on (the server sets it from the token).
_NEVER_CLIENT_FIELDS = {"password_hash", "hashed_password", "is_admin"}
_TENANT_FIELDS = {"org_id", "tenant_id"}


def is_user_entity(entity) -> bool:
    """The account table is owned by the auth router (sign-up, login); it gets no CRUD API."""
    return entity.name == "User" or getattr(entity, "table", "") == "users"


def client_fields(entity, multi_tenancy: bool = False) -> list:
    """The entity's fields without anything a client must not control."""
    deny = _NEVER_CLIENT_FIELDS | (_TENANT_FIELDS if multi_tenancy else set())
    return [f for f in entity.fields if f.name.lower() not in deny]
