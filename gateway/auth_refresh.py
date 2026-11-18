"""
AetherOS — refresh-token state (rotation, reuse detection, revocation).

A refresh token is single-use. Every sign-in starts a token *family* (claim
``fam``, carried by both the access and the refresh token); each refresh issues
a new pair in the same family and spends the old refresh token.

Redis keys (same store and conventions as the access-token blacklist):
  jwt:blacklist:{jti}          spent or revoked token (shared with access tokens)
  jwt:family_revoked:{fam}     whole family revoked (logout, or a spent token was replayed)
  jwt:refresh_cutoff:{user_id} "<unix_ts>:<exempt_fam>" — every token of the user (access
                               and refresh) issued at or before the timestamp is dead,
                               except family <exempt_fam> (password change/reset)

Fail closed: if Redis cannot answer, nothing is refreshed, no access token is
accepted (503), and nothing is reported as revoked.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as aioredis
from fastapi import HTTPException

from aether_os.core.pipeline_state import REDIS_URL, get_redis
from aether_os.core.resilience.redis_breaker import breaker_connection_class
from aether_os.gateway.auth import create_access_token, create_refresh_token

logger = logging.getLogger(__name__)

_REFRESH_TTL_SECONDS = 30 * 86400  # lifetime of a refresh token (create_refresh_token default)
_UNAVAILABLE = HTTPException(
    status_code=503, detail="Auth service temporarily unavailable — please retry",
    headers={"Retry-After": "5"},
)

# Short in-process verdict cache for assert_access_token_live, so a burst of requests on one
# token costs one Redis round trip, not one each. "live" is trusted for LIVE_TTL_S only (the
# revocation lag this adds); "revoked" is permanent for the life of the token. When Redis is
# down nothing is cached or assumed: requests still get 503 + Retry-After (fail closed).
LIVE_TTL_S = 2.0
_CACHE_MAX = 10_000
_verdicts: Dict[str, Tuple[float, bool]] = {}  # jti -> (expires monotonic, live)


def _remember(jti: str, live: bool, token_exp: float) -> None:
    if len(_verdicts) >= _CACHE_MAX:
        _verdicts.clear()  # ponytail: wholesale clear, bounded memory beats LRU bookkeeping
    now = time.monotonic()
    _verdicts[jti] = (now + (LIVE_TTL_S if live else max(1.0, token_exp - time.time())), live)
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


_own_client: Optional[Tuple[Any, Any]] = None  # (event loop, client)


async def _redis():
    """The token-state store. Never None: if it is down, the command that follows raises.

    get_redis() decides once, at its first call (startup), whether Redis exists,
    and answers None for the rest of the process if it did not. Revocation must
    not hang on that one moment — a gateway that started during a Redis blip
    would otherwise accept revoked tokens forever — so in that case this module
    talks to Redis through its own client, which connects per command.
    """
    global _own_client
    r = await get_redis()
    if r is not None:
        return r
    loop = asyncio.get_running_loop()
    if _own_client is None or _own_client[0] is not loop:  # a client is bound to the loop that made it
        _own_client = (loop, aioredis.from_url(REDIS_URL, decode_responses=True, connection_class=breaker_connection_class()))
    return _own_client[1]


def _before_cutoff(cutoff: Optional[str], claims: Dict[str, Any], family: str) -> bool:
    """True if the user's sessions were ended (password change/reset) after this token was issued."""
    if not cutoff:
        return False
    ts, _, exempt = str(cutoff).partition(":")
    # <= : iat has one-second resolution, so a token minted in the same second
    # as the password change is treated as older (fail closed).
    return family != exempt and int(claims.get("iat", 0)) <= int(ts)


async def assert_access_token_live(claims: Dict[str, Any]) -> None:
    """Every authenticated request passes here: 401 if the token was revoked, 503 if we cannot tell.

    Revoked means: this token blacklisted (logout), its family revoked (logout
    elsewhere, refresh-token replay), or the user's sessions ended by a password
    change/reset after it was issued. One round trip.
    """
    jti = claims.get("jti")
    if not jti:
        # Every token we mint has a jti; one without it cannot be revoked, so it is not accepted.
        raise HTTPException(status_code=401, detail="Token has been revoked")
    hit = _verdicts.get(jti)
    if hit and hit[0] > time.monotonic():
        if hit[1]:
            return
        raise HTTPException(status_code=401, detail="Token has been revoked")
    family, user_id = claims.get("fam") or jti, claims.get("user_id")
    keys = [f"jwt:blacklist:{jti}", family_key(family)] + ([_cutoff_key(user_id)] if user_id else [])
    try:
        r = await _redis()
        values = await r.mget(keys)
    except Exception as exc:
        logger.warning("Token revocation check failed (Redis unavailable) — denying request: %s", exc)
        raise _UNAVAILABLE from exc
    exp = claims.get("exp") if isinstance(claims.get("exp"), (int, float)) else time.time() + 3600
    if values[0] or values[1] or (user_id and _before_cutoff(values[2], claims, family)):
        _remember(jti, False, exp)
        raise HTTPException(status_code=401, detail="Token has been revoked")
    _remember(jti, True, exp)


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
        if _before_cutoff(await r.get(_cutoff_key(user_id)), claims, family):
            raise _REJECTED
        ttl = max(1, int(exp - time.time()))
        # SET NX is the atomic "first use wins": two concurrent refreshes cannot both pass.
        if not await r.set(f"jwt:blacklist:{jti}", "used", nx=True, ex=ttl):
            await r.set(family_key(family), "1", ex=_REFRESH_TTL_SECONDS)
            _verdicts.clear()
            logger.warning("Refresh token replayed (user=%s family=%s) — family revoked", user_id, family)
            raise _REJECTED
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Refresh token state check failed — denying refresh: %s", exc)
        raise _UNAVAILABLE from exc
    return family


