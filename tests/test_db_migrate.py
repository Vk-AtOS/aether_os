"""KAN-47: a first `docker compose up` must reach a database at the Alembic head.

Root cause: `alembic upgrade head` was the migrate step, but the chain cannot be replayed on an empty database (the baseline
already has columns later revisions add; one branch alters `organisations` before another creates it), so on a fresh
Postgres the migrate service failed and the API never started. scripts/db_migrate.py bootstraps an empty database and
upgrades an existing one. The Postgres test runs when AETHER_TEST_PG_ADMIN_URL points at a server you may create databases
on, e.g. postgresql://postgres@127.0.0.1:5432/postgres (initdb + pg_ctl on a spare port is enough).
"""
import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("db_migrate", ROOT / "scripts/db_migrate.py")
dbm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dbm)


def test_empty_database_is_detected_and_a_migrated_one_is_not(tmp_path):
    url = f"sqlite:///{tmp_path}/x.db"
    assert dbm.is_empty(url)
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    assert not dbm.is_empty(url)


def test_every_shipped_migrate_step_uses_the_bootstrap_script_not_bare_alembic():
    for name in ("docker-compose.yml", "docker-compose.staging.yml"):
        svc = next(v for k, v in yaml.safe_load((ROOT / name).read_text())["services"].items() if k.startswith("migrate"))
        assert svc["command"] == ["python", "scripts/db_migrate.py"], name
    assert "scripts/db_migrate.py" in (ROOT / "deploy/deploy.sh").read_text()
    assert "scripts/db_migrate.py" in (ROOT / "deploy/kubernetes/migrate-job.yaml").read_text()
    assert "scripts/db_migrate.py" in (ROOT / "helm/aetheros/templates/migrate-job.yaml").read_text()
    staging = yaml.safe_load((ROOT / "docker-compose.staging.yml").read_text())["services"]
    assert staging["api_staging"]["depends_on"]["migrate_staging"]["condition"] == "service_completed_successfully"


PG = os.environ.get("AETHER_TEST_PG_ADMIN_URL", "")


@pytest.mark.skipif(not PG, reason="AETHER_TEST_PG_ADMIN_URL is not set (needs a Postgres server)")
def test_fresh_postgres_reaches_head_and_the_api_accepts_it():
    name = f"aether_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(PG, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = PG.rsplit("/", 1)[0] + "/" + name
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT.parent), "AETHER_FIELD_KEY": "x"}
    try:
        def run(code):
            return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=ROOT, timeout=240)

        first = subprocess.run([sys.executable, "scripts/db_migrate.py"], env=env, capture_output=True, text=True, cwd=ROOT, timeout=240)
        assert first.returncode == 0, first.stderr[-800:]
        assert first.stdout.strip().endswith("created")
        second = subprocess.run([sys.executable, "scripts/db_migrate.py"], env=env, capture_output=True, text=True, cwd=ROOT, timeout=240)
        assert second.returncode == 0 and second.stdout.strip().endswith("upgraded"), second.stderr[-800:]
        check = run("import asyncio;from aether_os.core.db import init_db;asyncio.run(init_db());print('ok')")
        assert check.returncode == 0 and "ok" in check.stdout, check.stderr[-800:]   # _require_migrated passes
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
