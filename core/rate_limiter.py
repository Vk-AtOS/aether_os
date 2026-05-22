"""
AetherOS — Redis-backed Rate Limiter
Falls back to in-memory if Redis is unavailable (single-worker dev mode only).

Redis is required in multi-worker production. Set REDIS_URL env var.
Default: redis://localhost:6379/0
"""
from __future__ import annotations
import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── Async Redis connection ────────────────────────────────────────────────────

_async_redis_client = None
_redis_available: Optional[bool] = None  # None = not yet tested


async def _get_async_redis():
    """Lazy-init async Redis connection. Returns None if unavailable."""
    global _async_redis_client, _redis_available
    if _redis_available is not None:
        return _async_redis_client if _redis_available else None
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis.asyncio as aioredis
        _async_redis_client = aioredis.Redis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=2
        )
        await _async_redis_client.ping()
        _redis_available = True
        logger.info("Rate limiter: async Redis connected at %s", redis_url.split("@")[-1])
    except Exception as exc:
        _redis_available = False
        logger.warning(
            "Rate limiter: Redis unavailable (%s). "
            "Using in-memory fallback — NOT safe for multi-worker deployments. "
            "Set REDIS_URL and ensure Redis is running.",
            exc,
        )
    return _async_redis_client if _redis_available else None


# ── Async Redis helpers (sliding window counter) ──────────────────────────────

async def _redis_incr_window(r, key: str, window_seconds: int) -> int:
    """Increment a sliding-window counter in Redis. Returns new count."""
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - (window_seconds * 1000)
    async with r.pipeline() as pipe:
        await pipe.zremrangebyscore(key, 0, cutoff)
        await pipe.zadd(key, {str(now_ms): now_ms})
        await pipe.zcard(key)
        await pipe.expire(key, window_seconds + 5)
        results = await pipe.execute()
    return results[2]  # zcard result


async def _redis_get_count(r, key: str, window_seconds: int) -> int:
    """Get current sliding-window count without incrementing."""
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - (window_seconds * 1000)
    await r.zremrangebyscore(key, 0, cutoff)
    return await r.zcard(key)


# ── In-memory fallback (single worker only) ───────────────────────────────────

class _MemoryStore:
    def __init__(self):
        self.active_runs: dict = defaultdict(int)
        self.hourly_starts: dict = defaultdict(list)
        self.login_attempts: dict = defaultdict(list)
        self.registrations: dict = defaultdict(list)


_mem = _MemoryStore()


# ── Public RateLimiter API (async) ────────────────────────────────────────────

