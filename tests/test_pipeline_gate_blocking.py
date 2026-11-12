"""Run control: failed gates block, stage toggles are honoured, stage ids are canonical,
and no raw exception text reaches the event stream.

The real FactoryPipeline runs against a throwaway SQLite database. Only the twelve
stage supervisors are replaced (no model is called), plus the post-stage hooks and the
completion tasks, which read generated files and are not under test here.
"""
from __future__ import annotations

import json
from collections import defaultdict
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio
from sqlalchemy import select

import aether_os.core.db as db
import aether_os.core.pipeline_state as pipeline_state
import aether_os.orchestrator.artifact_collector as artifact_collector
import aether_os.orchestrator.events as events
import aether_os.orchestrator.factory_pipeline as fp
from aether_os.core.models import Organisation, PhaseCompletion, PhaseConfig, Run
from aether_os.orchestrator.parallel_runner import run_phases_in_wave
from aether_os.orchestrator.phase_selector import (
    LEGACY_STAGE_IDS, restore_from_checkpoint, select_phases,
)
from aether_os.orchestrator.phase_sequence import CRITICAL_PHASES, PHASE_SEQUENCE
from aether_os.orchestrator.stage_gate import MANDATORY_STAGES
from aether_os.phases.base import TaskResult

ORG = "org_gate_test"
SECRET = "S3cr3tPw"
LEAKY = f"could not connect to postgresql://aether:{SECRET}@10.0.0.5/app"


def gate_failed(reason: str) -> TaskResult:
    """What PhaseBase.run returns when a stage's gate still fails after its retries."""
    return TaskResult(output_path="", confidence=0.0, success=False, escalated=True, issues=[reason])


