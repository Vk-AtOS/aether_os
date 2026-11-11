"""
AetherOS — refresh-token state (rotation, reuse detection, revocation).

A refresh token is single-use. Every sign-in starts a token *family* (claim
``fam``, carried by both the access and the refresh token); each refresh issues
a new pair in the same family and spends the old refresh token.

Redis keys (same store and conventions as the access-token blacklist):
  jwt:blacklist:{jti}          spent or revoked token (shared with access tokens)
  jwt:family_revoked:{fam}     whole family revoked (logout, or a spent token was replayed)
  jwt:refresh_cutoff:{user_id} "<unix_ts>:<exempt_fam>" — refresh tokens issued at or
                               before the timestamp are dead (password change/reset)

Fail closed: if Redis cannot answer, nothing is refreshed or reported as revoked.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException

from aether_os.core.pipeline_state import get_redis
from aether_os.gateway.auth import create_access_token, create_refresh_token

logger = logging.getLogger(__name__)

_REFRESH_TTL_SECONDS = 30 * 86400  # lifetime of a refresh token (create_refresh_token default)
_UNAVAILABLE = HTTPException(status_code=503, detail="Auth service temporarily unavailable — please retry")
_REJECTED = HTTPException(status_code=401, detail="Invalid or expired refresh token")


def family_key(family: str) -> str:
    return f"jwt:family_revoked:{family}"


def _cutoff_key(user_id: str) -> str:
    return f"jwt:refresh_cutoff:{user_id}"


def issue_token_pair(claims: Dict[str, Any], family: Optional[str] = None) -> Tuple[str, str]:
    """Return (access_token, refresh_token) sharing one family id.

    The access token carries the family too, so logout (which only receives the
    access token) can revoke the refresh token issued alongside it.
    """
    data = {**claims, "fam": family or str(uuid.uuid4())}
    return create_access_token(data), create_refresh_token(data)


async def _redis():
    r = await get_redis()
    if not r:
        raise RuntimeError("Redis unavailable")
    return r


async def consume_refresh_token(claims: Dict[str, Any]) -> str:
    """Spend a decoded refresh token; return its family id for the successor pair.

    Raises 401 if the token is revoked or was already used (a replay also revokes
    the whole family: either the thief or the owner is holding a stale copy, and
    we cannot tell which), 503 if Redis cannot be consulted.
    """
    jti, user_id, exp = claims.get("jti"), claims.get("user_id"), claims.get("exp")
    if not jti or not user_id or not isinstance(exp, (int, float)):
        raise _REJECTED
    family = claims.get("fam") or jti  # tokens issued before families existed
    try:
        r = await _redis()
        if await r.exists(family_key(family)):
            raise _REJECTED
        cutoff = await r.get(_cutoff_key(user_id))
        if cutoff:
            ts, _, exempt = str(cutoff).partition(":")
            # <= : iat has one-second resolution, so a token minted in the same
            # second as the password change is treated as older (fail closed).
            if family != exempt and int(claims.get("iat", 0)) <= int(ts):
                raise _REJECTED
        ttl = max(1, int(exp - time.time()))
        # SET NX is the atomic "first use wins": two concurrent refreshes cannot both pass.
        if not await r.set(f"jwt:blacklist:{jti}", "used", nx=True, ex=ttl):
            await r.set(family_key(family), "1", ex=_REFRESH_TTL_SECONDS)
            logger.warning("Refresh token replayed (user=%s family=%s) — family revoked", user_id, family)
            raise _REJECTED
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Refresh token state check failed — denying refresh: %s", exc)
        raise _UNAVAILABLE
    return family


async def revoke_session(claims: Dict[str, Any]) -> None:
    """Logout: blacklist this access token and revoke its refresh-token family."""
    jti, exp, family = claims.get("jti"), claims.get("exp"), claims.get("fam")
    try:
        r = await _redis()
        if jti and isinstance(exp, (int, float)):
            await r.set(f"jwt:blacklist:{jti}", "1", ex=max(1, int(exp - time.time())))
        if family:
            await r.set(family_key(family), "1", ex=_REFRESH_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Logout could not revoke tokens (jti=%s): %s", jti, exc)
        raise _UNAVAILABLE


async def revoke_user_refresh_tokens(user_id: str, keep_family: Optional[str] = None) -> None:
    """Kill every refresh token the user holds now, except `keep_family` (the
    session that is changing the password stays signed in)."""
    try:
        r = await _redis()
        await r.set(_cutoff_key(user_id), f"{int(time.time())}:{keep_family or ''}", ex=_REFRESH_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Could not revoke refresh tokens for user %s: %s", user_id, exc)
        raise _UNAVAILABLE