async def revoke_session(claims: Dict[str, Any]) -> None:
    """Logout: blacklist this access token and revoke its refresh-token family."""
    jti, exp, family = claims.get("jti"), claims.get("exp"), claims.get("fam")
    _verdicts.clear()  # this worker must see the revocation at once (other workers: <= LIVE_TTL_S)
    try:
        r = await _redis()
        if jti and isinstance(exp, (int, float)):
            await r.set(f"jwt:blacklist:{jti}", "1", ex=max(1, int(exp - time.time())))
        if family:
            await r.set(family_key(family), "1", ex=_REFRESH_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Logout could not revoke tokens (jti=%s): %s", jti, exc)
        raise _UNAVAILABLE from exc


async def revoke_user_sessions(user_id: str, keep_family: Optional[str] = None) -> None:
    """Kill every access and refresh token the user holds now, except family
    `keep_family` (the session that is changing the password stays signed in).

    Access tokens used to survive this for up to their one-hour lifetime: only
    the refresh path read the cutoff. assert_access_token_live reads it too.
    """
    _verdicts.clear()
    try:
        r = await _redis()
        await r.set(_cutoff_key(user_id), f"{int(time.time())}:{keep_family or ''}", ex=_REFRESH_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Could not revoke sessions for user %s: %s", user_id, exc)
        raise _UNAVAILABLE from exc


# ── SSE exchange tokens ──────────────────────────────────────────────────────
# A 30-second, single-use token that stands in for the JWT on the EventSource URL
# (JWTs must not appear in URLs). Redis only: an in-process store is per worker,
# so it fails across workers and lets one token be spent once per worker.
_SSE_TTL_SECONDS = 30


async def sse_token_set(token: str, org_id: str, run_id: str) -> None:
    try:
        r = await _redis()
        await r.set(f"sse:{token}", json.dumps({"org_id": org_id, "run_id": run_id}), ex=_SSE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("SSE token could not be stored (Redis unavailable): %s", exc)
        raise _UNAVAILABLE from exc


async def sse_token_pop(token: str) -> Optional[Dict[str, Any]]:
    """Spend an SSE token: {org_id, run_id} the first time, None after (or if unknown/expired).
    GET and DELETE run as one transaction, so two connections cannot both spend it."""
    try:
        r = await _redis()
        async with r.pipeline(transaction=True) as pipe:
            await pipe.get(f"sse:{token}")
            await pipe.delete(f"sse:{token}")
            value, _ = await pipe.execute()
    except Exception as exc:
        logger.warning("SSE token could not be checked (Redis unavailable): %s", exc)
        raise _UNAVAILABLE from exc
    return json.loads(value) if value else None


# ── OAuth CSRF state ─────────────────────────────────────────────────────────
# Single-use, 10 minutes. Redis only for the same reason as the SSE tokens: the callback
# lands on any worker, and an in-process dict makes it fail on 3 of 4.
_OAUTH_STATE_TTL_SECONDS = 600


async def oauth_state_set(state: str, provider: str) -> None:
    try:
        r = await _redis()
        await r.set(f"oauthstate:{state}", provider, ex=_OAUTH_STATE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("OAuth state could not be stored (Redis unavailable): %s", exc)
        raise _UNAVAILABLE from exc


async def oauth_state_pop(state: str, provider: str) -> bool:
    """True once for a state issued for `provider` (atomic GET+DELETE), False otherwise."""
    try:
        r = await _redis()
        async with r.pipeline(transaction=True) as pipe:
            await pipe.get(f"oauthstate:{state}")
            await pipe.delete(f"oauthstate:{state}")
            value, _ = await pipe.execute()
    except Exception as exc:
        logger.warning("OAuth state could not be checked (Redis unavailable): %s", exc)
        raise _UNAVAILABLE from exc
    return value == provider


# ── OAuth sign-in codes ──────────────────────────────────────────────────────
# The OAuth callback must not put a JWT (or an MFA challenge token) in a URL: URLs reach browser history, proxy and
# access logs and Referer headers. It redirects with a random single-use code; the dashboard exchanges it once
# (POST /auth/oauth/exchange). Stored hashed in Redis for 60 s so any worker can serve the exchange.
_OAUTH_CODE_TTL_SECONDS = 60


def _code_key(code: str) -> str:
    return "oauthcode:" + hashlib.sha256(code.encode()).hexdigest()


async def oauth_code_set(code: str, payload: dict) -> None:
    try:
        r = await _redis()
        await r.set(_code_key(code), json.dumps(payload), ex=_OAUTH_CODE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("OAuth sign-in code could not be stored (Redis unavailable): %s", exc)
        raise _UNAVAILABLE from exc


async def oauth_code_pop(code: str) -> Optional[dict]:
    """The payload stored for `code`, once (atomic GET+DELETE); None for an unknown, spent or expired code."""
    try:
        r = await _redis()
        async with r.pipeline(transaction=True) as pipe:
            await pipe.get(_code_key(code))
            await pipe.delete(_code_key(code))
            value, _ = await pipe.execute()
    except Exception as exc:
        logger.warning("OAuth sign-in code could not be checked (Redis unavailable): %s", exc)
        raise _UNAVAILABLE from exc
    return json.loads(value) if value else None
