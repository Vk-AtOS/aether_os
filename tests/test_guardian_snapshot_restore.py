"""KAN-170: recovery restores the last good snapshot, not the forensic copy it just took (SQLite)."""
import asyncio
import os
import sqlite3

import pytest

import aether_os.core.db as db_mod
from aether_os.core.guardian import models as _gm  # noqa: F401  (registers tables)
from aether_os.core.guardian import snapshot_manager as sm


@pytest.fixture
def env(tmp_path, monkeypatch):
    live = tmp_path / "live.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{live}")
    monkeypatch.delenv("GUARDIAN_SNAPSHOT_DIR", raising=False)
    monkeypatch.setattr(sm, "_SNAPSHOT_DIR", tmp_path / "snaps")
    monkeypatch.setattr(sm, "_sqlite_db_path", lambda: live)
    monkeypatch.setattr(db_mod, "_engine", None)
    monkeypatch.setattr(db_mod, "_session_factory", None)
    c = sqlite3.connect(live)
    c.execute("CREATE TABLE t (v TEXT)")
    c.execute("INSERT INTO t VALUES ('good')")
    c.commit()
    c.close()
    return live


def _val(live):
    c = sqlite3.connect(live)
    try:
        return c.execute("SELECT v FROM t").fetchone()[0]
    finally:
        c.close()


def test_recover_target_is_not_the_forensic_snapshot(env):
    async def go():
        from aether_os.core.db import get_engine, Base
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        mgr = sm.SnapshotManager()
        good = await mgr.take_snapshot(trigger="scheduled")
        assert good is not None
        c = sqlite3.connect(env)
        c.execute("UPDATE t SET v='corrupt'")
        c.commit()
        c.close()
        await mgr.take_snapshot(trigger="pre_recovery")
        latest = await mgr.get_latest()
        assert latest.id == good.id
        assert await mgr.restore(latest.id)
        # a restored snapshot stays eligible
        assert (await mgr.get_latest()).id == good.id
        await db_mod.get_engine().dispose()
    asyncio.run(go())
    assert _val(env) == "good"
