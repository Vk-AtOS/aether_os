"""Run da281716 ended failed and the acceptance suite reported "no error recorded": _abort_run stored the blocking
stage's reason in Run.message (and returns it as "error"), but GET /factory/runs/{id} served it only as "message".
The run record now carries it as "error", with the stage that blocked the run as "failed_stage".
"""
from __future__ import annotations

import asyncio

import pytest

import aether_os.core.db as _db_mod
from aether_os.core.db_utils import _failure_fields, get_run_detail

REASON = ("Stage s07_healing did not pass its gate after retries: s07_healing: healing did not get the unit tests "
          "passing (max_attempts_reached)")


def test_failure_fields_name_the_reason_and_the_last_failed_stage():
    phases = {"s04_frontend": {"status": "timeout", "updated_at": 10.0},
              "s06_testing": {"status": "passed", "updated_at": 20.0},
              "s07_healing": {"status": "failed", "updated_at": 30.0}}
    assert _failure_fields("failed", REASON, phases) == {"error": REASON, "failed_stage": "s07_healing"}
    assert _failure_fields("completed", "done", phases) == {"error": None, "failed_stage": None}
    assert _failure_fields("failed", "", {}) == {"error": None, "failed_stage": None}


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_db_mod, "_engine", None)
    monkeypatch.setattr(_db_mod, "_session_factory", None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/runs.db")
    asyncio.run(_db_mod.init_db())
    yield
    monkeypatch.setattr(_db_mod, "_engine", None)
    monkeypatch.setattr(_db_mod, "_session_factory", None)


def test_the_run_record_serves_the_stored_failure_reason_as_error(sqlite_db):
    from aether_os.core.audit.ledger import DecisionLedger
    from aether_os.core.models import Organisation
    from aether_os.orchestrator.run_state import update_phase_state

    async def scenario():
        async with _db_mod.get_session_factory()() as session:
            session.add(Organisation(id="org-r", name="R", slug="org-r"))
            await session.commit()
        ledger = DecisionLedger()
        await ledger.async_save_run("run-r", "factory: tracker", "org-r", "running")
        await update_phase_state("run-r", "s07_healing", "failed")
        await ledger.async_update_run_status("run-r", "failed", message=REASON)    # what _abort_run does
        return await get_run_detail("run-r", org_id="org-r")

    detail = asyncio.run(scenario())
    assert detail["status"] == "failed" and detail["error"] == REASON and detail["failed_stage"] == "s07_healing"
