"""
AetherOS — Factory Pipeline Tests
Covers: MessageBus, Messages, ProjectManager, UsageTracker, FactoryPipeline
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_session_factory():
    """Return a no-op async session factory so tests never open aiosqlite connections."""
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(
            first=MagicMock(return_value=None),
            all=MagicMock(return_value=[]),
        ))
    ))

    @asynccontextmanager
    async def _session():
        yield mock_session

    def _factory():
        return _session()

    return _factory

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ═══════════════════════════════════════════════════════════════════════════════
# MessageBus
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bus_publish_and_drain():
    """Bus.drain() returns messages published since last drain."""
    from aether_os.orchestrator.bus import MessageBus
    from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

    bus = MessageBus(run_id="test-drain")
    result = PhaseResult(
        run_id="test-drain",
        phase="p00_intake",
        status="passed",
        output_path="/tmp/out",
        confidence=0.9,
        issues=[],
        next_phase="p01_requirements",
        upstream_route=None,
        failure_context=None,
        artifacts={"domain": "fintech"},
    )
    msg = PhaseMessage(
        message_id="msg-1",
        from_phase="p00_intake",
        to_phase=None,
        result=result,
    )
    await bus.publish(msg)
    msgs = await bus.drain()
    assert len(msgs) == 1
    assert msgs[0].from_phase == "p00_intake"


@pytest.mark.asyncio
async def test_bus_drain_clears_queue():
    """Bus.drain() empties the queue; second drain returns empty list."""
    from aether_os.orchestrator.bus import MessageBus
    from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

    bus = MessageBus(run_id="test-clear")
    result = PhaseResult(
        run_id="test-clear",
        phase="p01_requirements",
        status="passed",
        output_path="",
        confidence=1.0,
        issues=[],
        next_phase=None,
        upstream_route=None,
        failure_context=None,
        artifacts={},
    )
    msg = PhaseMessage(message_id="m2", from_phase="p01_requirements", to_phase=None, result=result)
    await bus.publish(msg)
    await bus.drain()
    second = await bus.drain()
    assert second == []


@pytest.mark.asyncio
async def test_bus_broadcast_status():
    """broadcast_status publishes a synthetic message."""
    from aether_os.orchestrator.bus import MessageBus

    bus = MessageBus(run_id="run-1")
    await bus.broadcast_status("run-1", "p02_architecture", "passed")
    msgs = await bus.drain()
    assert len(msgs) == 1
    assert msgs[0].result.status == "passed"


@pytest.mark.asyncio
async def test_get_bus_registry():
    """get_bus returns same instance for same run_id."""
    from aether_os.orchestrator.bus import get_bus, release_bus

    bus1 = get_bus("run-abc")
    bus2 = get_bus("run-abc")
    assert bus1 is bus2
    release_bus("run-abc")
    bus3 = get_bus("run-abc")
    assert bus3 is not bus1  # new instance after release


@pytest.mark.asyncio
async def test_bus_fan_out_to_subscriber():
    """Messages with a to_phase are fan-out to that phase's subscriber queue."""
    from aether_os.orchestrator.bus import MessageBus
    from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

    bus = MessageBus(run_id="sub-run")
    # Subscribe creates the queue; then publish fan-outs to it
    # We need to prime the subscriber queue before publishing
    if "p01_requirements" not in bus._subscribers:
        bus._subscribers["p01_requirements"] = asyncio.Queue()

    result = PhaseResult(
        run_id="sub-run", phase="p00_intake", status="passed",
        output_path="", confidence=0.8, issues=[], next_phase="p01_requirements",
        upstream_route=None, failure_context=None, artifacts={},
    )
    msg = PhaseMessage(message_id="sub-msg", from_phase="p00_intake",
                       to_phase="p01_requirements", result=result)
    # Force in-memory fan-out by making Redis unavailable for this publish
    with patch.object(bus, "_get_redis", new_callable=AsyncMock, return_value=None):
        await bus.publish(msg)
    item = bus._subscribers["p01_requirements"].get_nowait()
    assert item.from_phase == "p00_intake"


# ═══════════════════════════════════════════════════════════════════════════════
# Messages (Pydantic models)
# ═══════════════════════════════════════════════════════════════════════════════

def test_phase_input_defaults():
    from aether_os.orchestrator.messages import PhaseInput

    pi = PhaseInput(
        run_id="r1", project_id="p1", phase="p00_intake",
        input_data={"raw_text": "hello"}, output_dir="/tmp",
        domain="general", client_id="client-1",
    )
    assert pi.is_change_request is False
    assert pi.memory_context == []
    assert pi.change_context is None


