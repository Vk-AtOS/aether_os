"""
AutoRecovery — restores from snapshots, runs post-restore verification,
and re-establishes normal service operation.

Recovery flow:
  1. Take a pre-recovery snapshot of current (possibly corrupted) state
  2. Restore from the last known-good snapshot
  3. Run Alembic upgrade heads to ensure schema is current
  4. Run DB health probe to confirm restoration worked
  5. Log recovery event to guardian_events
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AutoRecovery:

    async def recover(self, trigger_event_id: Optional[str] = None) -> bool:
        """
        Full recovery sequence. Returns True if recovery succeeded.
        trigger_event_id links this recovery to the GuardianEvent that caused it.
        """
        from aether_os.core.guardian.snapshot_manager import get_snapshot_manager
        from aether_os.core.guardian.models import GuardianEvent
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select

        # Check for running runs
        max_retries = 5
        for _ in range(max_retries):
            sf = get_session_factory()
            async with sf() as session:
                running_runs = (await session.execute(
                    select(Run).where(Run.status == 'running')
                )).scalars().all()
            
            if not running_runs:
                break
            
            logger.warning("Guardian AutoRecovery: deferring restore due to active pipeline runs")
            await asyncio.sleep(30)
        else:
            logger.error("Guardian AutoRecovery: failed to restore due to persistent running pipeline runs")
            return False

        mgr = get_snapshot_manager()
        # ... rest of the original recover() logic ...
        logger.warning("Guardian AutoRecovery: starting recovery sequence")
        # Step 1: snapshot current state
        await mgr.take_snapshot(trigger="pre_recovery", note="Pre-recovery forensic snapshot")
        # Step 2: find latest clean snapshot
        latest = await mgr.get_latest()
        if latest is None:
            logger.error("Guardian AutoRecovery: no clean snapshot available — cannot recover")
            await self._log_event(
                event_type="recovery",
                severity="critical",
                detail={"outcome": "failed", "reason": "no_snapshot_available"},
            )
            return False

        logger.info("Guardian AutoRecovery: restoring from snapshot %s (%s)", latest.id, latest.created_at)

        # Step 3: restore
        success = await mgr.restore(latest.id)
        if not success:
            await self._log_event(
                event_type="recovery",
                severity="critical",
                detail={"outcome": "failed", "reason": "restore_failed", "snapshot_id": latest.id},
            )
            return False

        # Step 4: run Alembic upgrade to ensure schema is current
        alembic_ok = await self._run_alembic_upgrade()

        # Step 5: health verification
        health_ok = await self._verify_health()

        # Update baseline and set cooldown after successful restore
        if health_ok and trigger_event_id:
            try:
                from aether_os.core.guardian.models import GuardianEvent
                from aether_os.core.db import get_session_factory
                from aether_os.core.guardian.threat_detector import get_threat_detector, _CRITICAL_FILES
                from sqlalchemy import select
                
                sf = get_session_factory()
                async with sf() as sess:
                    event = (await sess.execute(select(GuardianEvent).where(GuardianEvent.id == trigger_event_id))).scalars().first()
                    
                    if event and event.detail and "file" in event.detail:
                        file_name = event.detail["file"]
                        
                        # Find Path object
                        target = next((f for f in _CRITICAL_FILES if f.name == file_name or str(f).endswith(file_name)), None)
                        if target:
                            td = get_threat_detector()
                            await td.update_baseline(target)
                            
                            # Set cooldown
                            from aether_os.core.rate_limiter import _get_async_redis
                            r = await _get_async_redis()
                            if r:
                                await r.set(f"guardian:cooldown:{target.name}", 1, ex=300)
                                logger.info("Guardian: cooldown set for %s", target.name)
            except Exception as e:
                logger.error("Guardian: failed to update baseline/cooldown after restore: %s", e)

        outcome = "success" if (health_ok and alembic_ok) else "partial"
        severity = "low" if outcome == "success" else "medium"

        await self._log_event(
            event_type="recovery",
            severity=severity,
            detail={
                "outcome": outcome,
                "snapshot_id": latest.id,
                "snapshot_created_at": latest.created_at.isoformat(),
                "alembic_ok": alembic_ok,
                "db_health_ok": health_ok,
                "trigger_event_id": trigger_event_id,
            },
        )

        logger.info("Guardian AutoRecovery: %s (alembic=%s, db=%s)", outcome, alembic_ok, health_ok)
        # Recovered means the data is back AND the schema is current: a failed or skipped migration is not success.
        return health_ok and alembic_ok

    @staticmethod
    def _alembic_ini() -> Optional[pathlib.Path]:
        root = pathlib.Path(__file__).resolve().parent.parent.parent   # the aether_os package directory
        return next((p for p in (root / "alembic.ini", root.parent / "alembic.ini") if p.exists()), None)

    async def _run_alembic_upgrade(self) -> bool:
        """alembic upgrade heads. False when it cannot be shown to have succeeded, including when alembic.ini is
        missing: recovery restored an older schema, so "no migration ran" must not be reported as "schema current"."""
        alembic_ini = self._alembic_ini()
        if alembic_ini is None:
            logger.error("Guardian: alembic.ini not found - the restored schema was NOT brought up to date")
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "heads",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                logger.warning("Guardian alembic upgrade failed: %s", stderr.decode(errors="replace")[:300])
                return False
            logger.info("Guardian: alembic upgrade heads completed")
            return True
        except asyncio.TimeoutError:
            logger.error("Guardian: alembic upgrade timed out")
            return False
        except Exception as exc:
            logger.warning("Guardian: alembic upgrade error: %s", exc)
            return False

    async def _verify_health(self) -> bool:
        """Confirm DB is responsive after restore."""
        try:
            from aether_os.core.db import get_session_factory
            from sqlalchemy import text
            sf = get_session_factory()
            async with sf() as sess:
                result = await sess.execute(text("SELECT COUNT(*) FROM organisations"))
                count = result.scalar()
            logger.info("Guardian post-restore DB check OK (organisations: %d)", count)
            return True
        except Exception as exc:
            logger.error("Guardian post-restore DB health check FAILED: %s", exc)
            return False

    async def _log_event(
        self,
        event_type: str,
        severity: str,
        detail: Dict[str, Any],
        org_id: Optional[str] = None,
    ) -> None:
        try:
            from aether_os.core.guardian.models import GuardianEvent
            from aether_os.core.db import get_session_factory
            sf = get_session_factory()
            async with sf() as sess:
                sess.add(GuardianEvent(
                    event_type=event_type,
                    severity=severity,
                    detail=detail,
                    org_id=org_id,
                ))
                await sess.commit()
        except Exception as exc:
            logger.warning("Guardian: could not log recovery event: %s", exc)


_instance: Optional[AutoRecovery] = None


def get_auto_recovery() -> AutoRecovery:
    global _instance
    if _instance is None:
        _instance = AutoRecovery()
    return _instance
