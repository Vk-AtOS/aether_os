"""core.db: PgBouncer-safe asyncpg settings, statement timeout, Alembic owns the PG schema, hot indexes."""
import asyncio
import re
from pathlib import Path

import pytest

import aether_os.core.db as db

ROOT = Path(__file__).resolve().parents[1]


def test_statement_timeout_is_configurable(monkeypatch):
    monkeypatch.delenv("DB_PGBOUNCER", raising=False)
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "5000")
    kw = db._postgres_engine_kwargs()
    assert kw["connect_args"]["server_settings"]["statement_timeout"] == "5000"
    assert "statement_cache_size" not in kw["connect_args"]


def test_pgbouncer_transaction_mode_disables_statement_cache(monkeypatch):
    monkeypatch.setenv("DB_PGBOUNCER", "true")
    ca = db._postgres_engine_kwargs()["connect_args"]
    assert ca["statement_cache_size"] == 0
    assert "server_settings" not in ca  # startup parameters do not survive transaction pooling


def test_pgbouncer_ini_enforces_query_timeout():
    ini = (ROOT / "deploy/pgbouncer.ini").read_text()
    assert re.search(r"^query_timeout\s*=\s*\d+", ini, re.M)


def test_init_db_refuses_unmigrated_postgres(monkeypatch):
    class Eng:
        class dialect:
            name = "postgresql"

        def connect(self):
            raise RuntimeError("no alembic_version table")

    monkeypatch.setattr(db, "get_engine", lambda: Eng())
    monkeypatch.delenv("AETHER_DB_CREATE_ALL", raising=False)
    with pytest.raises(db.SchemaNotMigrated):
        asyncio.run(db.init_db())


def test_hot_filter_migration_and_init_db_define_the_same_indexes():
    # Both now read core/schema_ddl.INDEXES (one definition); the migration only names which ones it creates.
    from aether_os.core import schema_ddl
    mig = (ROOT / "alembic/versions/add_hot_filter_indexes.py").read_text()
    names = re.findall(r'"(ix_[a-z_]+)"', mig)
    assert names and all(n in schema_ddl.INDEXES for n in names)
    joined = " ".join(schema_ddl.INDEXES[n] for n in names)
    for needle in ("runs(org_id, status)", "runs(org_id, started_at)", "notifications(", "artifact_embeddings(", "marketplace_profiles("):
        assert needle in joined