def test_phase_result_artifacts():
    from aether_os.orchestrator.messages import PhaseResult

    pr = PhaseResult(
        run_id="r2", phase="p01_requirements", status="passed",
        output_path="/tmp/req.md", confidence=0.95, issues=[],
        next_phase="p02_architecture", upstream_route=None,
        failure_context=None, artifacts={"reqs": "done"},
    )
    assert pr.artifacts["reqs"] == "done"
    assert pr.confidence == 0.95


def test_phase_message_has_timestamp():
    from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

    result = PhaseResult(
        run_id="r3", phase="p00_intake", status="failed",
        output_path="", confidence=0.1, issues=["missing text"],
        next_phase=None, upstream_route=None, failure_context=None, artifacts={},
    )
    msg = PhaseMessage(message_id="ts-msg", from_phase="p00_intake", to_phase=None, result=result)
    assert msg.timestamp is not None
    assert msg.message_id == "ts-msg"


# ═══════════════════════════════════════════════════════════════════════════════
# ProjectManager
# ═══════════════════════════════════════════════════════════════════════════════

def test_project_create_and_get(tmp_path):
    """create_project returns an ID; get_project retrieves it."""
    from aether_os.core.projects import ProjectManager

    pm = ProjectManager(root=tmp_path / "projects")
    pid = pm.create_project("client-x", "My App")
    assert pid != ""
    proj = pm.get_project(pid)
    assert proj is not None
    assert proj.client_id == "client-x"
    assert proj.name == "My App"


def test_project_output_dir(tmp_path):
    """get_output_dir returns a Path within the project directory."""
    from aether_os.core.projects import ProjectManager

    pm = ProjectManager(root=tmp_path / "projects")
    pid = pm.create_project("c1", "TestProj")
    out_dir = pm.get_output_dir(pid, "p02_architecture")
    assert "p02_architecture" in str(out_dir)
    assert out_dir.exists()


def test_project_list(tmp_path):
    """list_projects returns all non-archived created projects."""
    from aether_os.core.projects import ProjectManager

    pm = ProjectManager(root=tmp_path / "projects")
    pm.create_project("c1", "Alpha")
    pm.create_project("c1", "Beta")
    projects = pm.list_projects("c1")
    assert len(projects) == 2
    names = {p.name for p in projects}
    assert "Alpha" in names and "Beta" in names


def test_project_archive(tmp_path):
    """archive_project marks project as archived."""
    from aether_os.core.projects import ProjectManager

    pm = ProjectManager(root=tmp_path / "projects")
    pid = pm.create_project("c2", "ToArchive")
    pm.archive_project(pid)
    proj = pm.get_project(pid)
    assert proj.archived is True
    # Archived project should not appear in list_projects
    active = pm.list_projects("c2")
    assert len(active) == 0


def test_project_not_found(tmp_path):
    """get_project returns None for unknown ID."""
    from aether_os.core.projects import ProjectManager

    pm = ProjectManager(root=tmp_path / "projects")
    assert pm.get_project("nonexistent-id") is None


# ═══════════════════════════════════════════════════════════════════════════════
# UsageTracker (Billing)
# ═══════════════════════════════════════════════════════════════════════════════

def _tracker_with_sqlite(tmp_path, db_name):
    """Return an isolated UsageTracker backed by a per-test SQLite file."""
    import asyncio, os
    import aether_os.core.db as _db_mod
    old_db = os.environ.get("DATABASE_URL")
    _db_mod._engine = None
    _db_mod._session_factory = None
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/{db_name}"
    from aether_os.core.db import init_db
    asyncio.run(init_db())
    from aether_os.core.billing import UsageTracker
    tracker = UsageTracker()
    return tracker, _db_mod, old_db


def _tracker_cleanup(_db_mod, old_db):
    import os
    _db_mod._engine = None
    _db_mod._session_factory = None
    if old_db is not None:
        os.environ["DATABASE_URL"] = old_db
    else:
        os.environ.pop("DATABASE_URL", None)


