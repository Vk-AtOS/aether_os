"""
GuardianWatchdog — the main background loop.

Tick schedule:
  Every 30s  : service health check + brute force scan
  Every 5min : file integrity check
  Every 6h   : scheduled snapshot

On HIGH threat    : log event, take pre-threat snapshot
On CRITICAL threat: log event, take pre-threat snapshot, attempt auto-recovery
                    if the threat is a service crash or file tamper

Deduplication: the same (event_type, source_ip, endpoint) combination is not
re-inserted within a 10-minute cooldown window (tracked in Redis/memory).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set, Tuple

from aether_os.core.guardian.threat_detector import _get_redis

logger = logging.getLogger(__name__)

_TICK_INTERVAL   = 30       # seconds between health/brute-force ticks
_INTEGRITY_EVERY = 300      # seconds between file-integrity checks (5 min)
_SNAPSHOT_EVERY  = 21600    # seconds between scheduled snapshots (6 h)
_DB_FAILS_BEFORE_CRASH = 5  # consecutive failed DB probes (~2.5 min) before it counts as a crash
_DEDUP_WINDOW    = 600      # seconds before the same event can refire (10 min)


class GuardianWatchdog:
    def __init__(self):
        self._running = False
        self._last_integrity_check: float = 0.0
        self._last_snapshot: float = 0.0
        self._dedup: Dict[str, float] = {}   # key → last_seen_ts
        self._active_threats: Set[str] = set()
        self._db_failures = 0

    async def start(self) -> None:
        """Main loop — runs forever as a background asyncio task."""
        logger.info("Guardian watchdog starting")
        self._running = True

        # Initialize the threat detector baseline
        try:
            from aether_os.core.guardian.threat_detector import get_threat_detector
            await get_threat_detector().load_or_create_baseline()
        except Exception as exc:
            logger.warning("Guardian: baseline load failed: %s", exc)

        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Guardian watchdog tick error: %s", exc, exc_info=True)
            await asyncio.sleep(_TICK_INTERVAL)

        logger.info("Guardian watchdog stopped")

    def stop(self) -> None:
        self._running = False

    # ── Main tick ─────────────────────────────────────────────────────────────

    async def _tick(self) -> None:
        now = time.monotonic()
        all_events: list[Dict[str, Any]] = []

        # Always: service health + brute force
        try:
            from aether_os.core.guardian.threat_detector import get_threat_detector
            td = get_threat_detector()
            results = await asyncio.gather(
                td.check_service_health(),
                td.check_brute_force(),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, list):
                    all_events.extend(r)
        except Exception as exc:
            logger.warning("Guardian tick detect error: %s", exc)

        all_events = self._gate_db_failures(all_events)

        # Every 5 min: file integrity
        if now - self._last_integrity_check >= _INTEGRITY_EVERY:
            self._last_integrity_check = now
            try:
                from aether_os.core.guardian.threat_detector import get_threat_detector
                integrity_events = await get_threat_detector().check_file_integrity()
                all_events.extend(integrity_events)
            except Exception as exc:
                logger.warning("Guardian integrity check error: %s", exc)

        # Every 6h: scheduled snapshot
        if now - self._last_snapshot >= _SNAPSHOT_EVERY:
            self._last_snapshot = now
            await self._take_snapshot("scheduled")

        # Process events
        if all_events:
            await self._process_events(all_events)

    def _gate_db_failures(self, events: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """One failed DB probe is a blip (pool churn, deploy), not a crash.

        Drops database events until the probe has failed _DB_FAILS_BEFORE_CRASH ticks in a row.
        """
        is_db = lambda e: (e.get("detail") or {}).get("service") == "database"  # noqa: E731
        if not any(is_db(e) for e in events):
            self._db_failures = 0
            return events
        self._db_failures += 1
        if self._db_failures >= _DB_FAILS_BEFORE_CRASH:
            return events
        logger.warning("Guardian: DB probe failed (%d/%d) — not yet a crash", self._db_failures, _DB_FAILS_BEFORE_CRASH)
        return [e for e in events if not is_db(e)]

    # ── Event processing ──────────────────────────────────────────────────────

    async def _process_events(self, events: list[Dict[str, Any]]) -> None:
        new_events = []
        for e in events:
            if not await self._is_duplicate(e):
                new_events.append(e)
        if not new_events:
            return

        # Persist to DB
        saved = await self._persist_events(new_events)

        # Take pre-threat snapshot on HIGH/CRITICAL
        severities = {e.get("severity", "low") for e in new_events}
        # Disk pressure alerts but must not trigger a snapshot (it writes more to a full disk).
        snap_events = [e for e in new_events if (e.get("detail") or {}).get("service") != "disk"]
        if any(e.get("severity") in ("critical", "high") for e in snap_events):
            await self._take_snapshot("pre_threat")

        # Auto-recover ONLY on CRITICAL service crashes — NOT on file_tamper.
        # file_tamper events trigger alerts and snapshots but never pg_restore,
        # because restoring the DB from snapshot deletes legitimate user data
        # created after the snapshot was taken (false-positive deploy detection).
        # Run post-deploy.sh after every deploy to refresh the file baseline.
        critical = [
            e for e in new_events
            if e.get("severity") == "critical"
            and e.get("event_type") == "service_crash"
            # Restoring a snapshot cannot fix a full disk and loses data: only the
            # database being down (after consecutive failed probes) justifies it.
            and (e.get("detail") or {}).get("service") == "database"
        ]
        if critical:
            first_id = saved[0] if saved else None
            logger.warning(
                "Guardian: CRITICAL service crash — initiating auto-recovery (%d event(s))", len(critical)
            )
            asyncio.create_task(self._run_recovery(first_id))

    def _dedup_key(self, event: Dict[str, Any]) -> str:
        return f"{event.get('event_type')}:{event.get('source_ip', '')}:{event.get('endpoint', '')}:{event.get('detail', {}).get('service', '')}"

    async def _is_duplicate(self, event: Dict[str, Any]) -> bool:
        key = "guardian:dedup:" + self._dedup_key(event)
        r = await _get_redis()
        if r:
            # SET NX EX 600 — returns True if key was newly set (not duplicate), None if existed
            result = await r.set(key, "1", nx=True, ex=_DEDUP_WINDOW)
            return result is None  # None means key existed = duplicate
        # Redis unavailable — fall back to in-memory
        last = self._dedup.get(key, 0.0)
        is_dup = (time.monotonic() - last) < _DEDUP_WINDOW
        if not is_dup:
            self._dedup[key] = time.monotonic()
        return is_dup

    async def _persist_events(self, events: list[Dict[str, Any]]) -> list[str]:
        """Write events to guardian_events table. Returns list of inserted IDs."""
        ids: list[str] = []
        try:
            from aether_os.core.guardian.models import GuardianEvent
            from aether_os.core.db import get_session_factory
            sf = get_session_factory()
            async with sf() as sess:
                for e in events:
                    row = GuardianEvent(
                        event_type=e.get("event_type", "anomaly"),
                        severity=e.get("severity", "low"),
                        source_ip=e.get("source_ip"),
                        endpoint=e.get("endpoint"),
                        detail=e.get("detail"),
                        org_id=None,
                    )
                    sess.add(row)
                    ids.append(row.id)
                    sev = e.get("severity", "low")
                    log_fn = logger.critical if sev == "critical" else logger.warning if sev == "high" else logger.info
                    log_fn(
                        "Guardian event: [%s] %s — %s",
                        sev.upper(), e.get("event_type"), e.get("detail", {})
                    )
                await sess.commit()
        except Exception as exc:
            logger.error("Guardian: failed to persist events: %s", exc)
        return ids

    async def _take_snapshot(self, trigger: str) -> None:
        try:
            from aether_os.core.guardian.snapshot_manager import get_snapshot_manager
            await get_snapshot_manager().take_snapshot(trigger=trigger)
            if trigger == "scheduled":
                self._last_snapshot = time.monotonic()
        except Exception as exc:
            logger.error("Guardian: snapshot failed (trigger=%s): %s", trigger, exc)

    async def _run_recovery(self, trigger_event_id: Optional[str]) -> None:
        try:
            from aether_os.core.guardian.auto_recovery import get_auto_recovery
            await get_auto_recovery().recover(trigger_event_id=trigger_event_id)
        except Exception as exc:
            logger.error("Guardian: auto-recovery exception: %s", exc, exc_info=True)


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional[GuardianWatchdog] = None


def get_watchdog() -> GuardianWatchdog:
    global _instance
    if _instance is None:
        _instance = GuardianWatchdog()
    return _instance
