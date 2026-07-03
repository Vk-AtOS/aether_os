"""
Per-org API key store.
Lookup order: org_api_keys table → os.environ (system fallback)
"""
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Provider → env var name mapping
_ENV_VARS = {
    "anthropic":  ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
    "google":     ["GOOGLE_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "bedrock":    [],   # AWS uses credential chain, not API key
}

# Simple in-memory TTL cache: {(org_id, provider): (key, expires_at)}
_cache: dict = {}
_CACHE_TTL = 60  # seconds


def _cache_get(org_id: str, provider: str) -> Optional[str]:
    entry = _cache.get((org_id, provider))
    if entry and entry[1] > time.time():
        return entry[0]
    _cache.pop((org_id, provider), None)
    return None


def _cache_set(org_id: str, provider: str, key: str) -> None:
    _cache[(org_id, provider)] = (key, time.time() + _CACHE_TTL)


def invalidate(org_id: str, provider: str) -> None:
    """Call this after saving a new key so the next request picks it up."""
    _cache.pop((org_id, provider), None)


async def get_api_key(provider: str, org_id: Optional[str] = None) -> Optional[str]:
    """
    Return the API key for provider, preferring org-specific key over system key.
    Returns None if no key is configured.
    """
    if org_id:
        # Check cache first
        cached = _cache_get(org_id, provider)
        if cached is not None:
            return cached or None  # empty string = "no key"

        # Query DB
        try:
            from core.db import get_session_factory
            from core.models import OrgApiKey
            from sqlalchemy import select
            session_factory = get_session_factory()
            async with session_factory() as session:
                row = await session.execute(
                    select(OrgApiKey).where(
                        OrgApiKey.org_id == org_id,
                        OrgApiKey.provider == provider,
                    )
                )
                rec = row.scalar_one_or_none()
                key = rec.api_key if rec else ""
                _cache_set(org_id, provider, key)
                if key:
                    return key
        except Exception as exc:
            logger.warning("api_key_store: DB lookup failed for %s/%s: %s", org_id, provider, exc)

    # Fallback to system env vars
    for var in _ENV_VARS.get(provider, []):
        val = os.environ.get(var, "")
        if val:
            return val
    return None


async def save_api_key(provider: str, org_id: str, api_key: str, user_id: str = "") -> None:
    """Persist an API key for an org. Also updates os.environ for immediate effect."""
    import time as _time
    from core.db import get_session_factory
    from core.models import OrgApiKey
    from sqlalchemy import select

    session_factory = get_session_factory()

    # Detect dialect and use appropriate upsert
    async with session_factory() as session:
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(OrgApiKey).values(
                org_id=org_id,
                provider=provider,
                api_key=api_key,
                updated_at=_time.time(),
                updated_by=user_id or None,
            ).on_conflict_do_update(
                constraint="uq_org_provider",
                set_={
                    "api_key": api_key,
                    "updated_at": _time.time(),
                    "updated_by": user_id or None,
                },
            )
            await session.execute(stmt)
        except Exception as e:
            logger.debug("upsert_uq_org_provider conflict strategy unavailable, using fallback: %s", e)
            # SQLite fallback (or any non-postgres dialect)
            existing = (
                await session.execute(
                    select(OrgApiKey).where(
                        OrgApiKey.org_id == org_id,
                        OrgApiKey.provider == provider,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.api_key = api_key
                existing.updated_at = _time.time()
                existing.updated_by = user_id or None
            else:
                session.add(OrgApiKey(
                    org_id=org_id,
                    provider=provider,
                    api_key=api_key,
                    updated_at=_time.time(),
                    updated_by=user_id or None,
                ))
        await session.commit()

    # Invalidate cache so next lookup picks up new value
    invalidate(org_id, provider)

    # Also update os.environ for backward-compat with any code that still reads env directly
    for var in _ENV_VARS.get(provider, []):
        os.environ[var] = api_key
        break  # only set the first/primary env var