def test_usage_tracker_record_llm_call(tmp_path):
    """record_llm_call stores a row; get_project_cost returns a CostSummary."""
    tracker, _db_mod, old_db = _tracker_with_sqlite(tmp_path, "billing.db")
    try:
        tracker.record_llm_call(
            org_id="org-1", project_id="proj-1", phase="p01_requirements",
            model="claude-sonnet-4-6", input_tokens=500,
            output_tokens=200, cost_usd=0.003,
        )
        summary = tracker.get_project_cost("org-1", "proj-1")
        assert summary.total_cost_usd > 0
        assert summary.total_input_tokens == 500
        assert summary.total_output_tokens == 200
    finally:
        _tracker_cleanup(_db_mod, old_db)


def test_usage_tracker_record_phase_completion(tmp_path):
    """record_phase_completion stores duration in DB."""
    tracker, _db_mod, old_db = _tracker_with_sqlite(tmp_path, "billing2.db")
    try:
        tracker.record_phase_completion("proj-2", "p03_scaffolding", duration_s=12.5)
        phase_cost = tracker.get_phase_cost("org-2", "proj-2", "p03_scaffolding")
        assert phase_cost >= 0
    finally:
        _tracker_cleanup(_db_mod, old_db)


def test_usage_tracker_token_pricing(tmp_path):
    """Token pricing accumulates correctly across multiple calls."""
    tracker, _db_mod, old_db = _tracker_with_sqlite(tmp_path, "billing3.db")
    try:
        tracker.record_llm_call(
            org_id="org-3", project_id="proj-3", phase="p04a", model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=500, cost_usd=0.01,
        )
        tracker.record_llm_call(
            org_id="org-3", project_id="proj-3", phase="p06_security", model="claude-haiku-4-5",
            input_tokens=500, output_tokens=100, cost_usd=0.001,
        )
        summary = tracker.get_project_cost("org-3", "proj-3")
        assert abs(summary.total_cost_usd - 0.011) < 0.0001
        assert "p04a" in summary.phase_breakdown
        assert "p06_security" in summary.phase_breakdown
    finally:
        _tracker_cleanup(_db_mod, old_db)


def test_usage_tracker_get_phase_cost(tmp_path):
    """get_phase_cost returns only the cost for that phase."""
    tracker, _db_mod, old_db = _tracker_with_sqlite(tmp_path, "billing4.db")
    try:
        tracker.record_llm_call("org-4", "p4", "p01", "claude-sonnet-4-6", 100, 50, 0.002)
        tracker.record_llm_call("org-4", "p4", "p02", "claude-sonnet-4-6", 200, 100, 0.004)
        assert abs(tracker.get_phase_cost("org-4", "p4", "p01") - 0.002) < 0.00001
        assert abs(tracker.get_phase_cost("org-4", "p4", "p02") - 0.004) < 0.00001
    finally:
        _tracker_cleanup(_db_mod, old_db)


# ═══════════════════════════════════════════════════════════════════════════════
# FactoryPipeline (orchestrator)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_factory_pipeline_smoke(tmp_path):
    """FactoryPipeline.run() completes with mocked supervisors."""
    from aether_os.core.projects import ProjectManager
    from aether_os.phases.base import TaskResult

    mock_result = TaskResult(
        output_path=str(tmp_path),
        confidence=0.9,
        issues=[],
        metadata={"ok": True},
        success=True,
    )

    class MockSupervisor:
        async def run(self, phase_input):
            return mock_result

    with patch("aether_os.orchestrator.factory_pipeline._load_supervisor",
               return_value=MockSupervisor()), \
         patch("aether_os.core.audit.ledger.get_ledger") as mock_ledger, \
         patch("aether_os.orchestrator.factory_pipeline.get_control",
               new_callable=AsyncMock, return_value="spec_approved"), \
         patch("aether_os.orchestrator.factory_pipeline.set_control",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.update_phase_state",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.delivery_council_check",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.extract_learning",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.store_run_memory",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.embed_artifacts",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.upload_to_s3",
               new_callable=AsyncMock), \
         patch("aether_os.core.db.get_session_factory",
               return_value=_make_mock_session_factory()), \
         patch.dict("os.environ", {"PHASE_TIMEOUT_SECONDS": "10"}):

        mock_ledger.return_value = MagicMock(
            save_run=MagicMock(),
            update_run_status=MagicMock(),
            async_save_run=AsyncMock(),
            async_update_run_status=AsyncMock(),
            async_log_phase_completion=AsyncMock(),
            async_get_run_detail=AsyncMock(return_value=None),
        )

        from aether_os.orchestrator.factory_pipeline import FactoryPipeline
        fp = FactoryPipeline()
        fp.pm = ProjectManager(root=tmp_path / "projects")
        fp.ledger = mock_ledger.return_value

        with patch("aether_os.core.billing.get_usage_tracker", return_value=MagicMock()):
            result = await fp.run(
                client_id="client-test",
                raw_input="Build a task management app with user authentication",
                domain="saas",
                org_id="test-org",
            )

    assert result["status"] == "complete"
    assert result["phase_count"] >= 7
    assert "run_id" in result
    assert "project_id" in result


