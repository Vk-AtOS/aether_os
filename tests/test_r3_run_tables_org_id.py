"""KAN-131: org_id on the run-owned tables: filled on every ORM insert, migration back-fills, retention purges."""
import importlib.util
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from aether_os.core import models as m

ROOT = Path(__file__).resolve().parents[1]
RUN_TABLES = ("events", "snapshots", "run_specs", "pipeline_events", "llm_traces",
              "questionnaire_sessions", "phase_completions", "run_metadata")


def test_every_run_owned_table_has_an_indexed_org_id_column():
    for cls in m._RUN_OWNED:
        col = cls.__table__.c.org_id
        assert col.index and col.nullable
    assert {c.__tablename__ for c in m._RUN_OWNED} == set(RUN_TABLES)


def test_orm_inserts_take_org_id_from_the_run():
    engine = create_engine("sqlite://")
    m.Base.metadata.create_all(engine, tables=[m.Run.__table__, m.Event.__table__, m.PipelineEvent.__table__,
                                               m.RunMetadata.__table__, m.PhaseCompletion.__table__, m.RunSpec.__table__])
    with Session(engine) as s:
        s.add(m.Run(id="r1", org_id="org-a", status="running", started_at=time.time()))
        s.flush()
        s.add_all([m.Event(run_id="r1", agent="x"), m.PipelineEvent(run_id="r1", event_type="t"),
                   m.RunMetadata(run_id="r1"), m.PhaseCompletion(run_id="r1", phase_name="p01"),
                   m.RunSpec(run_id="r1", spec_type="backend", spec={}),
                   m.Event(run_id="r1", agent="y", org_id="explicit")])
        s.commit()
        got = [o for cls in (m.Event, m.PipelineEvent, m.RunMetadata, m.PhaseCompletion, m.RunSpec) for o in s.query(cls)]
        assert sorted(o.org_id for o in got) == ["explicit"] + ["org-a"] * 5


def _load(path):
    spec = importlib.util.spec_from_file_location("mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_adds_backfills_and_indexes_and_chains_after_the_merge():
    mig = _load(ROOT / "alembic" / "versions" / "add_org_id_to_run_tables.py")
    assert mig.down_revision == "merge_r2_heads"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE runs (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(50))"))
        conn.execute(text("INSERT INTO runs VALUES ('r1', 'org-a'), ('r2', NULL)"))
        for t in RUN_TABLES:
            conn.execute(text(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, run_id VARCHAR(36))"))
            conn.execute(text(f"INSERT INTO {t} (run_id) VALUES ('r1'), ('r2')"))
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()      # idempotent
        for t in RUN_TABLES:
            assert [r[0] for r in conn.execute(text(f"SELECT org_id FROM {t} ORDER BY id"))] == ["org-a", None]
            idx = [r[1] for r in conn.execute(text(f"PRAGMA index_list({t})"))]
            assert f"ix_{t}_org_id" in idx


def test_retention_purges_only_rows_older_than_the_window(monkeypatch):
    spec = importlib.util.spec_from_file_location("retention_purge", ROOT / "scripts" / "retention_purge.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    now = datetime.now(timezone.utc)
    old, new = (now - timedelta(days=400)), (now - timedelta(days=1))
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE llm_traces (id VARCHAR PRIMARY KEY, created_at DATETIME)"))
        c.execute(text("CREATE TABLE pipeline_events (id VARCHAR PRIMARY KEY, created_at DATETIME)"))
        c.execute(text("CREATE TABLE events (id VARCHAR PRIMARY KEY, timestamp FLOAT)"))
        c.execute(text("CREATE TABLE snapshots (id VARCHAR PRIMARY KEY, created_at FLOAT)"))
        for t in ("llm_traces", "pipeline_events"):
            c.execute(text(f"INSERT INTO {t} VALUES ('old', :o), ('new', :n)"), {"o": old.replace(tzinfo=None), "n": new.replace(tzinfo=None)})
        for t, col in (("events", "timestamp"), ("snapshots", "created_at")):
            c.execute(text(f"INSERT INTO {t} VALUES ('old', :o), ('new', :n)"), {"o": old.timestamp(), "n": new.timestamp()})
    assert rp.purge(engine, now=now, dry_run=True) == {"llm_traces": 1, "pipeline_events": 1, "events": 1, "snapshots": 1}
    assert rp.purge(engine, now=now) == {"llm_traces": 1, "pipeline_events": 1, "events": 1, "snapshots": 1}
    with engine.connect() as c:
        for t in ("llm_traces", "pipeline_events", "events", "snapshots"):
            assert [r[0] for r in c.execute(text(f"SELECT id FROM {t}"))] == ["new"]
    monkeypatch.setenv("AETHER_RETENTION_TRACE_DAYS", "0")
    assert "llm_traces" not in rp.purge(engine, now=now)
