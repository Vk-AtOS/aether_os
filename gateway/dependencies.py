"""
Shared FastAPI dependencies — importable by any router without circular-import risk.

Routers previously used a lazy-import pattern inside _current_user() to avoid
importing from gateway/api.py at module scope (circular import).  Placing the
dependency here breaks the cycle: neither api.py nor the routers import each other
at module level.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Dict[str, Any]:
    """FastAPI dependency: validates JWT token or API Key, returns user claims."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    token = credentials.credentials
    from aether_os.gateway.auth import decode_access_token, hash_api_key

    # 1. Try JWT
    payload = decode_access_token(token)
    if payload:
        if payload.get("mfa_pending"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="MFA verification required. Complete sign-in at /auth/mfa/confirm.",
            )

        # email_verified and is_active check
        user_id = payload.get("user_id")
        if user_id:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import User, Organisation
            sf = get_session_factory()
            async with sf() as session:
                user_row = (await session.execute(
                    select(User, Organisation).join(Organisation).where(User.id == user_id)
                )).fetchone()
                if not user_row:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
                
                db_user, db_org = user_row
                if not db_user.is_active or db_user.deleted_at:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is deactivated")
                
                if db_org.is_deleted:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation is deleted")

                if not db_user.email_verified:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="email_not_verified",
                    )

        jti = payload.get("jti")
        if jti:
            try:
                from aether_os.core.pipeline_state import get_redis
                r = await get_redis()
                if r and await r.exists(f"jwt:blacklist:{jti}"):
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
            except HTTPException:
                raise
            except Exception:
                pass
        return payload

    # 2. Try API Key
    if token.startswith("aesk_"):
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import APIKey, Organisation
        from sqlalchemy import select

        hashed = hash_api_key(token)
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(APIKey, Organisation).join(Organisation).where(
                APIKey.key_hash == hashed,
                APIKey.is_active == True,
            )
            result = await session.execute(stmt)
            row = result.fetchone()
            if row:
                api_key, org = row
                api_key.last_used_at = time.time()
                await session.commit()
                return {
                    "sub": "api_key",
                    "org_id": org.id,
                    "org_slug": org.slug,
                    "plan": org.plan,
                    "role": "api",
                }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )
