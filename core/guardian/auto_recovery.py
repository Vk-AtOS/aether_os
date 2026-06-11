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
import os
import time
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
        from datetime import datetime

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
        return health_ok

    async def _run_alembic_upgrade(self) -> bool:
        """Run alembic upgrade heads in an executor (blocking operation)."""
        import pathlib

        alembic_ini = pathlib.Path(__file__).resolve().parent.parent.parent / "aether_os" / "alembic.ini"
        if not alembic_ini.exists():
            # Try one level up (common layout)
            alembic_ini = pathlib.Path(__file__).resolve().parent.parent.parent / "alembic.ini"

        if not alembic_ini.exists():
            logger.warning("Guardian: alembic.ini not found — skipping migration step")
            return True  # non-fatal

        try:
            proc = await asyncio.create_subprocess_exec(
                "alembic", "-c", str(alembic_ini), "upgrade", "heads",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                logger.warning("Guardian alembic upgrade warnings: %s", stderr.decode(errors="replace")[:300])
                return proc.returncode == 0
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
    ) -> None:
        try:
            from aether_os.core.guardian.models import GuardianEvent
            from aether_os.core.db import get_session_factory
            from datetime import datetime
            sf = get_session_factory()
            async with sf() as sess:
                sess.add(GuardianEvent(
                    event_type=event_type,
                    severity=severity,
                    detail=detail,
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
