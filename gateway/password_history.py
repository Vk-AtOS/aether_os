"""Password history: a user may not go back to one of their last passwords (KAN-187).

AETHER_PASSWORD_HISTORY (default 5) is how many passwords are remembered, the current one included;
0 turns the check off. Only hashes are stored.
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import delete, select

from aether_os.core.models import PasswordHistory, User
from aether_os.gateway.auth import verify_password

REUSED = "You cannot reuse one of your last passwords. Choose a new one."


def keep_count() -> int:
    try:
        return max(0, int(os.environ.get("AETHER_PASSWORD_HISTORY", "5")))
    except ValueError:
        return 5


async def is_reused(session, user: User, new_password: str) -> bool:
    """True when new_password equals the current password or one of the remembered ones."""
    keep = keep_count()
    if keep == 0:
        return False
    old = (await session.execute(
        select(PasswordHistory.password_hash).where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc()).limit(keep - 1)
    )).scalars().all() if keep > 1 else []
    loop = asyncio.get_running_loop()
    for h in [user.password_hash, *old]:
        if h and await loop.run_in_executor(None, verify_password, new_password, h):
            return True
    return False


async def remember(session, user: User, old_hash: str) -> None:
    """Store the hash that is being replaced and drop the ones beyond the window. Call before commit."""
    keep = keep_count()
    if keep <= 1 or not old_hash:
        return
    session.add(PasswordHistory(user_id=user.id, password_hash=old_hash))
    await session.flush()
    stale = (await session.execute(
        select(PasswordHistory.id).where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc()).offset(keep - 1)
    )).scalars().all()
    if stale:
        await session.execute(delete(PasswordHistory).where(PasswordHistory.id.in_(stale)))