@pytest.mark.asyncio
async def test_factory_pipeline_start_phase(tmp_path):
    """start_phase parameter skips earlier phases."""
    from aether_os.core.projects import ProjectManager
    from aether_os.phases.base import TaskResult

    mock_result = TaskResult(
        output_path=str(tmp_path), confidence=0.9,
        issues=[], metadata={}, success=True,
    )

    class MockSupervisor:
        async def run(self, phase_input):
            return mock_result

    with patch("aether_os.orchestrator.factory_pipeline._load_supervisor",
               return_value=MockSupervisor()), \
         patch("aether_os.core.audit.ledger.get_ledger") as mock_ledger, \
         patch("aether_os.orchestrator.factory_pipeline.get_control",
               new_callable=AsyncMock, return_value="spec_approved"), \
         patch("aether_os.orchestrator.factory_pipeline.set_control",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.update_phase_state",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.delivery_council_check",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.extract_learning",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.store_run_memory",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.embed_artifacts",
               new_callable=AsyncMock), \
         patch("aether_os.orchestrator.factory_pipeline.upload_to_s3",
               new_callable=AsyncMock), \
         patch("aether_os.core.db.get_session_factory",
               return_value=_make_mock_session_factory()), \
         patch.dict("os.environ", {"PHASE_TIMEOUT_SECONDS": "10"}):

        mock_ledger.return_value = MagicMock(
            save_run=MagicMock(),
            update_run_status=MagicMock(),
            async_save_run=AsyncMock(),
            async_update_run_status=AsyncMock(),
            async_log_phase_completion=AsyncMock(),
            async_get_run_detail=AsyncMock(return_value=None),
        )

        from aether_os.orchestrator.factory_pipeline import FactoryPipeline
        fp = FactoryPipeline()
        fp.pm = ProjectManager(root=tmp_path / "projects")
        fp.ledger = mock_ledger.return_value

        with patch("aether_os.core.billing.get_usage_tracker", return_value=MagicMock()):
            result = await fp.run(
                client_id="c1",
                raw_input="Build app",
                start_phase="p08_cicd_deployment",
                org_id="test-org",
            )

    # Starting at p08 (index 20 of 39) means 19 phases run — fewer than the full 39
    assert result["phase_count"] < 39
    assert result["phase_count"] > 0


def test_factory_pipeline_phase_sequence():
    """PHASE_SEQUENCE starts with research and ends with handoff."""
    from aether_os.orchestrator.factory_pipeline import PHASE_SEQUENCE

    assert len(PHASE_SEQUENCE) >= 10
    # Pipeline starts with p00_research (pre-flight analysis)
    assert PHASE_SEQUENCE[0] == "p00_research"
    # Pipeline ends with the last known phase (p21_sre_agent added after p20_multiregion)
    assert PHASE_SEQUENCE[-1] in ("p20_multiregion", "p21_sre_agent")
    # Core phases must be present
    assert "p01_intake_requirements" in PHASE_SEQUENCE
    assert "p14_client_portal" in PHASE_SEQUENCE


def test_factory_pipeline_phase_supervisors_mapped():
    """Every phase in PHASE_SEQUENCE has an entry in PHASE_SUPERVISORS."""
    from aether_os.orchestrator.factory_pipeline import PHASE_SEQUENCE, PHASE_SUPERVISORS

    for phase in PHASE_SEQUENCE:
        assert phase in PHASE_SUPERVISORS, f"{phase} not in PHASE_SUPERVISORS"


# ═══════════════════════════════════════════════════════════════════════════════
# State Machine (26-phase)
# ═══════════════════════════════════════════════════════════════════════════════

def test_state_machine_26_phases_in_sequence():
    """PIPELINE_SEQUENCE has exactly 26 ordered states."""
    from aether_os.orchestrator.state_machine import PIPELINE_SEQUENCE, PipelineState

    assert len(PIPELINE_SEQUENCE) == 26
    assert PIPELINE_SEQUENCE[0] == PipelineState.INTAKE
    assert PIPELINE_SEQUENCE[-1] == PipelineState.CLIENT_PORTAL


