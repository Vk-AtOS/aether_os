"""
AetherOS — LLM Semantic Cache (PostgreSQL-backed)

Content-addressed cache: SHA-256(prompt + task_type + system) → response text.
Stored in the main PostgreSQL database (llm_cache_entries table) so all workers
share a single cache — no per-process SQLite files.

Hit rate targets:
  - Requirements/intake tasks: 60-80% hit (users ask similar things)
  - Code generation: 10-20% hit (unique per project)
  - Documentation: 40-60% hit (common patterns)
  Overall target: 25-35% hit rate → ~30% cost reduction on its own.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Task types NOT cached (code gen output must be unique per project)
_NO_CACHE_TASKS = {
    "code_generation", "security_scan", "testing", "architecture",
}


def _make_key(prompt: str, task_type: str, system: Optional[str], org_id: Optional[str] = None) -> str:
    # B8: org_id scopes the cache — prevents cross-tenant response leak
    payload = f"{org_id or 'global'}:{task_type}||{system or ''}||{prompt}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LLMCache:
    """
    Async semantic cache backed by the shared PostgreSQL database.
    All workers share one cache — cache warmth accumulates across instances.
    """

    def is_cacheable(self, task_type: str) -> bool:
        return task_type not in _NO_CACHE_TASKS

    async def get(self, prompt: str, task_type: str, system: Optional[str] = None, org_id: Optional[str] = None) -> Optional[str]:
        if not self.is_cacheable(task_type):
            return None
        key = _make_key(prompt, task_type, system, org_id)
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import LLMCacheEntry
            from sqlalchemy import update as _upd

            sf = get_session_factory()
            async with sf() as session:
                entry = await session.get(LLMCacheEntry, key)
                if entry:
                    # Update hit stats
                    await session.execute(
                        _upd(LLMCacheEntry)
                        .where(LLMCacheEntry.cache_key == key)
                        .values(hit_count=LLMCacheEntry.hit_count + 1, last_hit_at=time.time())
                    )
                    await session.commit()
                    logger.debug("Cache HIT: task=%s key=%s…", task_type, key[:12])
                    return entry.response
        except Exception as exc:
            logger.debug("Cache get failed: %s", exc)
        return None

    async def set(
        self,
        prompt: str,
        task_type: str,
        response: str,
        system: Optional[str] = None,
        prompt_tokens: int = 0,
        org_id: Optional[str] = None,
    ) -> None:
        if not self.is_cacheable(task_type):
            return
        key = _make_key(prompt, task_type, system, org_id)
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import LLMCacheEntry

            sf = get_session_factory()
            async with sf() as session:
                # Upsert — INSERT … ON CONFLICT DO NOTHING (keep first cached response)
                existing = await session.get(LLMCacheEntry, key)
                if not existing:
                    session.add(LLMCacheEntry(
                        cache_key=key,
                        task_type=task_type,
                        response=response,
                        prompt_tokens=prompt_tokens,
                        hit_count=0,
                        created_at=time.time(),
                        last_hit_at=time.time(),
                    ))
                    await session.commit()
        except Exception as exc:
            logger.debug("Cache set failed: %s", exc)

    async def get_stats(self) -> dict:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import LLMCacheEntry
            from sqlalchemy import func, select

            sf = get_session_factory()
            async with sf() as session:
                row = (await session.execute(
                    select(func.count(LLMCacheEntry.cache_key), func.sum(LLMCacheEntry.hit_count))
                )).one()
                return {
                    "total_entries": row[0] or 0,
                    "total_hits":    row[1] or 0,
                    "daily": [],  # daily breakdown requires a time-bucketed query — omit for now
                }
        except Exception as exc:
            logger.debug("Cache stats failed: %s", exc)
            return {"total_entries": 0, "total_hits": 0, "daily": []}


# ── Singleton ─────────────────────────────────────────────────────────────────

_cache: Optional[LLMCache] = None


def get_llm_cache() -> LLMCache:
    global _cache
    if _cache is None:
        _cache = LLMCache()
    return _cache
