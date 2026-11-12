"""
AetherOS — Redis-backed Rate Limiter
Falls back to in-memory if Redis is unavailable (single-worker dev mode only).

Redis is required in multi-worker production. Set REDIS_URL env var.
Default: redis://localhost:6379/0
"""
from __future__ import annotations
import asyncio
import ipaddress
import logging
import os
import time
from collections import defaultdict
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# ── Trusted proxy CIDRs (SEC-C3) ─────────────────────────────────────────────
# Only trust X-Forwarded-For when the direct connection comes from these ranges.
# Extend via TRUSTED_PROXY_CIDRS env var (comma-separated CIDR list).
_DEFAULT_TRUSTED_CIDRS = ["127.0.0.1/32", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


def _build_trusted_networks() -> list:
    raw = os.environ.get("TRUSTED_PROXY_CIDRS", "")
    cidrs = [c.strip() for c in raw.split(",") if c.strip()] if raw else _DEFAULT_TRUSTED_CIDRS
    nets = []
    for c in cidrs:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError as exc:
            logger.warning("Invalid TRUSTED_PROXY_CIDRS entry %r: %s", c, exc)
    return nets


_TRUSTED_NETWORKS: list = _build_trusted_networks()


def get_client_ip(request: "Request") -> str:
    """Return the authoritative client IP for rate-limiting purposes.

    SEC-C3: X-Forwarded-For is only trusted when the direct connection
    (request.client.host) comes from a known trusted proxy CIDR. Otherwise
    the direct connection IP is used, preventing spoofing via forged headers.
    """
    direct_ip = request.client.host if request.client else None
    if not direct_ip:
        logger.warning("Rate limiter: request.client is None — using 'unknown_ip' bucket")
        return "unknown_ip"

    # Only honour X-Forwarded-For from trusted proxies
    try:
        direct_addr = ipaddress.ip_address(direct_ip)
        is_trusted_proxy = any(direct_addr in net for net in _TRUSTED_NETWORKS)
    except ValueError:
        is_trusted_proxy = False

    if is_trusted_proxy:
        xff = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if xff:
            return xff

    return direct_ip

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
        import redis.asyncio as aioredis  # optional dependency — gracefully falls back to in-memory if not installed
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
        self.max_login_attempts      = int(os.environ.get("MAX_LOGIN_ATTEMPTS_PER_IP", 5))
        self.max_registrations       = int(os.environ.get("MAX_REGISTRATIONS_PER_IP", 5))
        self.max_factory_starts_per_min = int(os.environ.get("MAX_FACTORY_STARTS_PER_MIN", 10))

    # ── concurrent run guard ──────────────────────────────────────────────────

    async def check_concurrent_runs(self, org_id: str) -> bool:
        r = await _get_async_redis()
        if r:
            try:
                count = int(await r.get(f"concurrent:{org_id}") or 0)
                return count < self.max_concurrent_runs
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
        return _mem.active_runs[org_id] < self.max_concurrent_runs

    async def record_run_start(self, org_id: str):
        r = await _get_async_redis()
        if r:
            try:
                await r.incr(f"concurrent:{org_id}")
                await r.expire(f"concurrent:{org_id}", 7200)
                await _redis_incr_window(r, f"hourly_starts:{org_id}", 3600)
                return
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
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
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
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
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
        return True  # fallback: allow on Redis failure (non-auth endpoint)

    async def record_factory_start(self, org_id: str):
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"factory_start_min:{org_id}", 60)
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)

    # ── hourly starts guard ───────────────────────────────────────────────────

    async def check_hourly_starts(self, org_id: str) -> bool:
        r = await _get_async_redis()
        if r:
            try:
                count = await _redis_get_count(r, f"hourly_starts:{org_id}", 3600)
                return count < self.max_starts_per_hour
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
        now = time.time()
        _mem.hourly_starts[org_id] = [t for t in _mem.hourly_starts[org_id] if now - t < 3600]
        return len(_mem.hourly_starts[org_id]) < self.max_starts_per_hour

    # ── login / registration guards ───────────────────────────────────────────

    def _is_exempt_ip(self, ip: str) -> bool:
        """Localhost IPs are exempt from rate limiting in non-production mode.
        This allows load tests and automated testing from the same machine.
        In production, all IPs including localhost are rate-limited.
        SEC-037: "unknown" is never exempt — unknown IPs are rate-limited together."""
        if os.environ.get("ENVIRONMENT", "development") == "production":
            return False
        # "unknown" intentionally excluded: must be rate-limited (SEC-037)
        return ip in ("127.0.0.1", "::1", "localhost")

    def _normalize_ip(self, ip: str) -> str:
        """Return a rate-limiting key for this IP.
        SEC-037: If IP is unknown/empty, use 'unknown_ip' key so all
        unknown-IP requests share a single rate-limit bucket."""
        if not ip or ip == "unknown":
            logger.warning("Rate limiter: client IP could not be determined; using 'unknown_ip' bucket")
            return "unknown_ip"
        return ip

    async def check_login_attempts(self, ip: str, strict_mode: bool = True) -> bool:
        """True = allowed. False = rate-limited.
        SEC-037: unknown IP uses 'unknown_ip' bucket (never exempt).
        SEC-038: Redis failure in strict_mode (default) returns False (deny)."""
        if self._is_exempt_ip(ip):
            return True
        effective_ip = self._normalize_ip(ip)
        r = await _get_async_redis()
        if r:
            try:
                return await _redis_get_count(r, f"login:{effective_ip}", 900) < self.max_login_attempts
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
                if strict_mode:
                    logger.warning("Rate limiter: Redis failure on login check — denying (strict mode)")
                    return False
        # Redis unavailable (not connected) — fall through to in-memory fallback.
        # SEC-038: in strict_mode with no Redis, log a warning and use memory store
        # (acceptable single-worker fallback; multi-worker deployments must have Redis).
        if strict_mode:
            logger.warning(
                "Rate limiter: Redis unavailable on login check — falling back to in-memory store "
                "(per-worker only, NOT safe for multi-worker deployments)"
            )
        now = time.time()
        _mem.login_attempts[effective_ip] = [
            t for t in _mem.login_attempts[effective_ip] if now - t < 900
        ]
        return len(_mem.login_attempts[effective_ip]) < self.max_login_attempts

    async def record_login_attempt(self, ip: str):
        if self._is_exempt_ip(ip):
            return
        effective_ip = self._normalize_ip(ip)
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"login:{effective_ip}", 900)
                return
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
        _mem.login_attempts[effective_ip].append(time.time())

    async def check_registration_attempts(self, ip: str, strict_mode: bool = True) -> bool:
        """True = allowed. False = rate-limited.
        SEC-037: unknown IP uses 'unknown_ip' bucket.
        SEC-038: Redis failure in strict_mode returns False (deny)."""
        if self._is_exempt_ip(ip):
            return True
        effective_ip = self._normalize_ip(ip)
        r = await _get_async_redis()
        if r:
            try:
                return await _redis_get_count(r, f"reg:{effective_ip}", 3600) < self.max_registrations
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
                if strict_mode:
                    logger.warning("Rate limiter: Redis failure on registration check — denying (strict mode)")
                    return False
        now = time.time()
        _mem.registrations[effective_ip] = [
            t for t in _mem.registrations[effective_ip] if now - t < 3600
        ]
        return len(_mem.registrations[effective_ip]) < self.max_registrations

    async def record_registration_attempt(self, ip: str):
        if self._is_exempt_ip(ip):
            return
        effective_ip = self._normalize_ip(ip)
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"reg:{effective_ip}", 3600)
                return
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
        _mem.registrations[effective_ip].append(time.time())

    # ── password reset guard (SEC-H3: 5 requests per 15 minutes per IP) ─────

    async def check_password_reset_attempts(self, ip: str) -> bool:
        """True = allowed. False = rate-limited (5 per 15 min per IP)."""
        if self._is_exempt_ip(ip):
            return True
        effective_ip = self._normalize_ip(ip)
        max_attempts = int(os.environ.get("MAX_PASSWORD_RESET_PER_IP", 5))
        window = 900  # 15 minutes
        r = await _get_async_redis()
        if r:
            try:
                return await _redis_get_count(r, f"pwreset:{effective_ip}", window) < max_attempts
            except Exception as e:
                logger.warning("Rate limiter Redis error on password reset check: %s", e)
        # In-memory fallback uses registrations bucket (same TTL / same shape)
        now = time.time()
        _mem.registrations[f"pwreset:{effective_ip}"] = [
            t for t in _mem.registrations[f"pwreset:{effective_ip}"] if now - t < window
        ]
        return len(_mem.registrations[f"pwreset:{effective_ip}"]) < max_attempts

    async def record_password_reset_attempt(self, ip: str) -> None:
        if self._is_exempt_ip(ip):
            return
        effective_ip = self._normalize_ip(ip)
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"pwreset:{effective_ip}", 900)
                return
            except Exception as e:
                logger.warning("Rate limiter Redis error on password reset record: %s", e)
        _mem.registrations[f"pwreset:{effective_ip}"].append(time.time())

    # ── public (unauthenticated) endpoint guard ───────────────────────────────

    async def record_public_request(self, ip: str) -> None:
        """Count a request to a public, unauthenticated endpoint."""
        if self._is_exempt_ip(ip):
            return
        effective_ip = self._normalize_ip(ip)
        r = await _get_async_redis()
        if r:
            try:
                await _redis_incr_window(r, f"pub:{effective_ip}", 60)
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)

    async def check_public_ratelimit(self, ip: str, max_per_minute: int = 100) -> bool:
        """True = request is allowed. False = 429 should be returned."""
        if self._is_exempt_ip(ip):
            return True
        effective_ip = self._normalize_ip(ip)
        r = await _get_async_redis()
        if r:
            try:
                return await _redis_get_count(r, f"pub:{effective_ip}", 60) < max_per_minute
            except Exception as e:
                logger.warning("Rate limiter Redis error: %s", e)
        return True  # allow on Redis failure for non-auth public endpoints


