"""Regression: generated models.py must create every index exactly once.

First real run: the generated backend crashed at startup with
`sqlite3.OperationalError: index ix_tasks_status already exists`. The IR field `status` had index=True, so the
column got `Column(..., index=True)` (SQLAlchemy names it ix_tasks_status) AND generate_models_py added the
performance index `Index('ix_tasks_status', 'status')`. Model-written IRs also repeat fields.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

from aether_os.core.domain_ir import DomainIR
from aether_os.phases.p04a_backend_codegen import ir_generators as g

IR = {
    "domain": "crm", "app_name": "Demo",
    "entities": [
        {"name": "Project", "table": "projects", "fields": [
            {"name": "name", "type": "string", "nullable": False}]},
        {"name": "Task", "table": "tasks", "fields": [
            {"name": "title", "type": "string", "nullable": False},
            # index=True on a column that also gets the explicit status performance index
            {"name": "status", "type": "enum", "enum_values": ["open", "done"], "index": True},
            # the same field again, as real model output does
            {"name": "status", "type": "enum", "enum_values": ["open", "done"], "index": True},
            {"name": "state", "type": "string", "index": True},
            {"name": "project_id", "type": "fk", "ref_entity": "Project", "index": True},
            # generator-owned columns repeated by the IR
            {"name": "id", "type": "integer", "index": True},
            {"name": "created_at", "type": "datetime", "index": True}]},
    ],
}

_RUNNER = r'''
import asyncio, collections, sys
sys.path.insert(0, sys.argv[1])
from sqlalchemy.ext.asyncio import create_async_engine
from database import Base
import models  # noqa: F401  (registers the tables)

names = [ix.name for t in Base.metadata.sorted_tables for ix in t.indexes]
dupes = [n for n, c in collections.Counter(names).items() if c > 1]
assert not dupes, dupes

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

asyncio.run(main())
tasks = Base.metadata.tables["tasks"]
print(sorted(ix.name for ix in tasks.indexes))
print(tasks.c.id.primary_key)
'''


def _models(tmp_path) -> str:
    ir = DomainIR._from_dict(IR)
    code = g.generate_models_py(ir, domain="crm")
    (tmp_path / "models.py").write_text(code)
    (tmp_path / "database.py").write_text(textwrap.dedent("""\
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
    """))
    return code


def test_each_field_emitted_once(tmp_path):
    code = _models(tmp_path)
    task = code.split("class Task(Base):", 1)[1]
    assert task.count("    status = Column(") == 1
    assert task.count("    id = Column(") == 1
    assert task.count("    created_at = Column(") == 1
    assert "Index('ix_tasks_status'" not in task   # the column index already covers it
    assert "Index('ix_tasks_state'" not in task
    assert "Index('ix_tasks_created_at', 'created_at')" in task


def test_create_all_on_sqlite_has_no_duplicate_index(tmp_path):
    _models(tmp_path)
    done = subprocess.run([sys.executable, "-c", _RUNNER, str(tmp_path)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    indexes, pk = done.stdout.strip().splitlines()
    assert indexes == str(sorted(["ix_tasks_created_at", "ix_tasks_id", "ix_tasks_project_id", "ix_tasks_state", "ix_tasks_status"]))
    assert pk == "True"


def test_explicit_status_index_kept_when_column_not_indexed(tmp_path):
    ir = DomainIR._from_dict({"domain": "crm", "app_name": "Demo", "entities": [
        {"name": "Ticket", "table": "tickets", "fields": [{"name": "status", "type": "string"}]}]})
    code = g.generate_models_py(ir, domain="crm")
    assert "Index('ix_tickets_status', 'status')" in code
    assert "status = Column(String(255))" in code
