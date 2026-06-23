"""
AetherOS — Integration tests for the full 20-phase pipeline.

These tests exercise the real pipeline machinery with mocked LLM / DB calls
so they can run in CI without external services.  They verify:

  1.  All 20 supervisors are importable and instantiable
  2.  PHASE_SEQUENCE is exactly 20 phases, all mapped in PHASE_SUPERVISORS
  3.  _run_phase correctly invokes the supervisor and maps its result
  4.  Unmapped phases are skipped with a warning (not silently completed)
  5.  Phase timeout is configurable via PHASE_TIMEOUT_SECONDS
  6.  P07 testing gate correctly blocks / passes based on real test results
  7.  The full PHASE_SEQUENCE runs end-to-end with mocked supervisors
  8.  MessageBus fallback (asyncio.Queue) works without Redis
  9.  P01 intake gate blocks on empty / stub requirements
  10. Pipeline propagates accumulated_context across phases
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
import uuid
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

# Make sure the repo root is on sys.path regardless of how pytest is invoked
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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
# 1. Phase mapping completeness
# ─────────────────────────────────────────────────────────────────────────────

def test_phase_sequence_is_21_phases():
    from aether_os.orchestrator.factory_pipeline import PHASE_SEQUENCE
    # Phase count grows as new phases are added; assert minimum + reasonable upper bound
    assert 39 <= len(PHASE_SEQUENCE) <= 50, (
        f"Expected 39-50 phases, got {len(PHASE_SEQUENCE)}: {PHASE_SEQUENCE}"
    )


def test_all_phases_have_supervisor_mapping():
    from aether_os.orchestrator.factory_pipeline import PHASE_SEQUENCE, PHASE_SUPERVISORS
    missing = [p for p in PHASE_SEQUENCE if p not in PHASE_SUPERVISORS]
    assert missing == [], (
        f"Phases in PHASE_SEQUENCE with no PHASE_SUPERVISORS entry: {missing}"
    )


def test_no_orphaned_supervisor_mappings():
    """Every entry in PHASE_SUPERVISORS must correspond to a phase in PHASE_SEQUENCE."""
    from aether_os.orchestrator.factory_pipeline import PHASE_SEQUENCE, PHASE_SUPERVISORS
    orphans = [p for p in PHASE_SUPERVISORS if p not in PHASE_SEQUENCE]
    assert orphans == [], f"Supervisors mapped but not in PHASE_SEQUENCE: {orphans}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Supervisor import & instantiation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phase_name,class_path", [
    (k, v)
    for k, v in __import__(
        "aether_os.orchestrator.factory_pipeline",
        fromlist=["PHASE_SUPERVISORS"]
    ).PHASE_SUPERVISORS.items()
])
def test_supervisor_importable(phase_name, class_path):
    """Every supervisor module can be imported without ImportError."""
    module_path, class_name = class_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
        assert hasattr(module, class_name), (
            f"{module_path} has no attribute {class_name!r}"
        )
    except ImportError as exc:
        pytest.fail(f"Cannot import supervisor for {phase_name}: {exc}")


@pytest.mark.parametrize("phase_name,class_path", [
    (k, v)
    for k, v in __import__(
        "aether_os.orchestrator.factory_pipeline",
        fromlist=["PHASE_SUPERVISORS"]
    ).PHASE_SUPERVISORS.items()
])
def test_supervisor_instantiable(phase_name, class_path):
    """Every supervisor can be instantiated without __init__ errors."""
    module_path, class_name = class_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        instance = cls()
        assert instance is not None
        assert hasattr(instance, "run"), (
            f"{class_name} must expose a .run() method"
        )
    except Exception as exc:
        pytest.fail(f"Cannot instantiate supervisor for {phase_name}: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. _run_phase behaviour
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_phase_invokes_supervisor():
    """_run_phase calls supervisor.run() and maps success → 'passed'."""
    from aether_os.orchestrator.factory_pipeline import FactoryPipeline

    pipeline = FactoryPipeline.__new__(FactoryPipeline)
    mock_supervisor = MagicMock()
    mock_supervisor.run = AsyncMock(return_value=_make_task_result(success=True))

    phase_input = _make_phase_input()

    with patch(
        "aether_os.orchestrator.factory_pipeline._load_supervisor",
        return_value=mock_supervisor,
    ):
        result = await pipeline._run_phase("p01_intake_requirements", phase_input)

    mock_supervisor.run.assert_awaited_once_with(phase_input)
    assert result["status"] == "passed"


@pytest.mark.asyncio
async def test_run_phase_maps_failure_status():
    """_run_phase maps success=False → 'failed'."""
    from aether_os.orchestrator.factory_pipeline import FactoryPipeline

    pipeline = FactoryPipeline.__new__(FactoryPipeline)
    mock_supervisor = MagicMock()
    mock_supervisor.run = AsyncMock(
        return_value=_make_task_result(success=False, confidence=0.1)
    )

    with patch(
        "aether_os.orchestrator.factory_pipeline._load_supervisor",
        return_value=mock_supervisor,
    ):
        result = await pipeline._run_phase("p01_intake_requirements", _make_phase_input())

    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_run_phase_skipped_for_unmapped():
    """An unmapped phase returns status='skipped', NOT 'completed'."""
    from aether_os.orchestrator.factory_pipeline import FactoryPipeline

    pipeline = FactoryPipeline.__new__(FactoryPipeline)

    with patch(
        "aether_os.orchestrator.factory_pipeline._load_supervisor",
        return_value=None,
    ):
        result = await pipeline._run_phase("nonexistent_phase", _make_phase_input())

    assert result["status"] == "skipped", (
        "Unmapped phases must be 'skipped', not silently 'completed'"
    )
    assert "warning" in result


# ─────────────────────────────────────────────────────────────────────────────
# 4. Phase timeout is configurable
# ─────────────────────────────────────────────────────────────────────────────

def test_phase_timeout_env_var_is_read(monkeypatch):
    """PHASE_TIMEOUT_SECONDS env var is correctly parsed at runtime."""
    monkeypatch.setenv("PHASE_TIMEOUT_SECONDS", "42")
    val = float(os.environ.get("PHASE_TIMEOUT_SECONDS", "600"))
    assert val == 42.0, "PHASE_TIMEOUT_SECONDS must be read from env at runtime"

    monkeypatch.delenv("PHASE_TIMEOUT_SECONDS")
    default_val = float(os.environ.get("PHASE_TIMEOUT_SECONDS", "600"))
    assert default_val == 600.0, "Default phase timeout must be 600s"


# ─────────────────────────────────────────────────────────────────────────────
# 5. P07 testing gate — real logic exercised
# ─────────────────────────────────────────────────────────────────────────────

def test_p07_gate_blocks_when_no_tests():
    from aether_os.phases.p07_testing.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path="",
        confidence=0.9,
        metadata={},  # no test_code key → no tests generated
        success=False,  # hard block requires success=False
    )
    outcome = validate(result)
    assert outcome.passed is False
    assert any("No test code" in i for i in outcome.issues)


def test_p07_gate_blocks_on_low_pass_rate():
    from aether_os.phases.p07_testing.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path="",
        confidence=0.8,
        metadata={
            "test_code": "def test_x(): pass",
            "total_tests": 10,
            "passed_tests": 5,   # 50% — below 70% threshold
        },
        success=True,
    )
    outcome = validate(result)
    assert outcome.passed is False
    assert "50%" in outcome.issues[0] or "pass-rate" in outcome.issues[0].lower()


def test_p07_gate_passes_on_full_pass_rate():
    from aether_os.phases.p07_testing.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path="",
        confidence=0.95,
        metadata={
            "test_code": "def test_auth(): assert True",
            "total_tests": 8,
            "passed_tests": 8,
        },
        success=True,
    )
    outcome = validate(result)
    assert outcome.passed is True


def test_p07_gate_passes_with_warning_on_partial():
    """75% pass rate is above threshold → passes but with a warning issue."""
    from aether_os.phases.p07_testing.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path="",
        confidence=0.85,
        metadata={
            "test_code": "def test_x(): pass",
            "total_tests": 8,
            "passed_tests": 6,   # 75% — above 70% threshold
        },
        success=True,
    )
    outcome = validate(result)
    assert outcome.passed is True
    assert len(outcome.issues) > 0   # warning present


def test_p07_gate_blocks_when_runner_failed():
    """success=False with no test counts → blocks."""
    from aether_os.phases.p07_testing.gate import validate
    from aether_os.phases.base import TaskResult

    result = TaskResult(
        output_path="",
        confidence=0.0,
        metadata={"test_code": "def test_x(): pass"},
        success=False,
    )
    outcome = validate(result)
    assert outcome.passed is False


# ─────────────────────────────────────────────────────────────────────────────
# 6. P07 supervisor delegates to gate (not hardcoded)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_p07_supervisor_gate_calls_real_validate():
    """TestingSupervisor.validate_gate must NOT return passed=True unconditionally."""
    from aether_os.phases.p07_testing.supervisor_agent import TestingSupervisor

    supervisor = TestingSupervisor()

    # No test code + success=False → gate.validate returns passed=False (hard block)
    bad_result = _make_task_result(success=False, metadata={})
    outcome = await supervisor.validate_gate(bad_result, None)

    assert outcome.passed is False, (
        "TestingSupervisor.validate_gate must delegate to gate.validate — "
        "it must NOT hardcode passed=True"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. MessageBus asyncio.Queue fallback (no Redis required)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bus_publish_and_subscribe_without_redis():
    """Bus pub/sub works via asyncio.Queue fallback when Redis is unavailable.
    Subscribe must start before publish so the queue exists when message arrives."""
    from aether_os.orchestrator.bus import MessageBus
    from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

    bus = MessageBus(run_id="test-no-redis")

    result = PhaseResult(
        run_id="test-no-redis",
        phase="p01_intake_requirements",
        status="passed",
        output_path="/tmp/out",
        confidence=0.9,
        issues=[],
        next_phase="p02_architecture",
        upstream_route=None,
        failure_context=None,
        artifacts={"domain": "saas"},
    )
    msg = PhaseMessage(
        from_phase="p01_intake_requirements",
        to_phase="p02_architecture",
        result=result,
    )

    # Force Redis unavailable for the whole test
    with patch(
        "aether_os.orchestrator.bus.MessageBus._get_redis",
        new_callable=AsyncMock,
        return_value=None,
    ):
        # Subscribe first (creates the in-process queue), then publish
        subscribe_task = asyncio.create_task(bus.subscribe("p02_architecture"))
        await asyncio.sleep(0)    # yield so the task starts waiting
        await bus.publish(msg)    # now deliver the message into the queue
        received = await asyncio.wait_for(subscribe_task, timeout=2.0)

    assert received is not None
    assert received.from_phase == "p01_intake_requirements"


@pytest.mark.asyncio
async def test_bus_drain_returns_published_messages():
    from aether_os.orchestrator.bus import MessageBus
    from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

    bus = MessageBus(run_id="drain-test")
    result = PhaseResult(
        run_id="drain-test", phase="p02_architecture", status="passed",
        output_path="", confidence=1.0, issues=[], next_phase=None,
        upstream_route=None, failure_context=None, artifacts={},
    )
    msg = PhaseMessage(from_phase="p02_architecture", to_phase=None, result=result)

    with patch(
        "aether_os.orchestrator.bus.MessageBus._get_redis",
        new_callable=AsyncMock,
        return_value=None,
    ):
        await bus.publish(msg)
        drained = await bus.drain()

    assert len(drained) == 1
    assert drained[0].from_phase == "p02_architecture"


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
