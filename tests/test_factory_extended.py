"""
AetherOS — Extended factory tests for the orchestrator and portal.

These tests continue from test_factory.py and cover:

  6.  FactoryPipeline orchestrator
  7.  State Machine (26-phase)
  8.  Client Portal Routes
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

    # No credentials: refused before the project is looked up, so the id is not confirmed either way.
    assert resp.status_code == 401
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
