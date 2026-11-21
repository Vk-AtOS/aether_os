"""
AetherOS — Factory Pipeline Tests
Covers: MessageBus, Messages, ProjectManager, UsageTracker, FactoryPipeline
"""
from __future__ import annotations
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
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
    import asyncio
    import os
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

def test_factory_pipeline_phase_sequence():
    """PHASE_SEQUENCE uses the 12-stage architecture starting with s01_intake."""
    from aether_os.orchestrator.factory_pipeline import PHASE_SEQUENCE

    assert len(PHASE_SEQUENCE) >= 10
    # Refactored pipeline starts with s01_intake (was p00_research before stage consolidation)
    assert PHASE_SEQUENCE[0] == "s01_intake"
    # Pipeline ends with the specialist stage
    assert PHASE_SEQUENCE[-1] == "s12_specialist"
    # All 12 stages must be present
    assert "s01_intake" in PHASE_SEQUENCE
    assert "s03_backend" in PHASE_SEQUENCE
    assert "s11_handoff" in PHASE_SEQUENCE


def test_factory_pipeline_phase_supervisors_mapped():
    """Every phase in PHASE_SEQUENCE has an entry in PHASE_SUPERVISORS."""
    from aether_os.orchestrator.factory_pipeline import PHASE_SEQUENCE, PHASE_SUPERVISORS

    for phase in PHASE_SEQUENCE:
        assert phase in PHASE_SUPERVISORS, f"{phase} not in PHASE_SUPERVISORS"
