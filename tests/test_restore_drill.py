"""KAN-51: the restore drill script. The end-to-end test needs a Postgres server and the pg_* tools (AETHER_TEST_PG_ADMIN_URL)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("restore_drill", ROOT / "scripts/restore_drill.py")
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)


def test_the_record_never_contains_a_password():
    assert "s3cret" not in rd.redact("postgresql://aether:s3cret@db.example.com:5432/postgres")
    assert rd.redact("postgresql://aether:s3cret@db.example.com:5432/postgres") == "postgresql://aether@db.example.com:5432/postgres"
    assert rd.with_db("postgresql://u:p@h:5432/postgres", "scratch") == "postgresql://u:p@h:5432/scratch"


def test_missing_dump_is_refused_with_exit_2(tmp_path, capsys):
    assert rd.main(["--dump", str(tmp_path / "nope.dump"), "--admin-url", "postgresql://x@h/postgres"]) == 2


PG = os.environ.get("AETHER_TEST_PG_ADMIN_URL", "")


@pytest.mark.skipif(not PG or not shutil.which("pg_dump") or not shutil.which("pg_restore"),
                    reason="needs AETHER_TEST_PG_ADMIN_URL and the PostgreSQL client tools")
def test_a_real_backup_restores_verifies_and_is_recorded(tmp_path):
    src = f"aether_drill_src_{uuid.uuid4().hex[:8]}"
    admin = create_engine(PG, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{src}"'))
    src_url = PG.rsplit("/", 1)[0] + "/" + src
    try:
        env = {**os.environ, "DATABASE_URL": src_url, "PYTHONPATH": str(ROOT.parent), "AETHER_FIELD_KEY": "x"}
        assert subprocess.run([sys.executable, "scripts/db_migrate.py"], env=env, cwd=ROOT, capture_output=True).returncode == 0
        dump = tmp_path / "b.dump"
        subprocess.run(["pg_dump", "--format=custom", "-f", str(dump), src_url], check=True)
        rec = rd.drill(dump, PG)
        assert rec["passed"], rec
        assert [s["step"] for s in rec["steps"]] == ["create scratch database", "restore dump", "verify restored data",
                                                     "drop scratch database"]
        assert rec["checks"]["schema_at_head"] and rec["checks"]["chains_verify"]
        json.dumps(rec)                                    # serialisable: it is written as the drill record
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{src}" WITH (FORCE)'))
