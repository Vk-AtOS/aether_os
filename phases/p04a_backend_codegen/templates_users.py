"""Deterministic admin-only users router for the generated backend (KAN-224).

The generated admin UI has a Users page (GET/POST /users, PATCH/DELETE /users/{id}) but the backend
only had /auth/*, so the page 404'd. This router is a fixed template, not model output, so every
generated app gets it. It uses the app's own hasher and role guard from auth.py and the same
{items,total,page,page_size,limit} list shape as the entity routers. password_hash is never returned.
"""
from __future__ import annotations

_USERS_ROUTER_PY = '''"""Users admin API: list, get, create, update, deactivate. Admin only. Never returns password_hash."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_password_hash, password_problem, require_role
from database import get_db
from models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])

# The display-name column differs between generator paths (full_name / name / none).
_NAME_ATTR = next((a for a in ("full_name", "name") if hasattr(User, a)), None)
_TENANT = hasattr(User, "org_id")


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: str
    password: str
    role: str = "user"
    is_active: bool = True
    full_name: Optional[str] = None


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Optional[str] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = None
    password: Optional[str] = None      # a password change only goes through this field and is hashed


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    id: int
    email: str
    role: str
    is_active: bool
    full_name: Optional[str] = None
    created_at: Optional[object] = None
    updated_at: Optional[object] = None


def _out(u) -> dict:
    return {
        "id": u.id, "email": u.email, "role": u.role, "is_active": bool(u.is_active),
        "full_name": getattr(u, _NAME_ATTR, None) if _NAME_ATTR else None,
        "created_at": getattr(u, "created_at", None), "updated_at": getattr(u, "updated_at", None),
    }


def _scope(q, admin: dict):
    # Multi-tenant apps: an admin manages only the users of their own tenant.
    return q.where(User.org_id == admin.get("org_id")) if _TENANT else q


async def _load(db: AsyncSession, admin: dict, user_id: int):
    u = (await db.execute(_scope(select(User).where(User.id == user_id), admin))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


def _check_role(role: str) -> str:
    role = (role or "").strip()
    if not role or len(role) > 50:
        raise HTTPException(status_code=422, detail="role must be 1-50 characters")
    return role


def _check_password(pw: str) -> str:
    problem = password_problem(pw)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    try:
        return get_password_hash(pw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    limit: Optional[int] = Query(None, ge=1, le=200),   # older clients; page_size is the documented name
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_role("admin")),
):
    size = limit or page_size
    total = (await db.execute(_scope(select(func.count()).select_from(User), admin))).scalar_one()
    rows = (await db.execute(_scope(select(User), admin).order_by(User.id).offset((page - 1) * size).limit(size))).scalars().all()
    return {"items": [_out(u) for u in rows], "total": total, "page": page, "page_size": size, "limit": size}


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db), admin: dict = Depends(require_role("admin"))):
    return _out(await _load(db, admin, user_id))


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db), admin: dict = Depends(require_role("admin"))):
    email = data.email.strip().lower()
    if "@" not in email or len(email) > 320:
        raise HTTPException(status_code=422, detail="A valid email is required")
    pw_hash = _check_password(data.password)
    taken = await db.execute(select(User.id).where(func.lower(User.email) == email))
    if taken.first():
        raise HTTPException(status_code=409, detail="Email already registered")
    extra = {_NAME_ATTR: data.full_name} if _NAME_ATTR and data.full_name else {}
    if _TENANT:
        extra["org_id"] = admin.get("org_id")
    u = User(email=email, password_hash=pw_hash, role=_check_role(data.role), is_active=data.is_active, **extra)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return _out(u)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, data: UserUpdate, db: AsyncSession = Depends(get_db),
                      admin: dict = Depends(require_role("admin"))):
    u = await _load(db, admin, user_id)
    changes = data.model_dump(exclude_unset=True)
    own = str(u.id) == str(admin.get("id"))
    # An admin must not lock themselves out by demoting or deactivating their own account.
    if own and (changes.get("is_active") is False or (changes.get("role") is not None and changes["role"].lower() != "admin")):
        raise HTTPException(status_code=400, detail="You cannot demote or deactivate your own account")
    if changes.get("role") is not None:
        u.role = _check_role(changes["role"])
    if changes.get("is_active") is not None:
        u.is_active = changes["is_active"]
    if "full_name" in changes and _NAME_ATTR:
        setattr(u, _NAME_ATTR, changes["full_name"])
    if changes.get("password"):
        u.password_hash = _check_password(changes["password"])
    await db.flush()
    await db.refresh(u)
    return _out(u)


@router.delete("/{user_id}", response_model=UserResponse)
async def deactivate_user(user_id: int, db: AsyncSession = Depends(get_db), admin: dict = Depends(require_role("admin"))):
    """DELETE deactivates (is_active=False): a user row is referenced by the records they own."""
    u = await _load(db, admin, user_id)
    if str(u.id) == str(admin.get("id")):
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    u.is_active = False
    await db.flush()
    await db.refresh(u)
    return _out(u)
'''