_instance: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _instance
    if _instance is None:
        _instance = RateLimiter()
    return _instance


# SSE exchange tokens live with the other token state in gateway/auth_refresh.py
# (Redis only, 503 when Redis is down): an in-process fallback broke with several
# workers and let one token be spent once per worker.


# ── Run-App port registry (multi-worker-safe via Redis) ───────────────────────
_RUN_APP_KEY = "run_app:current"
_RUN_APP_TTL = 3600  # 1 hour

_run_app_port_memory: dict = {}


async def run_app_port_set(run_id: str, port: int) -> None:
    """Publish the ephemeral port for a run so all workers can proxy to it."""
    r = await _get_async_redis()
    if r:
        try:
            await r.set(_RUN_APP_KEY, f"{run_id}:{port}", ex=_RUN_APP_TTL)
            return
        except Exception as exc:
            logger.warning("run_app_port_set Redis write failed: %s", exc)
    _run_app_port_memory["current"] = {"run_id": run_id, "port": port}


async def run_app_port_get() -> tuple:
    """Return (run_id, port) of the most-recently started run-app, or (None, None)."""
    r = await _get_async_redis()
    if r:
        try:
            val = await r.get(_RUN_APP_KEY)
            if val:
                rid, p = val.split(":", 1)
                return rid, int(p)
            return None, None
        except Exception as exc:
            logger.warning("run_app_port_get Redis read failed: %s", exc)
    entry = _run_app_port_memory.get("current")
    if entry:
        return entry["run_id"], entry["port"]
    return None, None


async def run_app_port_clear() -> None:
    """Remove the current run-app port registration."""
    r = await _get_async_redis()
    if r:
        try:
            await r.delete(_RUN_APP_KEY)
        except Exception as exc:
            logger.warning("run_app_port_clear failed: %s", exc)
    _run_app_port_memory.pop("current", None)
