"""
SnapshotManager — takes and restores DB snapshots.

PostgreSQL: pg_dump / psql via subprocess
SQLite:     Python sqlite3 backup API

Snapshots are stored in GUARDIAN_SNAPSHOT_DIR (default: ./snapshots/guardian/).
Up to GUARDIAN_MAX_SNAPSHOTS are kept (default: 10); older ones are pruned.
Each snapshot file is SHA-256 hashed and recorded in guardian_snapshots table.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_SNAPSHOT_DIR = Path(os.environ.get("GUARDIAN_SNAPSHOT_DIR", "./snapshots/guardian")).resolve()
_MAX_SNAPSHOTS = int(os.environ.get("GUARDIAN_MAX_SNAPSHOTS", "10"))


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_db_backend() -> str:
    db_url = os.environ.get("DATABASE_URL", "")
    if "postgresql" in db_url or "postgres" in db_url:
        return "postgresql"
    return "sqlite"


def _sqlite_db_path() -> Optional[Path]:
    """Find the SQLite DB file (first .db in package root)."""
    from pathlib import Path as _P
    pkg_root = _P(__file__).resolve().parent.parent.parent
    candidates = ["aether_os/aether_os.db", "aether_os.db"]
    for c in candidates:
        p = pkg_root / c
        if p.exists():
            return p
    # Fallback: search
    found = list(pkg_root.glob("*.db"))
    if found:
        return found[0]
    return None


async def _pg_dump(dest: Path) -> bool:
    """Run pg_dump and write to dest. Returns True on success."""
    db_url = os.environ.get("DATABASE_URL", "")
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump", "--no-password", "--format=custom", f"--file={dest}", db_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            logger.error("Guardian pg_dump failed: %s", stderr.decode(errors="replace"))
            return False
        return True
    except asyncio.TimeoutError:
        logger.error("Guardian pg_dump timed out after 300s")
        return False
    except FileNotFoundError:
        # pg_dump not installed — try plain SQL format
        try:
            proc = await asyncio.create_subprocess_exec(
                "pg_dump", "--no-password", f"--file={dest}", db_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            return proc.returncode == 0
        except Exception as exc2:
            logger.warning("Guardian pg_dump unavailable: %s", exc2)
            return False


async def _sqlite_backup(dest: Path) -> bool:
    """Use Python sqlite3 backup API. Non-blocking via executor."""
    import sqlite3
    loop = asyncio.get_running_loop()
    src_path = _sqlite_db_path()
    if src_path is None:
        logger.warning("Guardian: SQLite DB not found for snapshot")
        return False

    def _do_backup():
        src = sqlite3.connect(str(src_path))
        dst = sqlite3.connect(str(dest))
        src.backup(dst)
        src.close()
        dst.close()

    try:
        await loop.run_in_executor(None, _do_backup)
        return True
    except Exception as exc:
        logger.error("Guardian SQLite backup failed: %s", exc)
        return False


class SnapshotManager:
    def __init__(self):
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    async def take_snapshot(
        self,
        trigger: str = "scheduled",
        note: Optional[str] = None,
    ) -> Optional[object]:
        """
        Take a DB snapshot. Returns a GuardianSnapshot ORM object on success.
        Inserts it into the DB automatically.
        """
        from aether_os.core.guardian.models import GuardianSnapshot
        from aether_os.core.db import get_session_factory

        backend = _detect_db_backend()
        snapshot_id = str(uuid.uuid4())
        ts = int(time.time())
        ext = ".dump" if backend == "postgresql" else ".sqlite3"
        filename = f"snapshot_{ts}_{snapshot_id[:8]}{ext}"
        dest = _SNAPSHOT_DIR / filename

        logger.info("Guardian: taking %s snapshot → %s (trigger=%s)", backend, filename, trigger)

        success = False
        if backend == "postgresql":
            success = await _pg_dump(dest)
        else:
            success = await _sqlite_backup(dest)

        if not success or not dest.exists():
            logger.error("Guardian: snapshot FAILED for trigger=%s", trigger)
            return None

        size = dest.stat().st_size
        digest = _sha256_path(dest)

        snap = GuardianSnapshot(
            id=snapshot_id,
            created_at=datetime.now(timezone.utc),
            snapshot_path=str(dest),
            size_bytes=size,
            integrity_hash=digest,
            trigger=trigger,
            status="ok",
            note=note,
            db_backend=backend,
        )

        sf = get_session_factory()
        async with sf() as sess:
            sess.add(snap)
            await sess.commit()

        logger.info(
            "Guardian: snapshot OK — %s (%.1f KB, sha256=%s...)",
            filename, size / 1024, digest[:12],
        )
        await self._prune_old()
        return snap

    async def list_snapshots(self, limit: int = 20) -> List[dict]:
        from aether_os.core.guardian.models import GuardianSnapshot
        from aether_os.core.db import get_session_factory
        from sqlalchemy import select, desc

        sf = get_session_factory()
        async with sf() as sess:
            rows = (await sess.execute(
                select(GuardianSnapshot).order_by(desc(GuardianSnapshot.created_at)).limit(limit)
            )).scalars().all()

        return [
            {
                "id": s.id,
                "created_at": s.created_at.isoformat(),
                "size_bytes": s.size_bytes,
                "integrity_hash": s.integrity_hash,
                "trigger": s.trigger,
                "status": s.status,
                "note": s.note,
                "db_backend": s.db_backend,
                "file_exists": Path(s.snapshot_path).exists(),
            }
            for s in rows
        ]

    async def get_latest(self) -> Optional[object]:
        from aether_os.core.guardian.models import GuardianSnapshot
        from aether_os.core.db import get_session_factory
        from sqlalchemy import select, desc

        sf = get_session_factory()
        async with sf() as sess:
            row = (await sess.execute(
                select(GuardianSnapshot)
                # A restored snapshot is still known-good. The forensic copy taken just
                # before a recovery is the (possibly corrupt) state being replaced and
                # must never be chosen as the restore target.
                .where(GuardianSnapshot.status.in_(("ok", "restored")))
                .where(GuardianSnapshot.trigger != "pre_recovery")
                .order_by(desc(GuardianSnapshot.created_at))
                .limit(1)
            )).scalars().first()
        return row

    async def restore(self, snapshot_id: str) -> bool:
        """
        Restore the platform DB from a snapshot.
        Marks the snapshot row as 'restoring' then 'restored' or 'failed'.
        """
        from aether_os.core.guardian.models import GuardianSnapshot
        from aether_os.core.db import get_session_factory
        from sqlalchemy import select

        sf = get_session_factory()
        async with sf() as sess:
            snap = (await sess.execute(
                select(GuardianSnapshot).where(GuardianSnapshot.id == snapshot_id)
            )).scalars().first()
            if not snap:
                logger.error("Guardian restore: snapshot %s not found", snapshot_id)
                return False
            snap.status = "restoring"
            await sess.commit()

        dest = Path(snap.snapshot_path)
        if not dest.exists():
            logger.error("Guardian restore: snapshot file missing at %s", dest)
            return False

        # Verify integrity before restoring
        current_hash = _sha256_path(dest)
        if current_hash != snap.integrity_hash:
            logger.error(
                "Guardian restore ABORTED: snapshot %s integrity check FAILED "
                "(expected %s, got %s)", snapshot_id, snap.integrity_hash[:12], current_hash[:12]
            )
            return False

        # The dump predates its own catalogue row (and every later one), so a restore
        # wipes the snapshot list. Keep the rows and put them back afterwards.
        async with sf() as sess:
            catalogue = [
                {c.name: getattr(r, c.name) for c in GuardianSnapshot.__table__.columns}
                for r in (await sess.execute(select(GuardianSnapshot))).scalars().all()
            ]

        success = False
        if snap.db_backend == "postgresql":
            success = await self._pg_restore(dest)
        else:
            success = await self._sqlite_restore(dest)

        status = "restored" if success else "failed"
        async with sf() as sess:
            if success:
                for row in catalogue:
                    await sess.merge(GuardianSnapshot(**row))
                await sess.flush()
            s = (await sess.execute(
                select(GuardianSnapshot).where(GuardianSnapshot.id == snapshot_id)
            )).scalars().first()
            if s:
                s.status = status
                await sess.commit()

        if success:
            logger.info("Guardian: restore COMPLETE from snapshot %s", snapshot_id)
        else:
            logger.error("Guardian: restore FAILED from snapshot %s", snapshot_id)

        return success

    async def _pg_restore(self, src: Path) -> bool:
        db_url = os.environ.get("DATABASE_URL", "")
        try:
            proc = await asyncio.create_subprocess_exec(
                "pg_restore", "--no-password", "--clean", "--if-exists",
                "--dbname", db_url, str(src),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            if proc.returncode not in (0, 1):  # pg_restore exits 1 with warnings
                logger.error("Guardian pg_restore error: %s", stderr.decode(errors="replace")[:500])
                return False
            return True
        except Exception as exc:
            logger.error("Guardian pg_restore exception: %s", exc)
            return False

    async def _sqlite_restore(self, src: Path) -> bool:
        import sqlite3
        loop = asyncio.get_running_loop()
        db_path = _sqlite_db_path()
        if db_path is None:
            return False

        # Backup current DB before overwrite
        bak = db_path.with_suffix(".bak")
        try:
            shutil.copy2(str(db_path), str(bak))
        except Exception as exc:
            logger.warning("Guardian: could not create pre-restore backup at %s: %s", bak, exc)

        def _do_restore():
            backup_conn = sqlite3.connect(str(src))
            live_conn = sqlite3.connect(str(db_path))
            backup_conn.backup(live_conn)
            backup_conn.close()
            live_conn.close()

        try:
            await loop.run_in_executor(None, _do_restore)
            return True
        except Exception as exc:
            logger.error("Guardian SQLite restore failed: %s", exc)
            # Roll back to pre-restore backup
            try:
                shutil.copy2(str(bak), str(db_path))
            except Exception as exc:
                logger.error("Guardian: rollback to pre-restore backup failed: %s", exc)
            return False

    async def _prune_old(self) -> None:
        """Delete snapshot files and DB rows beyond max count."""
        from aether_os.core.guardian.models import GuardianSnapshot
        from aether_os.core.db import get_session_factory
        from sqlalchemy import select, desc, delete

        sf = get_session_factory()
        async with sf() as sess:
            rows = (await sess.execute(
                select(GuardianSnapshot)
                .where(GuardianSnapshot.status.in_(["ok", "restored"]))
                .order_by(desc(GuardianSnapshot.created_at))
            )).scalars().all()

        to_delete = rows[_MAX_SNAPSHOTS:]
        if not to_delete:
            return

        for snap in to_delete:
            try:
                p = Path(snap.snapshot_path)
                if p.exists():
                    p.unlink()
            except Exception as exc:
                logger.warning("Guardian: could not delete old snapshot file %s: %s", snap.snapshot_path, exc)

        ids = [s.id for s in to_delete]
        async with sf() as sess:
            await sess.execute(
                delete(GuardianSnapshot).where(GuardianSnapshot.id.in_(ids))
            )
            await sess.commit()

        logger.info("Guardian: pruned %d old snapshot(s)", len(to_delete))


_instance: Optional[SnapshotManager] = None


def get_snapshot_manager() -> SnapshotManager:
    global _instance
    if _instance is None:
        _instance = SnapshotManager()
    return _instance
