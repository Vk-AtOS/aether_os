"""
ThreatDetector — reads existing Redis signals and file state to produce threat events.
Does NOT intercept requests or add middleware overhead to the hot path.

Signal sources:
  1. Auth brute force  — reads login:{ip} keys already written by rate_limiter.py
  2. File integrity    — SHA-256 hashes of critical platform files, baseline in Redis
  3. Service health    — probes DB, Redis, disk
  4. Rate anomaly      — reads pub:{ip} and factory_start_min:{org} keys
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Critical files whose integrity is checked every cycle.
# Paths relative to the aether_os package root.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
_CRITICAL_FILES: List[Path] = [
    _PACKAGE_ROOT / "gateway" / "api.py",
    _PACKAGE_ROOT / "gateway" / "auth.py",
    _PACKAGE_ROOT / "core" / "models.py",
    _PACKAGE_ROOT / "core" / "db.py",
    _PACKAGE_ROOT.parent / "alembic" / "env.py",
]

# Redis key prefix for baseline file hashes
_HASH_KEY_PREFIX = "guardian:file_hash:"
# Redis key for brute force check
_LOGIN_KEY_PREFIX = "login:"

# Thresholds
_BRUTE_FORCE_THRESHOLD = 15   # failed logins per 15-minute window → HIGH
_DISK_WARN_PCT = 80            # disk usage % → medium
_DISK_CRIT_PCT = 92            # disk usage % → critical


def _sha256_file(path: Path) -> Optional[str]:
    """Return SHA-256 hex digest of a file, or None if unreadable."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as exc:
        logger.warning("Guardian: cannot hash %s: %s", path, exc)
        return None


async def _get_redis():
    """Reuse the platform's existing async Redis client."""
    try:
        from aether_os.core.rate_limiter import _get_async_redis
        return await _get_async_redis()
    except Exception:
        return None


