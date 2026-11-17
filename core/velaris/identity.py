"""The Velaris identity of a signed-in AetherOS user, from the database (never from the request)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import User
from aether_os.core.velaris.client import Identity


async def identity_for(org_id: Optional[str], user_id: Optional[str]) -> Optional[Identity]:
    """Identity of an active person of `org_id`, with the role stored now (a token's role may be stale) and the
    employee record an organisation admin linked to this sign-in (users.velaris_employee_id; None = not linked,
    and Velaris then refuses every own-record read).
    None for API keys, unknown, inactive or deleted users and users of another organisation."""
    if not org_id or not user_id:
        return None
    async with get_session_factory()() as session:
        row = (await session.execute(select(User.role, User.velaris_employee_id).where(
            User.id == user_id, User.org_id == org_id, User.is_active == True,  # noqa: E712
            User.deleted_at.is_(None)))).first()
    if row is None or row[0] is None:
        return None
    return Identity(user_id=user_id, org_id=org_id, org_role=row[0], employee_id=row[1] or None)


async def identity_for_user(user: Dict[str, Any]) -> Optional[Identity]:
    """From get_current_user()'s claims: only the verified user_id and org_id are used."""
    return await identity_for(user.get("org_id"), user.get("user_id"))
