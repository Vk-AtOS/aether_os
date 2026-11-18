"""
AetherOS — Pipeline and State Machine Tests

NOTE: tests in this file that import orchestrator.pipeline are testing the
LEGACY 10-phase pipeline (deprecated). New pipeline tests should use
orchestrator.factory_pipeline.FactoryPipeline instead.
"""
from __future__ import annotations
import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Suppress the DeprecationWarning emitted by the legacy orchestrator.pipeline
# module so test output stays clean. The module is intentionally deprecated
# in favour of orchestrator.factory_pipeline.
warnings.filterwarnings(
    "ignore",
    message="orchestrator.pipeline is deprecated",
    category=DeprecationWarning,
)
# Suppress ResourceWarning and RuntimeWarning (unclosed socket/loop) that
# originate from the async test harness teardown, not from production code.
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", message="coroutine .* was never awaited", category=RuntimeWarning)


# ── Execution Context ─────────────────────────────────────────────────────────

def test_execution_context_defaults():
    from aether_os.orchestrator.context import ExecutionContext
    ctx = ExecutionContext(requirement="Build a REST API")
    assert ctx.requirement == "Build a REST API"
    assert ctx.language == "python"
    assert ctx.run_id != ""
    assert ctx.errors == []


def test_execution_context_add_error():
    from aether_os.orchestrator.context import ExecutionContext
    ctx = ExecutionContext(requirement="test")
    ctx.add_error("Something failed")
    assert len(ctx.errors) == 1
    assert "Something failed" in ctx.errors[0]


def test_execution_context_record_phase():
    from aether_os.orchestrator.context import ExecutionContext, PhaseOutput
    ctx = ExecutionContext(requirement="test")
    phase = PhaseOutput(phase_id="p01", phase_name="requirements", passed=True, confidence=0.9)
    ctx.record_phase(phase)
    assert len(ctx.phase_outputs) == 1
    assert ctx.get_phase_output("p01") is not None


def test_execution_context_summary():
    from aether_os.orchestrator.context import ExecutionContext
    ctx = ExecutionContext(requirement="Build something amazing")
    summary = ctx.summary()
    assert "run_id" in summary
    assert summary["requirement"].startswith("Build")


def test_execution_context_serializable():
    from aether_os.orchestrator.context import ExecutionContext
    import json
    ctx = ExecutionContext(requirement="test", language="python", project_name="proj")
    # Should be JSON serializable via pydantic
    json_str = ctx.model_dump_json()
    data = json.loads(json_str)
    assert data["requirement"] == "test"


# ── State Machine ─────────────────────────────────────────────────────────────

def test_full_pipeline_sequence():
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState, PIPELINE_SEQUENCE
    sm = PipelineStateMachine(run_id="full-test")

    # Walk through all 26 phases in order
    sm.transition_to(PIPELINE_SEQUENCE[0])  # IDLE → INTAKE
    for i in range(1, len(PIPELINE_SEQUENCE)):
        sm.transition_to(PIPELINE_SEQUENCE[i])

    sm.transition_to(PipelineState.COMPLETE)
    assert sm.is_terminal()
    assert sm.current_state == PipelineState.COMPLETE


def test_state_machine_gated_human():
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState
    sm = PipelineStateMachine(run_id="gated-test")
    sm.transition_to(PipelineState.REQUIREMENTS)
    sm.transition_to(PipelineState.GATED_HUMAN, reason="human review needed")
    assert sm.is_gated()
    # Can resume from gated state
    sm.transition_to(PipelineState.REQUIREMENTS)
    assert sm.current_state == PipelineState.REQUIREMENTS


def test_state_machine_history_recorded():
    from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState
    sm = PipelineStateMachine(run_id="history-test")
    sm.transition_to(PipelineState.REQUIREMENTS, reason="start", metadata={"user": "test"})
    sm.transition_to(PipelineState.ARCHITECTURE, reason="done")

    assert len(sm.history) == 2
    assert sm.history[0]["from_state"] == "IDLE"
    assert sm.history[0]["to_state"] == "REQUIREMENTS"
    assert sm.history[0]["metadata"]["user"] == "test"


def test_state_machine_summary():
    from aether_os.orchestrator.state_machine import PipelineStateMachine
    sm = PipelineStateMachine(run_id="summary-test")
    summary = sm.summary()
    assert summary["run_id"] == "summary-test"
    assert summary["current_state"] == "IDLE"


# ── Phase Router ──────────────────────────────────────────────────────────────

def test_router_security_routes_to_codegen():
    from aether_os.orchestrator.routing.router import route_failure
    from aether_os.orchestrator.state_machine import PipelineState
    target = route_failure("security_critical", PipelineState.SECURITY)
    assert target == PipelineState.BACKEND_CODEGEN


def test_router_unknown_failure_returns_none():
    from aether_os.orchestrator.routing.router import route_failure
    from aether_os.orchestrator.state_machine import PipelineState
    target = route_failure("unknown_failure_xyz", PipelineState.SECURITY)
    assert target is None


