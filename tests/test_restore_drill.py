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


def test_with_db_keeps_the_query_string_so_sslmode_survives():
    assert rd.with_db("postgresql://u:p@h:5432/postgres?sslmode=require", "scratch") == "postgresql://u:p@h:5432/scratch?sslmode=require"


def test_the_password_never_reaches_a_command_line():
    seen = []

    def fake(cmd, **kw):
        seen.append((cmd, kw.get("env", {})))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    url = "postgresql://aether:s3cret@db.example.com:5432/postgres?sslmode=require"
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(rd.subprocess, "run", fake):
        rd.run(["psql", url, "-c", "select 1"], url)
    cmd, env = seen[0]
    assert all("s3cret" not in c for c in cmd) and "sslmode=require" in " ".join(cmd)
    assert env["PGPASSWORD"] == "s3cret"


def test_anchor_file_must_be_a_non_empty_regular_file_with_checkpoints(tmp_path):
    assert "not a regular file" in rd.check_anchor_file(str(tmp_path / "missing"))
    assert "not a regular file" in rd.check_anchor_file(str(tmp_path))
    empty = tmp_path / "e.jsonl"
    empty.write_text("")
    assert "no checkpoints" in rd.check_anchor_file(str(empty))
    junk = tmp_path / "j.jsonl"
    junk.write_text("not json\n")
    assert "no checkpoints" in rd.check_anchor_file(str(junk))
    good = tmp_path / "g.jsonl"
    good.write_text('{"chain_id": "a", "chain_seq": 3}\n{"chain_id": "b", "chain_seq": 1}\n')
    assert rd.check_anchor_file(str(good)) == "" and rd.covered_chains(good) == ["a", "b"]


def test_cli_refuses_an_empty_anchor_file_and_an_admin_restore_without_opt_in(tmp_path, capsys):
    dump = tmp_path / "d.dump"
    dump.write_bytes(b"x")
    empty = tmp_path / "e.jsonl"
    empty.write_text("")
    assert rd.main(["--dump", str(dump), "--admin-url", "postgresql://x@h/postgres", "--anchor-file", str(empty)]) == 2
    assert rd.main(["--dump", str(dump), "--admin-url", "postgresql://x@h/postgres"]) == 2
    assert "--role" in capsys.readouterr().err


def test_dumps_with_event_triggers_or_untrusted_languages_are_refused():
    assert rd.unsafe_objects("CREATE EVENT TRIGGER t ON ddl_command_start EXECUTE FUNCTION f();")
    assert rd.unsafe_objects("CREATE FUNCTION f() RETURNS int LANGUAGE c AS 'x', 'y';")
    assert rd.unsafe_objects("CREATE FUNCTION f() RETURNS void LANGUAGE plpython3u AS $$ import os $$;")
    assert rd.unsafe_objects("CREATE FUNCTION f() RETURNS trigger LANGUAGE plpgsql AS $$ begin return new; end $$;") == []
    assert rd.unsafe_objects("CREATE TABLE t (language text, c int);") == []


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
        assert [s["step"] for s in rec["steps"]] == ["preflight (role, dump contents)", "create scratch database", "restore dump", "verify restored data",
                                                     "drop scratch database"]
        assert rec["checks"]["schema_at_head"] and rec["checks"]["chains_verify"]
        json.dumps(rec)                                    # serialisable: it is written as the drill record
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{src}" WITH (FORCE)'))
