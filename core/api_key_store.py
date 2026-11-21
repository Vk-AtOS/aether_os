"""
Per-org API key store.
Lookup order: org_api_keys table → os.environ (platform-level fallback)

An org's key is only ever returned from get_api_key(provider, org_id) and handed
to the provider client for that one call. It is never written to os.environ:
the process environment is shared by every tenant, so a key placed there became
every other org's "platform" fallback.

Import this module as aether_os.core.api_key_store only. Importing it as
core.api_key_store creates a second module object with its own cache (and its
own database engine), which is how saved keys used to be invisible to callers.
"""
import logging
import os
import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from aether_os.core.db import get_session_factory
from aether_os.core.models import OrgApiKey

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
        if cached:
            return cached
        # A cached "" means "this org has no key of its own": skip the DB, but still fall back to the platform key
        # below. It used to return None here, so only an org's FIRST call found the platform key and every later
        # call failed with "not configured" (AWS testbed, 21 Nov 2026: council passed, the pipeline then had no model).
        if cached is None:
            try:
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

    # Fallback to the platform's own keys (set by the operator, never by an org)
    for var in _ENV_VARS.get(provider, []):
        val = os.environ.get(var, "")
        if val:
            return val
    return None


async def save_api_key(provider: str, org_id: str, api_key: str, user_id: str = "") -> None:
    """Persist an API key for an org. Takes effect on that org's next call (cache invalidated)."""
    session_factory = get_session_factory()

    # Detect dialect and use appropriate upsert
    async with session_factory() as session:
        try:
            stmt = pg_insert(OrgApiKey).values(
                org_id=org_id,
                provider=provider,
                api_key=api_key,
                updated_at=time.time(),
                updated_by=user_id or None,
            ).on_conflict_do_update(
                constraint="uq_org_provider",
                set_={
                    "api_key": api_key,
                    "updated_at": time.time(),
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
                existing.updated_at = time.time()
                existing.updated_by = user_id or None
            else:
                session.add(OrgApiKey(
                    org_id=org_id,
                    provider=provider,
                    api_key=api_key,
                    updated_at=time.time(),
                    updated_by=user_id or None,
                ))
        await session.commit()

    # Invalidate cache so next lookup picks up new value
    invalidate(org_id, provider)