@pytest_asyncio.fixture
async def pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))   # generated projects go under ~/.aether_os
    monkeypatch.delenv("MONITOR_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/pipe.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    # No Redis: events are buffered in pipeline_state._local_history, where we read them.
    monkeypatch.setattr(pipeline_state, "get_redis", AsyncMock(return_value=None))
    monkeypatch.setattr(pipeline_state, "_local_history", defaultdict(list))
    monkeypatch.setattr(pipeline_state, "_local_control", {})

    outcomes: dict = {}   # stage -> TaskResult to return, or Exception to raise
    ran: list = []

    class Supervisor:
        def __init__(self, name):
            self.name = name

        async def run(self, _phase_input):
            ran.append(self.name)
            outcome = outcomes.get(self.name, TaskResult(output_path="", confidence=1.0))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(fp, "_load_supervisor", Supervisor)
    monkeypatch.setattr(fp, "run_phase_hooks", AsyncMock())
    monkeypatch.setattr(fp, "schedule_completion_tasks", lambda **_k: None)

    class Harness:
        pass

    h = Harness()
    h.outcomes, h.ran, h.sf = outcomes, ran, db.get_session_factory()
    async with h.sf() as s:
        s.add(Organisation(id=ORG, name="Gate Test", slug="gate-test", plan="pro"))
        await s.commit()

    async def run(run_id="run-1", **kw):
        return await fp.FactoryPipeline()._execute_pipeline(
            client_id="c1", raw_input="Build the Ledger app", run_id=run_id, org_id=ORG, **kw)

    async def run_row(run_id="run-1"):
        async with h.sf() as s:
            return await s.get(Run, run_id)

    async def stage_rows(run_id="run-1"):
        async with h.sf() as s:
            rows = (await s.execute(select(PhaseCompletion).where(PhaseCompletion.run_id == run_id))).scalars()
            return {r.phase_name: r.status for r in rows}

    def stream(run_id="run-1"):
        return [json.loads(p) for p in pipeline_state._local_history.get(run_id, [])]

    h.run, h.run_row, h.stage_rows, h.stream = run, run_row, stage_rows, stream
    yield h
    await engine.dispose()


# ── 1. A failed gate blocks ───────────────────────────────────────────────────

async def test_failed_gate_ends_run_at_that_stage_and_restart_resumes_there(pipe):
    pipe.outcomes["s04_frontend"] = gate_failed(f"frontend did not build: {LEAKY}")

    result = await pipe.run()

    assert result["status"] == "failed" and result["failed_stage"] == "s04_frontend"
    assert pipe.ran == ["s01_intake", "s02_architecture", "s03_backend", "s04_frontend"]
    run = await pipe.run_row()
    assert run.status == "failed"
    assert run.message.startswith("Stage s04_frontend did not pass its gate after retries: frontend did not build")
    assert SECRET not in run.message
    rows = await pipe.stage_rows()
    assert rows["s04_frontend"] == "failed" and rows["s03_backend"] == "passed"
    assert not set(rows) & {"s05_quality", "s06_testing", "s11_handoff", "pipeline"}
    # The checkpoint still points at the stage before the blocked one ...
    assert run.checkpoint_data["last_completed_phase"] == "s03_backend"
    done = [e for e in pipe.stream() if e["type"] == "pipeline_complete"]
    assert done and done[-1]["status"] == "failed" and done[-1]["failed_stage"] == "s04_frontend"

    # ... so restarting the same run (POST /factory/runs/{id}/restart) resumes at it.
    pipe.outcomes.clear()
    pipe.ran.clear()
    result = await pipe.run()
    assert result["status"] == "complete"
    assert pipe.ran[0] == "s04_frontend" and "s11_handoff" in pipe.ran
    assert not {"s01_intake", "s02_architecture", "s03_backend"} & set(pipe.ran)
    assert (await pipe.stage_rows())["s04_frontend"] == "passed"


async def test_failed_gate_in_a_parallel_wave_blocks_and_is_not_checkpointed(pipe):
    pipe.outcomes["s12_specialist"] = gate_failed("mobile build failed")   # runs beside s05

    result = await pipe.run()

    assert result["status"] == "failed" and result["failed_stage"] == "s12_specialist"
    assert "s06_testing" not in pipe.ran and "s11_handoff" not in pipe.ran
    assert (await pipe.stage_rows())["s12_specialist"] == "failed"
    run = await pipe.run_row()
    assert "s12_specialist did not pass its gate" in run.message
    # Checkpointing the wave would make a restart resume at s06 and never re-run s12.
    assert run.checkpoint_data["last_completed_phase"] == "s04_frontend"


async def test_crashed_critical_stage_blocks_and_crashed_optional_stage_is_recorded_failed(pipe):
    pipe.outcomes["s08_observability"] = RuntimeError("grafana template missing")
    assert (await pipe.run("run-a"))["status"] == "complete"
    assert (await pipe.stage_rows("run-a"))["s08_observability"] == "failed"   # was "completed"

    pipe.ran.clear()
    pipe.outcomes["s02_architecture"] = RuntimeError("no entities extracted")
    result = await pipe.run("run-b")
    assert result["status"] == "failed" and result["failed_stage"] == "s02_architecture"
    assert pipe.ran == ["s01_intake", "s02_architecture"]
    assert "no entities extracted" in (await pipe.run_row("run-b")).message


# ── 2. Stage toggles ──────────────────────────────────────────────────────────

async def test_disabled_optional_stage_is_skipped_and_mandatory_disable_is_ignored(pipe):
    async with pipe.sf() as s:
        s.add_all([
            PhaseConfig(org_id=ORG, phase_name="s10_enterprise", enabled=0),
            PhaseConfig(org_id=ORG, phase_name="s03_backend", enabled=0),
            PhaseConfig(org_id=ORG, phase_name="s12_specialist", enabled=1),
            PhaseConfig(org_id="org_someone_else", phase_name="s08_observability", enabled=0),
        ])
        await s.commit()

    result = await pipe.run()

    assert result["status"] == "complete"
    assert "s10_enterprise" not in pipe.ran
    assert {"s03_backend", "s08_observability", "s12_specialist", "s11_handoff"} <= set(pipe.ran)
    rows = await pipe.stage_rows()
    assert rows["s10_enterprise"] == "skipped" and rows["s03_backend"] == "passed"
    assert result["phases"]["s10_enterprise"]["metadata"]["skipped_reason"] == "disabled_in_settings"
    ignored = [e for e in pipe.stream() if e["type"] == "stage_toggle_ignored"]
    assert [e["phase"] for e in ignored] == ["s03_backend"]
    assert "cannot be switched off" in ignored[0]["reason"]
    toggles = (await pipe.run_row()).checkpoint_data["accumulated_context"]["stage_toggles"]
    assert toggles["skipped"] == ["s10_enterprise"] and list(toggles["ignored"]) == ["s03_backend"]


async def test_mandatory_and_optional_stages_cover_the_sequence():
    assert set(MANDATORY_STAGES) <= set(PHASE_SEQUENCE) and CRITICAL_PHASES <= set(MANDATORY_STAGES)
    assert set(PHASE_SEQUENCE) - set(MANDATORY_STAGES) == {
        "s08_observability", "s10_enterprise", "s12_specialist"}


# ── 3. Stage ids ──────────────────────────────────────────────────────────────

async def test_stage_ids_are_canonical_and_legacy_ids_map_to_their_stage():
    assert select_phases(PHASE_SEQUENCE, "s01_intake") == PHASE_SEQUENCE
    assert select_phases(PHASE_SEQUENCE, "s07_healing")[0] == "s07_healing"
    assert LEGACY_STAGE_IDS["p01_intake_requirements"] == "s01_intake"
    assert select_phases(PHASE_SEQUENCE, "p01_intake_requirements") == PHASE_SEQUENCE
    assert select_phases(PHASE_SEQUENCE, "p04_backend")[0] == "s03_backend"   # was: full sequence
    assert set(LEGACY_STAGE_IDS.values()) == set(PHASE_SEQUENCE)
    with pytest.raises(ValueError, match="Unknown stage id 'p99_nope'"):
        select_phases(PHASE_SEQUENCE, "p99_nope")


async def test_unknown_start_stage_fails_the_run_instead_of_rebuilding_everything(pipe):
    result = await pipe.run(start_phase="p99_nope")
    assert result["status"] == "failed" and pipe.ran == []
    run = await pipe.run_row()
    assert run.status == "failed" and "Unknown stage id 'p99_nope'" in run.message


async def test_old_checkpoint_with_legacy_id_resumes_at_the_containing_stage(pipe):
    async with pipe.sf() as s:
        s.add(Run(id="old-run", org_id=ORG, command="factory: x", status="failed", checkpoint_data={
            "last_completed_phase": "p04_backend", "accumulated_context": {"domain": "general"}}))
        await s.commit()
    phases, _ctx = await restore_from_checkpoint(
        "old-run", PHASE_SEQUENCE, list(PHASE_SEQUENCE), {}, AsyncMock())
    assert phases[0] == "s03_backend"   # was: checkpoint ignored, whole pipeline re-run


# ── 5. Exception text on the event stream ─────────────────────────────────────

async def test_every_orchestrator_publisher_is_the_one_redacting_function():
    assert fp.publish_event is events.publish_event
    assert artifact_collector.publish_event is events.publish_event
    out = events.redact_event({"type": "x", "error": LEAKY, "issues": [LEAKY], "text": "kept as is"})
    assert SECRET not in json.dumps(out) and out["text"] == "kept as is"


async def test_exception_text_is_redacted_on_the_stream_sequential_and_parallel(pipe, tmp_path):
    pipe.outcomes["s03_backend"] = RuntimeError(LEAKY)
    result = await pipe.run()
    assert result["status"] == "failed" and SECRET not in json.dumps(result)

    async def crash(_name, _input):
        raise RuntimeError(LEAKY)

    await run_phases_in_wave(
        wave=["s05_quality", "s12_specialist"], run_phase_fn=crash, accumulated_context={},
        run_id="run-1", org_id=ORG, project_dir=tmp_path, domain="general", client_id="c1",
        emit_fn=events.emit, update_state_fn=AsyncMock(), phase_input_cls=fp.PhaseInput,
        critical_phases=CRITICAL_PHASES)

    stream = pipe.stream()
    failed = [e for e in stream if e.get("status") == "failed"]
    assert len(failed) >= 4   # s03 stage + run, and both wave stages
    assert all("[redacted]" in e["error"] for e in failed if e["type"] == "phase_complete")
    assert SECRET not in json.dumps(stream)