# ── Pipeline (mocked LLM) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore:orchestrator.pipeline is deprecated:DeprecationWarning")
async def test_pipeline_run_complete(tmp_path):
    """Test full pipeline run with mocked LLM responses."""
    import os
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    old_primary = os.environ.get("PRIMARY_LLM")
    os.environ["PRIMARY_LLM"] = "anthropic"

    # Clear any real cloud LLM credentials loaded from .env so only the
    # ollama mock is used.  load_dotenv() runs at gateway.api import time
    # (triggered by test_multi_tenancy.py's module-level import during
    # pytest collection) and can set OPENROUTER_API_KEY / BEDROCK_ENABLED,
    # causing real API calls that return dict-format findings instead of the
    # mock string responses.
    old_openrouter_key = os.environ.pop("OPENROUTER_API_KEY", None)
    old_bedrock_enabled = os.environ.pop("BEDROCK_ENABLED", None)
    old_bedrock_heavy = os.environ.pop("BEDROCK_MODEL_HEAVY", None)
    old_bedrock_light = os.environ.pop("BEDROCK_MODEL_LIGHT", None)
    old_google_key = os.environ.pop("GOOGLE_API_KEY", None)

    # Reset singletons
    import aether_os.core.llm.client as llm_mod
    llm_mod._instance = None
    import aether_os.core.audit.ledger as ledger_mod
    old_db = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    ledger_mod.DecisionLedger._instance = None

    mock_code = """
def hello(name: str) -> str:
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(hello("World"))
"""

    try:
        responses = [
            "Goals: Build a hello world app\nConstraints: None\nStack: Python",
            "Architecture: Simple script with one function",
            '{"files": ["main.py"], "structure": "simple"}',
            mock_code,
            '{"findings": [], "overall_quality": 9}',
            '{"issues": [], "score": 100}',
            "def test_hello(): assert hello('World') == 'Hello, World!'",
            "# README\nThis is a hello world app",
            mock_code,  # extra for any retries
        ]
        call_count_holder = [0]

        async def _mock_call_ollama(prompt, task_type, model):
            idx = call_count_holder[0]
            call_count_holder[0] += 1
            return responses[min(idx, len(responses) - 1)]

        with patch("aether_os.core.llm.client._call_ollama_with_model", side_effect=_mock_call_ollama), \
             patch("httpx.AsyncClient.get") as mock_get:

            # Mock Ollama tags check
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"models": [{"name": "qwen2.5-coder:3b"}]}
            mock_get.return_value = mock_resp

            # NOTE: Pipeline is the legacy 10-phase orchestrator. New pipeline
            # code should use FactoryPipeline from orchestrator.factory_pipeline.
            # The DeprecationWarning is suppressed by filterwarnings at module top.
            from aether_os.orchestrator.pipeline import Pipeline
            pipeline = Pipeline()
            result = await pipeline.run(
                requirement="Build a hello world function",
                project_name="hello_test",
                language="python",
                output_dir=str(tmp_path / "output"),
            )

        assert result["status"] == "complete"
        assert result["run_id"] != ""
        assert len(result["phases"]) > 0

        # BUG 9 FIX: verify output was written to disk
        assert result.get("output_dir") is not None
        output_dir = Path(result["output_dir"])
        assert output_dir.exists()
        assert (output_dir / "main.py").exists()

    finally:
        del os.environ["ANTHROPIC_API_KEY"]
        if old_primary:
            os.environ["PRIMARY_LLM"] = old_primary
        elif "PRIMARY_LLM" in os.environ:
            del os.environ["PRIMARY_LLM"]

        # Restore any cloud credentials we cleared
        for _key, _val in [
            ("OPENROUTER_API_KEY", old_openrouter_key),
            ("BEDROCK_ENABLED", old_bedrock_enabled),
            ("BEDROCK_MODEL_HEAVY", old_bedrock_heavy),
            ("BEDROCK_MODEL_LIGHT", old_bedrock_light),
            ("GOOGLE_API_KEY", old_google_key),
        ]:
            if _val is not None:
                os.environ[_key] = _val
            else:
                os.environ.pop(_key, None)

        if old_db:
            os.environ["DATABASE_URL"] = old_db
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
        llm_mod._instance = None
        ledger_mod.DecisionLedger._instance = None


# ── write_output_to_disk ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_output_to_disk(tmp_path):
    """Test Bug 9 fix: generated code is written to disk."""
    from aether_os.orchestrator.context import ExecutionContext
    # write_output_to_disk lives in pipeline_helpers; importing from the legacy
    # pipeline module still works but emits a DeprecationWarning.
    from aether_os.orchestrator.pipeline_helpers import write_output_to_disk

    ctx = ExecutionContext(
        requirement="test",
        project_name="testproj",
        generated_code="print('hello')",
        docs="# README",
        test_results={"test_code": "def test_foo(): pass", "passed": True},
        output_dir=str(tmp_path / "output"),
    )

    output_path = await write_output_to_disk(ctx)
    out_dir = Path(output_path)

    assert out_dir.exists()
    assert (out_dir / "main.py").exists()
    assert (out_dir / "README.md").exists()
    assert (out_dir / "tests" / "test_main.py").exists()
    assert (out_dir / "main.py").read_text() == "print('hello')"
