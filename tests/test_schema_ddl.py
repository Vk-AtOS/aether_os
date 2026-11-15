"""The empty-database bootstrap (create_all + core/schema_ddl.py + stamp) and the Alembic revisions share ONE
definition of every raw-SQL schema object.

Root cause: scripts/db_migrate.py bootstrapped an empty database with create_all and stamped head, which skipped
everything only the revisions created through op.execute: the audit-ledger append-only triggers, the pgvector
column/index and the extra indexes. A fresh deployment therefore had an editable ledger. The Postgres test needs
AETHER_TEST_PG_ADMIN_URL (a server you may create databases on); the rest run anywhere.
"""
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from aether_os.core import schema_ddl
from aether_os.core.db import Base

ROOT = Path(__file__).resolve().parents[1]


def test_every_module_that_declares_a_table_is_registered_for_the_bootstrap():
    declaring = set()
    for top in ("core", "prime", "gateway", "integrations"):
        for path in (ROOT / top).rglob("*.py"):
            if re.search(r"^\s+__tablename__\s*=", path.read_text(errors="ignore"), re.M):
                declaring.add(path.relative_to(ROOT).with_suffix("").as_posix().replace("/", "."))
    declaring -= {"core.scim_models"}   # imported by core.models
    assert declaring <= set(schema_ddl.MODEL_MODULES), sorted(declaring - set(schema_ddl.MODEL_MODULES))


def test_shared_indexes_point_at_real_tables_and_columns():
    schema_ddl.register_models()
    for name, target in schema_ddl.INDEXES.items():
        table, cols = re.fullmatch(r"(\w+)\(([^)]*)\)", target).groups()
        assert table in Base.metadata.tables, name
        assert {c.strip() for c in cols.split(",")} <= set(Base.metadata.tables[table].c.keys()), name


def test_revisions_do_not_carry_their_own_copy_of_ledger_triggers_functions_or_extensions():
    raw = re.compile(r"CREATE\s+(OR\s+REPLACE\s+)?(TRIGGER|FUNCTION|EXTENSION)\s", re.I)
    offenders = [p.name for p in (ROOT / "alembic/versions").glob("*.py") if raw.search(p.read_text())]
    assert not offenders, f"move the DDL into core/schema_ddl.py: {offenders}"


def test_unknown_object_name_is_refused():
    with pytest.raises(KeyError):
        schema_ddl.apply(create_engine("sqlite://").connect(), only=("no_such_object",))


PG = os.environ.get("AETHER_TEST_PG_ADMIN_URL", "")


@pytest.mark.skipif(not PG, reason="AETHER_TEST_PG_ADMIN_URL is not set (needs a Postgres server)")
def test_a_freshly_bootstrapped_postgres_rejects_updates_and_deletes_on_the_ledger():
    name = f"aether_ddl_{uuid.uuid4().hex[:8]}"
    admin = create_engine(PG, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = PG.rsplit("/", 1)[0] + "/" + name
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT.parent), "AETHER_FIELD_KEY": "x"}
    try:
        run = subprocess.run([sys.executable, "scripts/db_migrate.py"], env=env, cwd=ROOT, capture_output=True,
                             text=True, timeout=240)
        assert run.returncode == 0, run.stderr[-800:]
        eng = create_engine(url)
        with eng.begin() as c:
            have = set(c.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
            assert set(schema_ddl.PG_TRIGGERS) <= have
            idx = set(c.execute(text("SELECT indexname FROM pg_indexes")).scalars())
            assert set(schema_ddl.INDEXES) <= idx, sorted(set(schema_ddl.INDEXES) - idx)
            c.execute(text("INSERT INTO audit_chain (chain_id, chain_seq, timestamp, actor, action, payload, prev_hash, "
                           "entry_hash) VALUES ('org_x', 1, 1.0, 'a', 'b', '{}', 'p', 'e')"))
        for stmt in ("UPDATE audit_chain SET actor = 'evil'", "DELETE FROM audit_chain"):
            with pytest.raises(Exception, match="append-only"):
                with eng.begin() as c:
                    c.execute(text(stmt))
        with pytest.raises(Exception, match="frozen"):
            with eng.begin() as c:
                c.execute(text("INSERT INTO audit_chain (chain_id, timestamp, actor, action, payload, prev_hash, "
                               "entry_hash) VALUES ('legacy', 1.0, 'a', 'b', '{}', 'p2', 'e2')"))
        eng.dispose()
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
