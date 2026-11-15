"""KAN-170: the Postgres snapshot/restore path.

The URL test always runs. The drill needs a throw-away PostgreSQL database and the client tools:
  GUARDIAN_PG_TEST_URL=postgresql://user:pass@host:5432/scratch_db python3.11 -m pytest tests/test_guardian_postgres_restore.py
(pg_dump, pg_restore and psql on PATH). It is skipped otherwise: UNVERIFIED until run once on a real server.
"""
import asyncio
import os
import shutil
import subprocess

import pytest

from aether_os.core.guardian import snapshot_manager as sm

PG_URL = os.environ.get("GUARDIAN_PG_TEST_URL", "")


@pytest.mark.parametrize("url,expected", [
    ("postgresql+asyncpg://u@h:5432/db", "postgresql://u@h:5432/db"),
    ("postgres+psycopg2://u@h/db", "postgres://u@h/db"),
    ("postgresql://u@h/db?sslmode=require", "postgresql://u@h/db?sslmode=require"),
])
def test_driver_suffix_is_removed_for_the_postgres_tools(url, expected, monkeypatch):
    # pg_dump/pg_restore cannot parse SQLAlchemy's "+asyncpg": every production snapshot failed on it.
    monkeypatch.setenv("DATABASE_URL", url)
    assert sm._libpq_target()[0] == expected


def test_password_travels_in_the_environment_never_in_the_command_line(monkeypatch):
    # Root cause: the whole URL, password included, was argv, readable by every local user through `ps`.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:p%40ss%2Fw:rd@db.internal:5432/aether?sslmode=require")
    url, env = sm._libpq_target()
    assert "p%40ss" not in url and "w:rd" not in url and "p@ss/w:rd" not in url
    assert url == "postgresql://app@db.internal:5432/aether?sslmode=require"
    assert env["PGPASSWORD"] == "p@ss/w:rd"


def test_dump_and_restore_pass_the_password_through_env_not_argv(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:s3cret@h/db")
    calls = []

    async def fake_exec(*argv, **kw):
        calls.append((argv, kw.get("env") or {}))

        class P:
            returncode = 0

            async def communicate(self):
                return b"", b""
        return P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert asyncio.run(sm._pg_dump(tmp_path / "d"))
    assert asyncio.run(sm.SnapshotManager()._pg_restore(tmp_path / "d"))
    assert len(calls) == 2
    for argv, env in calls:
        assert not any("s3cret" in a for a in argv), argv
        assert env["PGPASSWORD"] == "s3cret"


@pytest.mark.skipif(not PG_URL or not all(shutil.which(t) for t in ("pg_dump", "pg_restore", "psql")),
                    reason="needs GUARDIAN_PG_TEST_URL (scratch database) and pg_dump, pg_restore, psql")
def test_corrupted_postgres_state_is_restored_from_the_dump(tmp_path, monkeypatch):
    def psql(sql):
        done = subprocess.run(["psql", "--no-psqlrc", "-tA", "-c", sql, PG_URL], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    psql("DROP TABLE IF EXISTS guardian_probe; CREATE TABLE guardian_probe (v text); INSERT INTO guardian_probe VALUES ('good')")
    # the app's URL carries the asyncpg driver suffix; the tools must still work
    monkeypatch.setenv("DATABASE_URL", PG_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    dump = tmp_path / "snap.dump"
    assert asyncio.run(sm._pg_dump(dump)) and dump.stat().st_size > 0
    psql("UPDATE guardian_probe SET v = 'corrupted'")
    assert asyncio.run(sm.SnapshotManager()._pg_restore(dump))
    assert psql("SELECT v FROM guardian_probe") == "good"
    psql("DROP TABLE guardian_probe")
