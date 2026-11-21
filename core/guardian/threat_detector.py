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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aether_os.core.guardian.build_identity import (
    CRITICAL_REL_PATHS,
    MANIFEST_PATH,
    PACKAGE_ROOT,
    resolve_build_identity,
    sha256_file,
)

logger = logging.getLogger(__name__)

# Critical files whose integrity is checked every cycle.
# Paths relative to the aether_os package root.
_PACKAGE_ROOT = PACKAGE_ROOT
_MANIFEST_PATH = MANIFEST_PATH
_CRITICAL_FILES: List[Path] = [_PACKAGE_ROOT / rel for rel in CRITICAL_REL_PATHS]

# Legacy (no build identity) baseline: one key per file, guardian:file_hash:<md5(abs path)>. Still written by
# scripts/post-deploy.sh and still used on installs that have neither a build manifest nor AETHER_BUILD_ID.
_HASH_KEY_PREFIX = "guardian:file_hash:"
# Per-build baseline: one Redis hash per build, guardian:baseline:<build_id> → {rel_path: sha256}.
_BUILD_BASELINE_PREFIX = "guardian:baseline:"
# The build id whose baseline is current, so a build change is noticed and logged.
_CURRENT_BUILD_KEY = "guardian:current_build"
# A replaced build's baseline is kept this long (rolling deploys: old pods still check against it), then expires.
_OLD_BUILD_TTL_SECONDS = 7 * 24 * 3600
# Redis key for brute force check
_LOGIN_KEY_PREFIX = "login:"

# Thresholds
_BRUTE_FORCE_THRESHOLD = 15   # failed logins per 15-minute window → HIGH
_DISK_WARN_PCT = 80            # disk usage % → medium
_DISK_CRIT_PCT = 92            # disk usage % → critical

# Kept as a module-level name: other modules and tests use it from here.
_sha256_file = sha256_file


def _legacy_key(path: Path) -> str:
    return _HASH_KEY_PREFIX + hashlib.md5(str(path).encode(), usedforsecurity=False).hexdigest()


def _rel(path: Path) -> str:
    """Manifest key for a file: its path relative to the package root (absolute if outside it)."""
    try:
        return path.relative_to(_PACKAGE_ROOT).as_posix()
    except ValueError:
        return str(path)


async def _get_redis():
    """Reuse the platform's existing async Redis client."""
    try:
        from aether_os.core.rate_limiter import _get_async_redis
        return await _get_async_redis()
    except Exception as e:
        logger.debug("threat_detector: could not get Redis client: %s", e)
        return None


class ThreatDetector:
    def __init__(self):
        self._baseline_loaded = False
        self._build_id: Optional[str] = None
        # Always populated at load, so a Redis outage after startup still leaves a baseline to compare against.
        self._mem_baseline: Dict[str, str] = {}

    # ── Baseline ─────────────────────────────────────────────────────────────

    def _trusted_hashes(self, manifest: Optional[Dict[str, str]]) -> Dict[Path, str]:
        """Hashes to trust: the build-time manifest where it lists the file, else the file as it is now."""
        trusted: Dict[Path, str] = {}
        for path in _CRITICAL_FILES:
            if not path.exists():
                continue
            h = (manifest or {}).get(_rel(path)) or _sha256_file(path)
            if h:
                trusted[path] = h
        return trusted

    async def load_or_create_baseline(self) -> None:
        """
        Establish the trusted baseline for the running build.

        With a build identity (AETHER_BUILD_ID or the image's build manifest) the baseline is stored per build, so a new
        deploy starts from its own baseline instead of alerting against the previous build's. Within one build the
        first-stored baseline is never overwritten here (HSETNX): a file changed while that build runs, even across a
        container restart, still differs from it. Without a build identity the legacy first-boot baseline is kept.
        """
        build_id, manifest = resolve_build_identity(_MANIFEST_PATH)
        self._build_id = build_id
        trusted = self._trusted_hashes(manifest)
        self._mem_baseline = {str(p): h for p, h in trusted.items()}

        r = await _get_redis()
        if r is None:
            logger.warning("Guardian: Redis unavailable — file integrity baseline stored in memory only (build %s)",
                           build_id or "unknown")
            self._baseline_loaded = True
            return

        if build_id is None:
            for path, h in trusted.items():
                key = _legacy_key(path)
                if not await r.get(key):
                    # First boot — establish baseline
                    await r.set(key, h)
                    logger.info("Guardian: baseline set for %s", path.name)
            self._baseline_loaded = True
            return

        key = _BUILD_BASELINE_PREFIX + build_id
        for path, h in trusted.items():
            await r.hsetnx(key, _rel(path), h)
        previous = await r.get(_CURRENT_BUILD_KEY)
        if previous != build_id:
            await r.set(_CURRENT_BUILD_KEY, build_id)
            if previous:
                await r.expire(_BUILD_BASELINE_PREFIX + previous, _OLD_BUILD_TTL_SECONDS)
            # Warning level so every baseline change is in the logs; a restart of the same build never causes one.
            logger.warning("Guardian: new build %s (previous %s) — file integrity baseline re-established",
                           build_id, previous or "none")
        self._baseline_loaded = True

    async def _get_baseline(self, path: Path) -> Optional[str]:
        r = await _get_redis()
        if r:
            if self._build_id:
                val = await r.hget(_BUILD_BASELINE_PREFIX + self._build_id, _rel(path))
            else:
                val = await r.get(_legacy_key(path))
            if val:
                return val
        return self._mem_baseline.get(str(path))

    async def update_baseline(self, path: Path) -> None:
        """Accept a file's current content as trusted for the running build (admin re-baseline, after a restore)."""
        h = _sha256_file(path)
        if not h:
            return
        self._mem_baseline[str(path)] = h
        r = await _get_redis()
        if r:
            if self._build_id:
                await r.hset(_BUILD_BASELINE_PREFIX + self._build_id, _rel(path), h)
            else:
                await r.set(_legacy_key(path), h)

    async def update_all_baselines(self) -> None:
        """Re-hash all critical files and write to baseline (call after git pull / deploy)."""
        for path in _CRITICAL_FILES:
            if path.exists():
                await self.update_baseline(path)
                logger.info("Guardian: baseline refreshed for %s", path.name)

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
            
            # Check cooldown
            r = await _get_redis()
            if r and await r.get(f"guardian:cooldown:{path.name}"):
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
            except Exception as e:
                logger.warning("threat_detector: Redis ping failed: %s", e)
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
            logger.warning("threat_detector: DB health check failed: %s", exc)
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
