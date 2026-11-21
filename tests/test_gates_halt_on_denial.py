"""KAN-97: a denial or timeout at p00 Gate 1, p05 Gate 3 and p05 Gate 2 halts the run.

(p01's entity gate is covered in test_p01_gate_engine.py, s01 Gate 1 in the s01 tests.)
Root cause: p00 only stopped on "denied" (a timeout fell through as approved); p05's gates
swallowed every exception, including the block, and carried on generating.
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from aether_os.core.decisions import decision_engine as de
from aether_os.core.errors import PipelineBlockedError
from aether_os.core.stack_profiles import get_profile
from aether_os.orchestrator import events
from aether_os.phases.p00_research import multimodal_intake
from aether_os.phases.p00_research import task_agent as p00
from aether_os.phases.p05_frontend import approval_gates


def _engine(status, choice=None):
    class Eng:
        async def request_approval(self, d):
            pass

        async def await_decision(self, i):
            return SimpleNamespace(status=status, human_choice=choice)

    return Eng()


async def _noop(*a, **k):
    return None


def _patch_gate_env(monkeypatch, status, choice=None):
    monkeypatch.setattr(approval_gates, "get_decision_engine", lambda: _engine(status, choice))
    monkeypatch.setattr(approval_gates, "publish_event", _noop)


@pytest.fixture
def run_id():
    tok = events.ACTIVE_RUN_ID.set("run-gate-test")
    yield "run-gate-test"
    events.ACTIVE_RUN_ID.reset(tok)


@pytest.mark.parametrize("status", ["denied", "timeout"])
def test_p05_gate3_halts(monkeypatch, run_id, status):
    _patch_gate_env(monkeypatch, status)
    with pytest.raises(PipelineBlockedError):
        asyncio.run(approval_gates.run_gate3_approval(
            domain_ir=None, data={}, is_autonomous=False, derive_admin_features_fn=lambda flows: ["users"]))


def test_p05_gate3_approved_with_correction(monkeypatch, run_id):
    _patch_gate_env(monkeypatch, "approved", "a, b")
    out = asyncio.run(approval_gates.run_gate3_approval(
        domain_ir=None, data={}, is_autonomous=False, derive_admin_features_fn=lambda flows: ["users"]))
    assert out == ["a", "b"]


@pytest.mark.parametrize("status", ["denied", "timeout"])
def test_p05_gate2_halts(monkeypatch, tmp_path, run_id, status):
    _patch_gate_env(monkeypatch, status)

    async def shot(frontend_dir, path):
        return False

    with pytest.raises(PipelineBlockedError):
        asyncio.run(approval_gates.run_gate2_preview(
            run_id=run_id, frontend_dir=tmp_path, output_dir=tmp_path, domain="d", project_name="p", data={},
            is_autonomous=False, take_screenshot_fn=shot, apply_revisions_fn=_noop))


@pytest.mark.parametrize("status", ["denied", "timeout"])
def test_p00_gate1_halts(monkeypatch, tmp_path, run_id, status):
    profile = get_profile("go_microservices")

    async def classify(spec, domain):
        return profile

    async def parse(data):
        return data.get("raw_input", ""), "text"

    class LLM:
        async def call_json(self, prompt, task_type="analysis"):
            return {"layout_patterns": {}, "must_have_features": []}

    monkeypatch.setattr(multimodal_intake, "detect_and_parse_input", parse)
    monkeypatch.setattr(p00, "classify_build", classify)
    monkeypatch.setattr(p00, "load_pack", lambda domain: None)
    monkeypatch.setattr(p00, "generate_business_model", _noop)
    monkeypatch.setattr(p00._llm_client, "get_llm_client", lambda: LLM())
    monkeypatch.setattr(de, "get_decision_engine", lambda: _engine(status))
    monkeypatch.setattr("aether_os.core.pipeline_state.publish_event", _noop)
    monkeypatch.delenv("AUTONOMOUS_MODE", raising=False)
    pi = SimpleNamespace(input_data={"raw_input": "an order service", "domain": "unmapped_domain"},
                         domain="unmapped_domain")
    with pytest.raises(PipelineBlockedError):
        asyncio.run(p00.run(pi, [], Path(tmp_path) / "p00"))
