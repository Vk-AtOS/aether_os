"""A Postgres schema without the ledger triggers (create_all / stamped bootstrap) must be refused (KAN-102)."""
import asyncio
from unittest.mock import MagicMock

import pytest

from aether_os.core import db


class _Conn:
    def __init__(self, names):
        self.names = names

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        r = MagicMock()
        r.scalars.return_value = iter(self.names)
        return r


def _engine(names):
    e = MagicMock()
    e.connect.return_value = _Conn(names)
    return e


def test_missing_ledger_triggers_refuse_startup():
    with pytest.raises(db.SchemaNotMigrated, match="audit_checkpoints_no_update_delete"):
        asyncio.run(db.require_ledger_triggers(_engine(["audit_chain_no_update_delete", "audit_chain_legacy_frozen"])))
    asyncio.run(db.require_ledger_triggers(_engine(list(db.LEDGER_TRIGGERS))))


def test_every_trigger_the_migrations_create_is_in_the_required_list():
    import pathlib
    import re
    names = set()
    for f in pathlib.Path(db.__file__).resolve().parent.parent.joinpath("alembic/versions").glob("*.py"):
        names |= set(re.findall(r"CREATE TRIGGER (\w+)", f.read_text()))
    assert names <= set(db.LEDGER_TRIGGERS) or names - set(db.LEDGER_TRIGGERS) == set(), names