def test_phase_to_state_covers_all_phases():
    """PHASE_TO_STATE maps all 26 main phases plus p15."""
    from aether_os.orchestrator.state_machine import PHASE_TO_STATE

    assert len(PHASE_TO_STATE) == 37  # 12 consolidated + 25 legacy
    assert "p00_intake" in PHASE_TO_STATE
    assert "p14_client_portal" in PHASE_TO_STATE
    assert "p15_change_requests" in PHASE_TO_STATE


def test_state_machine_transition_all_26():
    """Walk all 26 phases through the state machine without error."""
    from aether_os.orchestrator.state_machine import (
        PipelineStateMachine, PipelineState, PIPELINE_SEQUENCE
    )

    sm = PipelineStateMachine(run_id="walk-26")
    sm.transition_to(PIPELINE_SEQUENCE[0], reason="begin")
    for i in range(1, len(PIPELINE_SEQUENCE)):
        sm.transition_to(PIPELINE_SEQUENCE[i])
    sm.transition_to(PipelineState.COMPLETE)
    assert sm.current_state == PipelineState.COMPLETE
    assert sm.is_terminal()


def test_state_machine_change_request_transition():
    """CHANGE_REQUEST state can transition to any pipeline phase."""
    from aether_os.orchestrator.state_machine import (
        PipelineStateMachine, PipelineState
    )

    sm = PipelineStateMachine(run_id="cr-test")
    sm.current_state = PipelineState.CHANGE_REQUEST  # force state for test
    sm.transition_to(PipelineState.CODE_REVIEW)
    assert sm.current_state == PipelineState.CODE_REVIEW


def test_state_machine_failed_is_terminal():
    """FAILED state is terminal."""
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState

    sm = PipelineStateMachine(run_id="fail-test")
    sm.transition_to(PipelineState.INTAKE)
    sm.transition_to(PipelineState.FAILED)
    assert sm.is_terminal()
    assert not sm.is_gated()


def test_state_machine_get_resume_state():
    """get_resume_state returns last non-failure state."""
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState

    sm = PipelineStateMachine(run_id="resume-test")
    sm.transition_to(PipelineState.INTAKE)
    sm.transition_to(PipelineState.REQUIREMENTS)
    sm.transition_to(PipelineState.FAILED)
    resume = sm.get_resume_state()
    assert resume == PipelineState.REQUIREMENTS


# ═══════════════════════════════════════════════════════════════════════════════
# Client Portal Routes
# ═══════════════════════════════════════════════════════════════════════════════

def test_portal_routes_importable():
    """Client portal router can be imported."""
    from aether_os.gateway.client_portal.routes import router

    assert router is not None
    routes = [r.path for r in router.routes]
    assert any("status" in r for r in routes)
    assert any("approve" in r for r in routes)
    assert any("feedback" in r for r in routes)


def test_portal_status_project_not_found(tmp_path):
    """GET /portal/{id}/status returns 404 for unknown project."""
    from aether_os.core.projects import ProjectManager
    import aether_os.core.projects as pm_mod

    # Patch the singleton to use isolated root
    pm_mod._manager = ProjectManager(root=tmp_path / "projects")

    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from aether_os.gateway.client_portal.routes import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/portal/nonexistent-id/status")

    assert resp.status_code == 404
    pm_mod._manager = None


def test_portal_feedback_writes_file(tmp_path):
    """POST /portal/{id}/feedback writes feedback.jsonl."""
    import os
    from aether_os.core.projects import ProjectManager
    import aether_os.core.projects as pm_mod
    from aether_os.gateway.client_portal.routes import _get_portal_token

    os.environ.setdefault("AETHER_SECRET_KEY", "test-secret-key-32-chars-minimum")
    pm_mod._manager = ProjectManager(root=tmp_path / "projects")
    pid = pm_mod._manager.create_project("c1", "FeedbackTest")

    # Create portal token (writes .portal_token file into project_dir)
    portal_token = _get_portal_token(pid)
    assert portal_token, "Portal token must be generated"

    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from aether_os.gateway.client_portal.routes import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post(
        f"/portal/{pid}/feedback",
        params={"portal_token": portal_token},
        json={"feedback": "Looks great!", "phase": "p02_architecture"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Feedback recorded"
    pm_mod._manager = None
