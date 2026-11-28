"""KAN-274: phase duration is recorded, error registry entries carry their run id, the API log survives a recreate."""
import logging
import time
from pathlib import Path

import pytest
import pytest_asyncio
import yaml

import aether_os.core.db as db
from aether_os.core import logging_config
from aether_os.core.error_registry import ErrorCategory, ErrorRegistry
from aether_os.core.models import PhaseCompletion, Run
from aether_os.core.run_context import ACTIVE_RUN_ID
from aether_os.orchestrator.run_state import update_phase_state

ROOT = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def dbenv(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    async with db.get_engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_factory()() as s:
        s.add(Run(id="r1", status="running", started_at=time.time()))
        await s.commit()
    yield
    await db.get_engine().dispose()


async def _row(run_id, phase):
    async with db.get_session_factory()() as s:
        return await s.get(PhaseCompletion, (run_id, phase))


@pytest.mark.asyncio
async def test_phase_duration_is_the_time_between_running_and_the_end(dbenv):
    await update_phase_state("r1", "s01", "running")
    async with db.get_session_factory()() as s:       # pretend it went "running" 12.5 s ago
        pc = await s.get(PhaseCompletion, ("r1", "s01"))
        pc.updated_at = time.time() - 12.5
        await s.commit()
    await update_phase_state("r1", "s01", "complete")
    pc = await _row("r1", "s01")
    assert pc.status == "complete" and 12.0 <= pc.duration_s <= 14.0


@pytest.mark.asyncio
async def test_skipped_phase_that_never_ran_has_no_duration(dbenv):
    await update_phase_state("r1", "s02", "skipped")
    assert (await _row("r1", "s02")).duration_s is None


def test_error_registry_records_the_active_run_and_an_explicit_one_wins(tmp_path):
    reg = ErrorRegistry(json_path=tmp_path / "e.json")
    token = ACTIVE_RUN_ID.set("run-123")
    try:
        reg.record(ErrorCategory.RELATIVE_IMPORT, "p04a", "from .models import X")
        reg.record(ErrorCategory.UNKNOWN, "p04a", "x", run_id="explicit")
    finally:
        ACTIVE_RUN_ID.reset(token)
    reg.record(ErrorCategory.UNKNOWN, "p04a", "no run")
    assert [e["run_id"] for e in reg._load()] == ["run-123", "explicit", ""]
    assert len(reg.get_for_run("run-123")) == 1


def test_file_handler_writes_under_the_state_dir_and_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_STATE_DIR", str(tmp_path))
    h = logging_config.file_handler(logging.Formatter("%(message)s"))
    assert h is not None
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "hello persistent", None, None)
    h.emit(rec)
    h.close()
    assert "hello persistent" in (tmp_path / "logs" / "api.log").read_text()
    monkeypatch.setenv("LOG_TO_FILE", "0")
    assert logging_config.file_handler(logging.Formatter("%(message)s")) is None


def test_unwritable_log_dir_is_not_fatal(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("AETHER_STATE_DIR", str(blocker))      # a file where the directory should be
    assert logging_config.file_handler(logging.Formatter("%(message)s")) is None


def test_compose_api_logs_are_rotated_and_state_dir_is_a_host_volume():
    api = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["api"]
    assert api["logging"]["driver"] == "json-file" and api["logging"]["options"]["max-file"]
    assert any(v.startswith("/home/aether/.aether_os:") for v in api["volumes"])   # logs/api.log lands on the host