class RateLimiter:
    def __init__(self):
        self.max_concurrent_runs     = int(os.environ.get("MAX_CONCURRENT_RUNS_PER_ORG", 5))
        self.max_starts_per_hour     = int(os.environ.get("MAX_STARTS_PER_ORG_PER_HOUR", 20))
        self.max_login_attempts      = int(os.environ.get("MAX_LOGIN_ATTEMPTS_PER_IP", 20))
        self.max_registrations       = int(os.environ.get("MAX_REGISTRATIONS_PER_IP", 5))
        self.max_factory_starts_per_min = int(os.environ.get("MAX_FACTORY_STARTS_PER_MIN", 10))

    # ── concurrent run guard ──────────────────────────────────────────────────

    async def check_concurrent_runs(self, org_id: str) -> bool:
        r = await _get_async_redis()
        if r:
            try:
                count = int(await r.get(f"concurrent:{org_id}") or 0)
                return count < self.max_concurrent_runs
            except Exception:
                pass
        return _mem.active_runs[org_id] < self.max_concurrent_runs

    async def record_run_start(self, org_id: str):
        r = await _get_async_redis()
        if r:
            try:
                await r.incr(f"concurrent:{org_id}")
                await r.expire(f"concurrent:{org_id}", 7200)
                await _redis_incr_window(r, f"hourly_starts:{org_id}", 3600)
                return
            except Exception:
                pass
        _mem.active_runs[org_id] += 1
        _mem.hourly_starts[org_id].append(time.time())

    async def record_run_end(self, org_id: str):
        r = await _get_async_redis()
        if r:
            try:
                cur = int(await r.get(f"concurrent:{org_id}") or 0)
                if cur > 0:
                    await r.decr(f"concurrent:{org_id}")
                return
            except Exception:
                pass
        if _mem.active_runs[org_id] > 0:
            _mem.active_runs[org_id] -= 1

    # ── factory start per-minute guard ───────────────────────────────────────

    async def check_factory_start(self, org_id: str) -> bool:
        """Hard cap on /factory/start calls per minute per org."""
        r = await _get_async_redis()
        if r:
            try:
                count = await _redis_get_count(r, f"factory_start_min:{org_id}", 60)
                return count < self.max_factory_starts_per_min
            except Exception:
                pass
        return True  # fallback: allow (mem fallback doesn't track per-minute here)

    async def record_factory_start(self, org_id: str):
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"factory_start_min:{org_id}", 60)
            except Exception:
                pass

    # ── hourly starts guard ───────────────────────────────────────────────────

    async def check_hourly_starts(self, org_id: str) -> bool:
        r = await _get_async_redis()
        if r:
            try:
                count = await _redis_get_count(r, f"hourly_starts:{org_id}", 3600)
                return count < self.max_starts_per_hour
            except Exception:
                pass
        now = time.time()
        _mem.hourly_starts[org_id] = [t for t in _mem.hourly_starts[org_id] if now - t < 3600]
        return len(_mem.hourly_starts[org_id]) < self.max_starts_per_hour

    # ── login / registration guards ───────────────────────────────────────────

    def _is_exempt_ip(self, ip: str) -> bool:
        """Localhost IPs are exempt from rate limiting in non-production mode.
        This allows load tests and automated testing from the same machine.
        In production, all IPs including localhost are rate-limited."""
        if os.environ.get("ENVIRONMENT", "development") == "production":
            return False
        return ip in ("127.0.0.1", "::1", "localhost", "unknown")

    async def check_login_attempts(self, ip: str) -> bool:
        if self._is_exempt_ip(ip):
            return True
        r = await _get_async_redis()
        if r:
            try:
                return await _redis_get_count(r, f"login:{ip}", 900) < self.max_login_attempts
            except Exception:
                pass
        now = time.time()
        _mem.login_attempts[ip] = [t for t in _mem.login_attempts[ip] if now - t < 900]
        return len(_mem.login_attempts[ip]) < self.max_login_attempts

    async def record_login_attempt(self, ip: str):
        if self._is_exempt_ip(ip):
            return
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"login:{ip}", 900)
                return
            except Exception:
                pass
        _mem.login_attempts[ip].append(time.time())

    async def check_registration_attempts(self, ip: str) -> bool:
        if self._is_exempt_ip(ip):
            return True
        r = await _get_async_redis()
        if r:
            try:
                return await _redis_get_count(r, f"reg:{ip}", 3600) < self.max_registrations
            except Exception:
                pass
        now = time.time()
        _mem.registrations[ip] = [t for t in _mem.registrations[ip] if now - t < 3600]
        return len(_mem.registrations[ip]) < self.max_registrations

    async def record_registration_attempt(self, ip: str):
        if self._is_exempt_ip(ip):
            return
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"reg:{ip}", 3600)
                return
            except Exception:
                pass
        _mem.registrations[ip].append(time.time())

    # ── public (unauthenticated) endpoint guard ───────────────────────────────

    async def record_public_request(self, ip: str) -> None:
        """Count a request to a public, unauthenticated endpoint."""
        if self._is_exempt_ip(ip):
            return
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"pub:{ip}", 60)
            except Exception:
                pass

    async def check_public_ratelimit(self, ip: str, max_per_minute: int = 100) -> bool:
        """True = request is allowed. False = 429 should be returned."""
        if self._is_exempt_ip(ip):
            return True
        r = await _get_async_redis()
        if r:
            try:
                return await _redis_get_count(r, f"pub:{ip}", 60) < max_per_minute
            except Exception:
                pass
        return True  # allow on Redis failure


_instance: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _instance
    if _instance is None:
        _instance = RateLimiter()
    return _instance


# ── Async Redis-backed SSE token store ────────────────────────────────────────

_SSE_TTL = 30  # seconds
_sse_memory: dict = {}  # in-memory fallback only


async def sse_token_set(token: str, org_id: str, run_id: str) -> None:
    """Store a short-lived SSE exchange token (expires in 30s)."""
    r = await _get_async_redis()
    if r:
        try:
            import json
            await r.setex(f"sse:{token}", _SSE_TTL, json.dumps({"org_id": org_id, "run_id": run_id}))
            return
        except Exception as exc:
            logger.warning("SSE token Redis write failed: %s", exc)
    _sse_memory[token] = {"org_id": org_id, "run_id": run_id, "exp": time.time() + _SSE_TTL}


async def sse_token_pop(token: str) -> Optional[dict]:
    """Consume (pop) an SSE token. Returns {org_id, run_id} or None if invalid/expired."""
    r = await _get_async_redis()
    if r:
        try:
            import json
            key = f"sse:{token}"
            async with r.pipeline() as pipe:
                await pipe.get(key)
                await pipe.delete(key)
                val, _ = await pipe.execute()
            return json.loads(val) if val else None
        except Exception as exc:
            logger.warning("SSE token Redis pop failed: %s", exc)
    entry = _sse_memory.pop(token, None)
    if entry and entry.get("exp", 0) > time.time():
        return entry
    return None
