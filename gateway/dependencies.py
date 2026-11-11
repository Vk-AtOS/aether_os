"""
Shared FastAPI dependencies — importable by any router without circular-import risk.

Routers previously used a lazy-import pattern inside _current_user() to avoid
importing from gateway/api.py at module scope (circular import).  Placing the
dependency here breaks the cycle: neither api.py nor the routers import each other
at module level.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import Run

security_scheme = HTTPBearer(auto_error=False)

# Endpoints exempt from must_change_password block — user must be able to reach
# change-password and logout even when forced to rotate credentials.
_PASSWORD_CHANGE_EXEMPT_PATHS = {"/auth/change-password", "/auth/logout"}


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Dict[str, Any]:
    """FastAPI dependency: validates JWT token or API Key, returns user claims."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    token = credentials.credentials
    from aether_os.gateway.auth import decode_bearer_token, hash_api_key

    # 1. Try JWT
    payload = decode_bearer_token(token)
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

                # FIX-15: block all endpoints except change-password/logout when must_change_password is set.
                # This is set by admin reset-password and invite flows to force credential rotation.
                if getattr(db_user, "must_change_password", False):
                    if request.url.path not in _PASSWORD_CHANGE_EXEMPT_PATHS:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="password_change_required",
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
            except Exception as exc:
                # SEC-C1: Redis blacklist unavailable — fail CLOSED to prevent
                # revoked tokens from silently passing auth during an outage.
                logger.warning("JWT blacklist check failed (Redis unavailable) — denying request: %s", exc)
                raise HTTPException(
                    status_code=503,
                    detail="Auth service temporarily unavailable — please retry",
                )
        return payload

    # 2. Try API Key
    if token.startswith("aesk_"):
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import APIKey, Organisation

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


async def assert_run_in_org(run_id: str, user: Dict[str, Any]) -> None:
    """Raise 404 unless run_id is a run owned by the caller's org.

    Single choke point for run-scoped endpoints: project files, traces, Redis
    control flags and preview processes are all keyed by run_id alone, so the
    org check has to happen before any of them is touched. 404 (not 403) so a
    caller cannot probe which run ids exist in other orgs.
    """
    org_id = user.get("org_id")
    if run_id and org_id:
        async with get_session_factory()() as session:
            found = (await session.execute(
                select(Run.id).where(Run.id == run_id, Run.org_id == org_id)
            )).scalar_one_or_none()
        if found:
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")


async def require_run_user(
    run_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Dependency for routes with a {run_id} path param: the user, after the org check."""
    await assert_run_in_org(run_id, user)
    return user
