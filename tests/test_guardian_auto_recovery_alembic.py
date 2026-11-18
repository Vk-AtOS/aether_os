"""KAN-102: recovery must not report success when the migration step did not (or could not) run."""
import asyncio
import types

import pytest

from aether_os.core.guardian import auto_recovery as ar


def test_missing_alembic_ini_is_a_failure_not_a_pass(monkeypatch):
    monkeypatch.setattr(ar.AutoRecovery, "_alembic_ini", staticmethod(lambda: None))
    assert asyncio.run(ar.AutoRecovery()._run_alembic_upgrade()) is False


def test_alembic_ini_is_found_in_this_tree():
    assert ar.AutoRecovery._alembic_ini() is not None


class _Mgr:
    async def take_snapshot(self, **kw): return None
    async def get_latest(self): return types.SimpleNamespace(id="s1", created_at=__import__("datetime").datetime(2026, 1, 1))
    async def restore(self, sid): return True


@pytest.mark.parametrize("alembic_ok,expected", [(True, True), (False, False)])
def test_recover_returns_true_only_when_data_and_schema_are_both_back(monkeypatch, alembic_ok, expected):
    import aether_os.core.guardian.snapshot_manager as sm
    rec = ar.AutoRecovery()

    async def alembic(): return alembic_ok
    async def health(): return True
    async def log(**kw): return None
    monkeypatch.setattr(sm, "get_snapshot_manager", lambda: _Mgr())
    monkeypatch.setattr(rec, "_run_alembic_upgrade", alembic)
    monkeypatch.setattr(rec, "_verify_health", health)
    monkeypatch.setattr(rec, "_log_event", log)

    class _S:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, q): return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: []))
    import aether_os.core.db as db
    monkeypatch.setattr(db, "get_session_factory", lambda: (lambda: _S()))
    assert asyncio.run(rec.recover()) is expected
