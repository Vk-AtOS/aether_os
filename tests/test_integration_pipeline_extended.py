"""
AetherOS — Extended integration tests for the full 20-phase pipeline.

These tests continue from test_integration_pipeline.py and cover:

  8.  The full PHASE_SEQUENCE runs end-to-end with mocked supervisors
  9.  Pipeline accumulated_context propagation
  10. GateOutcome data class
"""
from __future__ import annotations

import sys
import tempfile
import uuid
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

# Make sure the repo root is on sys.path regardless of how pytest is invoked
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def _make_task_result(success=True, confidence=0.9, metadata=None, issues=None):
    from aether_os.phases.base import TaskResult
    return TaskResult(
        output_path=tempfile.mkdtemp(),
        confidence=confidence,
        success=success,
        metadata=metadata or {},
        issues=issues or [],
    )


def _make_phase_input(run_id=None, project_id=None, domain="general", tmp_dir=None):
    from aether_os.orchestrator.messages import PhaseInput
    rid = run_id or str(uuid.uuid4())
    return PhaseInput(
        run_id=rid,
        project_id=project_id or rid,
        phase="p01_intake_requirements",
        input_data={"raw_input": "Build a SaaS app", "domain": domain},
        output_dir=str(tmp_dir or tempfile.mkdtemp()),
        domain=domain,
        client_id="test@example.com",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 8. Full PHASE_SEQUENCE end-to-end with mocked supervisors
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_pipeline_runs_all_20_phases(tmp_path, monkeypatch):
    """
    Runs the complete PHASE_SEQUENCE with every supervisor mocked.
    Verifies:
      - All 21 phases are attempted
      - Accumulated context is passed to each phase
      - The pipeline returns a final result dict with run_id and status
    """
    import uuid as _uuid

    monkeypatch.setenv("PHASE_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("AETHER_SECRET_KEY", "test-secret-key-32-chars-minimum!!")

    phases_executed = []

    def _mock_load_supervisor(phase_name):
        sup = MagicMock()

        async def _run(phase_input):
            phases_executed.append(phase_name)
            return _make_task_result(
                success=True,
                metadata={
                    # Provide enough metadata for each phase type
                    "test_code": "def test_pass(): assert True",
                    "total_tests": 3,
                    "passed_tests": 3,
                    "domain": phase_input.domain,
                },
            )

        sup.run = _run
        return sup

    run_id = str(_uuid.uuid4())

    # Patch all external dependencies
    with (
        patch("aether_os.orchestrator.factory_pipeline._load_supervisor",
              side_effect=_mock_load_supervisor),
        patch("aether_os.orchestrator.factory_pipeline.get_ledger") as mock_ledger,
        patch("aether_os.orchestrator.factory_pipeline.get_project_manager") as mock_pm,
        patch("aether_os.core.pipeline_state.get_redis", new_callable=AsyncMock,
              return_value=None),
        patch("aether_os.orchestrator.factory_pipeline.publish_event",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.emit",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.get_control",
              new_callable=AsyncMock, return_value="spec_approved"),
        patch("aether_os.orchestrator.factory_pipeline.set_control",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.update_phase_state",
              new_callable=AsyncMock),
        patch("aether_os.core.db_utils.create_run", new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.delivery_council_check",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.extract_learning",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.store_run_memory",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.embed_artifacts",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.upload_to_s3",
              new_callable=AsyncMock),
        patch("aether_os.core.db.get_session_factory",
              return_value=_make_mock_session_factory()),
    ):
        # Mock ledger — ALL async methods must be AsyncMock
        mock_ledger_inst = MagicMock()
        mock_ledger_inst.create_run = AsyncMock(return_value=run_id)
        mock_ledger_inst.async_save_run = AsyncMock()
        mock_ledger_inst.async_update_run_status = AsyncMock()
        mock_ledger_inst.async_log_phase_completion = AsyncMock()
        mock_ledger_inst.async_get_run_detail = AsyncMock(return_value=None)
        mock_ledger.return_value = mock_ledger_inst

        # Mock project manager
        mock_pm_inst = MagicMock()
        mock_pm_inst.create_project = MagicMock(return_value=run_id)
        mock_pm_inst.get_project_dir = MagicMock(return_value=tmp_path)
        mock_pm_inst.get_output_dir = MagicMock(return_value=tmp_path)
        mock_pm_inst.update_project = MagicMock()
        mock_pm.return_value = mock_pm_inst

        from aether_os.orchestrator.factory_pipeline import FactoryPipeline, PHASE_SEQUENCE
        pipeline = FactoryPipeline()

        result = await pipeline._execute_pipeline(
            client_id="test@example.com",
            raw_input="Build a multi-tenant SaaS CRM",
            domain="saas_multitenant",
            project_name="test-saas-crm",
            run_id=run_id,
            org_id="test-org",
        )

    assert result is not None, "Pipeline must return a result dict"
    assert "run_id" in result or "status" in result, (
        f"Result missing run_id/status: {result}"
    )

    # All 21 phases must have been attempted
    from aether_os.orchestrator.factory_pipeline import PHASE_SEQUENCE
    for phase in PHASE_SEQUENCE:
        assert phase in phases_executed, (
            f"Phase {phase!r} was never executed — pipeline skipped it"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 9. Accumulated context propagation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_accumulated_context_contains_domain(tmp_path, monkeypatch):
    """
    The accumulated_context dict passed to every phase must carry
    the domain and raw_input set by the caller.
    """
    monkeypatch.setenv("PHASE_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("SPEC_REVIEW_TIMEOUT", "0")
    monkeypatch.setenv("AETHER_SECRET_KEY", "test-secret-key-32-chars-minimum!!")

    received_contexts = []

    def _mock_load_supervisor(phase_name):
        sup = MagicMock()

        async def _run(phase_input):
            received_contexts.append(dict(phase_input.input_data))
            return _make_task_result(
                success=True,
                metadata={"test_code": "pass", "total_tests": 1, "passed_tests": 1},
            )

        sup.run = _run
        return sup

    import uuid as _uuid
    run_id = str(_uuid.uuid4())

    with (
        patch("aether_os.orchestrator.factory_pipeline._load_supervisor",
              side_effect=_mock_load_supervisor),
        patch("aether_os.orchestrator.factory_pipeline.get_ledger") as mock_ledger,
        patch("aether_os.orchestrator.factory_pipeline.get_project_manager") as mock_pm,
        patch("aether_os.core.pipeline_state.get_redis", new_callable=AsyncMock,
              return_value=None),
        patch("aether_os.orchestrator.factory_pipeline.publish_event",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.emit",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.get_control",
              new_callable=AsyncMock, return_value="spec_approved"),
        patch("aether_os.orchestrator.factory_pipeline.set_control",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.update_phase_state",
              new_callable=AsyncMock),
        patch("aether_os.core.db_utils.create_run", new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.delivery_council_check",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.extract_learning",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.store_run_memory",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.embed_artifacts",
              new_callable=AsyncMock),
        patch("aether_os.orchestrator.factory_pipeline.upload_to_s3",
              new_callable=AsyncMock),
        patch("aether_os.core.db.get_session_factory",
              return_value=_make_mock_session_factory()),
    ):
        mock_ledger_inst = MagicMock()
        mock_ledger_inst.create_run = AsyncMock(return_value=run_id)
        mock_ledger_inst.async_save_run = AsyncMock()
        mock_ledger_inst.async_update_run_status = AsyncMock()
        mock_ledger_inst.async_log_phase_completion = AsyncMock()
        mock_ledger_inst.async_get_run_detail = AsyncMock(return_value=None)
        mock_ledger.return_value = mock_ledger_inst

        mock_pm_inst = MagicMock()
        mock_pm_inst.create_project = MagicMock(return_value=run_id)
        mock_pm_inst.get_project_dir = MagicMock(return_value=tmp_path)
        mock_pm_inst.get_output_dir = MagicMock(return_value=tmp_path)
        mock_pm_inst.update_project = MagicMock()
        mock_pm.return_value = mock_pm_inst

        from aether_os.orchestrator.factory_pipeline import FactoryPipeline
        pipeline = FactoryPipeline()
        await pipeline._execute_pipeline(
            client_id="test@example.com",
            raw_input="Build a fintech payment gateway",
            domain="fintech",
            project_name="test-fintech",
            run_id=run_id,
            org_id="test-org",
        )

    assert len(received_contexts) > 0, "No phases were called"
    # Every phase receives the domain
    for ctx in received_contexts:
        assert ctx.get("domain") == "fintech", (
            f"Phase received wrong domain in context: {ctx.get('domain')!r}"
        )
    # raw_input must propagate
    assert any("fintech" in ctx.get("raw_input", "") for ctx in received_contexts)


# ─────────────────────────────────────────────────────────────────────────────
# 10. GateOutcome data class
# ─────────────────────────────────────────────────────────────────────────────

def test_gate_outcome_defaults():
    from aether_os.phases.base import GateOutcome
    g = GateOutcome(passed=True, confidence=0.95)
    assert g.passed is True
    assert g.confidence == 0.95
    assert g.issues == []


def test_gate_outcome_with_issues():
    from aether_os.phases.base import GateOutcome
    g = GateOutcome(passed=False, confidence=0.1, issues=["Test coverage below threshold"])
    assert g.passed is False
    assert len(g.issues) == 1