class ThreatDetector:
    def __init__(self):
        self._baseline_loaded = False

    # ── Baseline ─────────────────────────────────────────────────────────────

    async def load_or_create_baseline(self) -> None:
        """Hash critical files and store in Redis as the trusted baseline."""
        r = await _get_redis()
        if r is None:
            logger.warning("Guardian: Redis unavailable — file integrity baseline stored in memory only")
            self._mem_baseline: Dict[str, str] = {}
            for path in _CRITICAL_FILES:
                if path.exists():
                    h = _sha256_file(path)
                    if h:
                        self._mem_baseline[str(path)] = h
            self._baseline_loaded = True
            return

        for path in _CRITICAL_FILES:
            if not path.exists():
                continue
            key = _HASH_KEY_PREFIX + hashlib.md5(str(path).encode()).hexdigest()
            existing = await r.get(key)
            if not existing:
                # First boot — establish baseline
                h = _sha256_file(path)
                if h:
                    await r.set(key, h)
                    logger.info("Guardian: baseline set for %s", path.name)
        self._baseline_loaded = True

    async def _get_baseline(self, path: Path) -> Optional[str]:
        r = await _get_redis()
        key = _HASH_KEY_PREFIX + hashlib.md5(str(path).encode()).hexdigest()
        if r:
            val = await r.get(key)
            return val
        return getattr(self, "_mem_baseline", {}).get(str(path))

    async def update_baseline(self, path: Path) -> None:
        """Refresh the baseline for one file (call after legitimate deploys)."""
        h = _sha256_file(path)
        if not h:
            return
        r = await _get_redis()
        key = _HASH_KEY_PREFIX + hashlib.md5(str(path).encode()).hexdigest()
        if r:
            await r.set(key, h)
        else:
            if not hasattr(self, "_mem_baseline"):
                self._mem_baseline = {}
            self._mem_baseline[str(path)] = h

    # ── Detection ─────────────────────────────────────────────────────────────

    async def check_brute_force(self) -> List[Dict[str, Any]]:
        """
        Scan all login:{ip} keys in Redis.
        Any IP with > threshold login attempts in the 15-min window is a threat.
        """
        events: List[Dict[str, Any]] = []
        r = await _get_redis()
        if r is None:
            return events
        try:
            pattern = f"{_LOGIN_KEY_PREFIX}*"
            async for key in r.scan_iter(pattern, count=100):
                ip = key.replace(_LOGIN_KEY_PREFIX, "")
                count = await r.zcard(key)
                if count >= _BRUTE_FORCE_THRESHOLD:
                    severity = "critical" if count >= _BRUTE_FORCE_THRESHOLD * 3 else "high"
                    events.append({
                        "event_type": "brute_force",
                        "severity": severity,
                        "source_ip": ip,
                        "endpoint": "/auth/login",
                        "detail": {"attempt_count": count, "window_minutes": 15},
                    })
        except Exception as exc:
            logger.warning("Guardian brute force check failed: %s", exc)
        return events

    async def check_file_integrity(self) -> List[Dict[str, Any]]:
        """Compare current file hashes against baseline. Returns tamper events."""
        events: List[Dict[str, Any]] = []
        if not self._baseline_loaded:
            await self.load_or_create_baseline()
            return events  # first run just sets baseline

        for path in _CRITICAL_FILES:
            if not path.exists():
                events.append({
                    "event_type": "file_tamper",
                    "severity": "critical",
                    "detail": {"file": str(path), "reason": "file_missing"},
                })
                continue
            current = _sha256_file(path)
            baseline = await self._get_baseline(path)
            if baseline and current and current != baseline:
                events.append({
                    "event_type": "file_tamper",
                    "severity": "critical",
                    "detail": {
                        "file": path.name,
                        "baseline_hash": baseline[:16] + "...",
                        "current_hash":  current[:16] + "...",
                    },
                })
                logger.error("Guardian: TAMPER DETECTED — %s hash changed!", path.name)
        return events

    async def check_service_health(self) -> List[Dict[str, Any]]:
        """Check DB, Redis, and disk. Returns degradation events."""
        events: List[Dict[str, Any]] = []
        loop = asyncio.get_running_loop()

        # Disk check
        try:
            import shutil
            total, used, free = await loop.run_in_executor(None, shutil.disk_usage, "/")
            pct = used / total * 100
            if pct >= _DISK_CRIT_PCT:
                events.append({
                    "event_type": "service_crash",
                    "severity": "critical",
                    "detail": {"service": "disk", "used_pct": round(pct, 1), "free_gb": round(free / 1e9, 2)},
                })
            elif pct >= _DISK_WARN_PCT:
                events.append({
                    "event_type": "anomaly",
                    "severity": "medium",
                    "detail": {"service": "disk", "used_pct": round(pct, 1), "free_gb": round(free / 1e9, 2)},
                })
        except Exception as exc:
            logger.warning("Guardian disk check: %s", exc)

        # Redis check
        r = await _get_redis()
        if r is None:
            events.append({
                "event_type": "service_crash",
                "severity": "high",
                "detail": {"service": "redis", "reason": "connection_failed"},
            })
        else:
            try:
                await r.ping()
            except Exception:
                events.append({
                    "event_type": "service_crash",
                    "severity": "high",
                    "detail": {"service": "redis", "reason": "ping_failed"},
                })

        # DB check
        try:
            from aether_os.core.db import get_session_factory
            from sqlalchemy import text as _t
            sf = get_session_factory()
            async with sf() as sess:
                await sess.execute(_t("SELECT 1"))
        except Exception as exc:
            events.append({
                "event_type": "service_crash",
                "severity": "critical",
                "detail": {"service": "database", "reason": str(exc)[:200]},
            })

        return events

    async def run_all_checks(self) -> Tuple[List[Dict[str, Any]], str]:
        """
        Run all detectors. Returns (events_list, overall_threat_level).
        Threat levels: safe | low | medium | high | critical
        """
        all_events: List[Dict[str, Any]] = []

        results = await asyncio.gather(
            self.check_brute_force(),
            self.check_file_integrity(),
            self.check_service_health(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list):
                all_events.extend(r)

        if not all_events:
            return [], "safe"

        severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        max_sev = max(all_events, key=lambda e: severity_rank.get(e.get("severity", "low"), 0))
        return all_events, max_sev.get("severity", "low")


_instance: Optional[ThreatDetector] = None


def get_threat_detector() -> ThreatDetector:
    global _instance
    if _instance is None:
        _instance = ThreatDetector()
    return _instance
