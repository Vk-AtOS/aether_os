"""Real-database suite (KAN-180): the schema bootstrap, this round's migrations, the org_id hook and retention on a real
PostgreSQL. Skipped unless AETHER_PG_TEST_URL points at a server you may create databases on, e.g.
postgresql://ci:ci@127.0.0.1:5432/postgres (CI has a postgres service and sets it; locally initdb + pg_ctl on a spare port).
Each test class run gets its own database and drops it afterwards."""
import importlib.util
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
PG = os.environ.get("AETHER_PG_TEST_URL", "")
pytestmark = pytest.mark.skipif(not PG.startswith("postgres"), reason="AETHER_PG_TEST_URL is not set (needs PostgreSQL)")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def db_url():
    """A fresh database with every table created from the models, dropped at the end."""
    name = f"aether_r3_{uuid.uuid4().hex[:8]}"
    base = make_url(PG).set(drivername="postgresql")
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    # create_all straight from the models. scripts/db_migrate.py is not used here: on an empty database it is
    # refused by init_db's ledger-trigger guard (found by this suite, see the report), which is tested in
    # tests/test_db_migrate.py once that is fixed.
    from aether_os.core import models  # noqa: F401  registers every table
    from aether_os.core.db import Base
    boot = create_engine(url)
    Base.metadata.create_all(boot)
    boot.dispose()
    try:
        yield url
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture()
def engine(db_url):
    eng = create_engine(db_url)
    yield eng
    eng.dispose()


def test_bootstrapped_schema_has_the_round_3_columns_tables_and_indexes(engine):
    insp = inspect(engine)
    for table in ("events", "snapshots", "run_specs", "pipeline_events", "llm_traces",
                  "questionnaire_sessions", "phase_completions", "run_metadata"):
        assert "org_id" in {c["name"] for c in insp.get_columns(table)}, table
        assert f"ix_{table}_org_id" in {i["name"] for i in insp.get_indexes(table)}, table
    assert "scopes" in {c["name"] for c in insp.get_columns("api_keys")}
    assert "password_history" in insp.get_table_names()


def test_org_id_hook_fills_org_id_on_a_real_database(engine):
    from aether_os.core import models as m
    with Session(engine) as s:
        org = m.Organisation(id=f"org-{uuid.uuid4().hex[:6]}", name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}")
        s.add(org)
        s.flush()
        run = m.Run(id=str(uuid.uuid4()), org_id=org.id, status="running", started_at=time.time())
        s.add(run)
        s.flush()
        ev, pe = m.Event(run_id=run.id, agent="a"), m.PipelineEvent(run_id=run.id, event_type="t")
        s.add_all([ev, pe])
        s.commit()
        assert (ev.org_id, pe.org_id) == (org.id, org.id)


def test_migration_adds_backfills_and_is_idempotent_on_postgres(engine):
    mig = _load(ROOT / "alembic" / "versions" / "add_org_id_to_run_tables.py", "mig_org")
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_events_org_id"))
        conn.execute(text("ALTER TABLE events DROP COLUMN org_id"))
        org_id = conn.execute(text("SELECT org_id FROM runs WHERE org_id IS NOT NULL LIMIT 1")).scalar()
        run_id = conn.execute(text("SELECT id FROM runs WHERE org_id = :o LIMIT 1"), {"o": org_id}).scalar()
        conn.execute(text("INSERT INTO events (id, run_id, agent) VALUES (:i, :r, 'x')"), {"i": str(uuid.uuid4()), "r": run_id})
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()
        assert conn.execute(text("SELECT COUNT(*) FROM events WHERE org_id = :o"), {"o": org_id}).scalar() >= 1
        assert conn.execute(text("SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'ix_events_org_id'")).scalar() == 1


def test_retention_purge_deletes_in_batches_on_postgres(engine):
    spec = importlib.util.spec_from_file_location("rp", ROOT / "scripts" / "retention_purge.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    old = datetime.now(timezone.utc) - timedelta(days=400)
    with engine.begin() as conn:
        for i in range(3):
            conn.execute(text("INSERT INTO llm_traces (id, phase, parsed_ok, attempt, duration_ms, tokens_in, tokens_out, created_at) VALUES (:i, 'p01', true, 1, 0, 0, 0, :c)"),
                         {"i": f"old{i}-{uuid.uuid4().hex[:6]}", "c": old.replace(tzinfo=None)})
        conn.execute(text("INSERT INTO llm_traces (id, phase, parsed_ok, attempt, duration_ms, tokens_in, tokens_out, created_at) VALUES (:i, 'p01', true, 1, 0, 0, 0, now())"), {"i": f"new-{uuid.uuid4().hex[:6]}"})
    done = rp.purge(engine)
    assert done["llm_traces"] >= 3
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM llm_traces WHERE created_at < now() - interval '300 days'")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM llm_traces WHERE id LIKE 'new-%'")).scalar() == 1
