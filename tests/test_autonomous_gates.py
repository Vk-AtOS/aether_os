"""KAN-248: one resolver decides "is this run autonomous" for all four human gates.

Root cause: p00 Gate 1, the spec review and p05 Gates 3/2 each had their own check and none read the
request's mode, so a default API build (mode="autonomous") waited for a person at every gate and then
failed with a model-provider message. Here: precedence of the resolver, then each gate in autonomous
mode (no wait, auditable approved row) and supervised mode (waits; a timeout names the gate).
Waiting/Redis/DB are replaced by a fake decision engine.
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import aether_os.orchestrator.spec_review_gate as gate_mod
from aether_os.core.decisions import decision_engine as de
from aether_os.core.errors import PipelineBlockedError
from aether_os.core.stack_profiles import get_profile
from aether_os.orchestrator import events
from aether_os.orchestrator.autonomy import gate_wait_reason, halt_unless_approved, resolve_autonomy
from aether_os.phases.p00_research import multimodal_intake
from aether_os.phases.p00_research import task_agent as p00
from aether_os.phases.p05_frontend import approval_gates

REAL_GATE = gate_mod.run_spec_review_gate


class FakeEngine:
    def __init__(self, status="timeout"):
        self.status, self.requested, self.awaited = status, [], 0

    async def request_approval(self, d):
        self.requested.append(d)
        return d

    async def await_decision(self, i):
        self.awaited += 1
        return SimpleNamespace(status=self.status, human_choice=None, timeout_seconds=300)


async def _noop(*a, **k):
    return None


@pytest.fixture
def engine(monkeypatch):
    eng = FakeEngine()
    monkeypatch.setattr(de, "get_decision_engine", lambda: eng)
    monkeypatch.setattr(approval_gates, "get_decision_engine", lambda: eng)
    monkeypatch.setattr(approval_gates, "publish_event", _noop)
    monkeypatch.setattr("aether_os.core.pipeline_state.publish_event", _noop)
    monkeypatch.delenv("AUTONOMOUS_MODE", raising=False)
    return eng


@pytest.fixture
def run_id():
    tok = events.ACTIVE_RUN_ID.set("run-248")
    yield "run-248"
    events.ACTIVE_RUN_ID.reset(tok)


def _assert_auto_approved(eng, source="request"):
    assert eng.awaited == 0
    assert len(eng.requested) == 1
    row = eng.requested[0]
    assert row.status == "approved" and row.human_choice == "autonomous" and source in row.why


# ── resolver precedence ──────────────────────────────────────────────────────

def test_request_mode_beats_org_setting(monkeypatch):
    monkeypatch.delenv("AUTONOMOUS_MODE", raising=False)
    assert resolve_autonomy({"mode": "autonomous"}, org_autonomous=False) == (True, "request")
    for m in ("supervised", "manual", "guided"):
        assert resolve_autonomy({"mode": m}, org_autonomous=True) == (False, "request")
        assert resolve_autonomy({"mode": m, "decision_mode": "autonomous"}) == (False, "request")


def test_org_setting_beats_env_and_default(monkeypatch):
    monkeypatch.delenv("AUTONOMOUS_MODE", raising=False)
    assert resolve_autonomy({}, org_autonomous=True) == (True, "organisation")
    assert resolve_autonomy({"decision_mode": "autonomous"}) == (True, "organisation")
    assert resolve_autonomy({"autonomous_mode": True}) == (True, "organisation")
    # a value read from the database replaces the copy in the mutable context
    assert resolve_autonomy({"decision_mode": "autonomous"}, org_autonomous=False) == (False, "default")


def test_env_is_last_and_default_is_supervised(monkeypatch):
    monkeypatch.delenv("AUTONOMOUS_MODE", raising=False)
    assert resolve_autonomy({}) == (False, "default")
    assert resolve_autonomy(None) == (False, "default")
    monkeypatch.setenv("AUTONOMOUS_MODE", "true")
    assert resolve_autonomy({}) == (True, "env")
    assert resolve_autonomy({"mode": "supervised"}) == (False, "request")


def test_timeout_message_names_gate_not_a_model():
    msg = gate_wait_reason("Gate 1 (Design Brief)", 300)
    assert "Waited 300 s for a human approval of Gate 1 (Design Brief)" in msg
    assert "model" not in msg.lower().replace("mode=autonomous", "")
    with pytest.raises(PipelineBlockedError, match="Waited 300 s for a human approval of Gate 2"):
        halt_unless_approved(SimpleNamespace(status="timeout", timeout_seconds=300), "Gate 2")
    with pytest.raises(PipelineBlockedError, match="denied"):
        halt_unless_approved(SimpleNamespace(status="denied"), "Gate 2")


# ── p00 Gate 1 ───────────────────────────────────────────────────────────────

def _run_p00(monkeypatch, tmp_path, extra):
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
    pi = SimpleNamespace(input_data={"raw_input": "an order service", "domain": "unmapped_domain", **extra},
                         domain="unmapped_domain")
    return asyncio.run(p00.run(pi, [], Path(tmp_path) / "p00"))


def test_p00_gate1_autonomous_does_not_wait(monkeypatch, tmp_path, engine, run_id):
    _run_p00(monkeypatch, tmp_path, {"mode": "autonomous"})
    _assert_auto_approved(engine)
    assert engine.requested[0].title == "Gate 1: Design Brief"


def test_p00_gate1_supervised_waits_and_timeout_names_gate(monkeypatch, tmp_path, engine, run_id):
    with pytest.raises(PipelineBlockedError, match="human approval of Gate 1"):
        _run_p00(monkeypatch, tmp_path, {"mode": "supervised", "decision_mode": "autonomous"})
    assert engine.awaited == 1


# ── p05 Gates 3 and 2 ────────────────────────────────────────────────────────

def _gate3(**kw):
    return asyncio.run(approval_gates.run_gate3_approval(
        domain_ir=None, data={"org_id": "o"}, derive_admin_features_fn=lambda f: ["users"], **kw))


def _gate2(tmp_path, run_id, **kw):
    async def shot(frontend_dir, path):
        return False

    return asyncio.run(approval_gates.run_gate2_preview(
        run_id=run_id, frontend_dir=tmp_path, output_dir=tmp_path, domain="d", project_name="p",
        data={"org_id": "o"}, take_screenshot_fn=shot, apply_revisions_fn=_noop, **kw))


def test_p05_gate3_autonomous_records_and_continues(engine, run_id):
    assert _gate3(is_autonomous=True) == ["users"]
    _assert_auto_approved(engine)
    assert engine.requested[0].decision_type == "admin_spec_approval"


def test_p05_gate3_supervised_timeout_names_gate(engine, run_id):
    with pytest.raises(PipelineBlockedError, match="human approval of Gate 3"):
        _gate3(is_autonomous=False)
    assert engine.awaited == 1


def test_p05_gate2_autonomous_records_and_continues(engine, run_id, tmp_path):
    _gate2(tmp_path, run_id, is_autonomous=True)
    _assert_auto_approved(engine)
    assert engine.requested[0].decision_type == "portal_preview_approval"


def test_p05_gate2_supervised_timeout_names_gate(engine, run_id, tmp_path):
    with pytest.raises(PipelineBlockedError, match="human approval of Gate 2"):
        _gate2(tmp_path, run_id, is_autonomous=False)


# ── spec review gate ─────────────────────────────────────────────────────────

def _spec(monkeypatch, ctx, org_autonomous, run_gate):
    async def org(run_id):
        return "org-1", org_autonomous

    ledger = SimpleNamespace(async_log_audit_event=_noop)
    monkeypatch.setattr(gate_mod, "_org_of_run", org)
    monkeypatch.setattr(gate_mod, "get_ledger", lambda: ledger)
    monkeypatch.setattr(gate_mod, "save_checkpoint", _noop)
    monkeypatch.setattr(gate_mod, "run_spec_review_gate", run_gate)
    asyncio.run(gate_mod.apply_spec_review("r1", ctx, _noop, _noop, _noop, _noop))


def test_spec_review_request_mode_autonomous_skips_even_if_org_is_not(monkeypatch, engine):
    called = []

    async def gate(**kw):
        called.append(kw)

    ctx = {"mode": "autonomous"}
    _spec(monkeypatch, ctx, False, gate)
    assert not called
    assert ctx["spec_review"]["status"] == "skipped" and ctx["spec_review"]["source"] == "request"
    _assert_auto_approved(engine)
    assert engine.requested[0].decision_type == "spec_review_approval"


def test_spec_review_supervised_request_waits_even_if_org_is_autonomous(monkeypatch, engine):
    called = []

    async def gate(**kw):
        called.append(kw)

    ctx = {"mode": "supervised"}
    _spec(monkeypatch, ctx, True, gate)
    assert len(called) == 1 and ctx["spec_review"]["status"] == "approved"
    assert engine.requested == []


def test_spec_review_timeout_says_waited_for_human(monkeypatch):
    async def critique(ctx, run_id):
        return None

    async def get_control(run_id):
        return None

    monkeypatch.setattr(gate_mod, "_run_spec_critique", critique)
    monkeypatch.setenv("SPEC_REVIEW_TIMEOUT", "0")
    with pytest.raises(PipelineBlockedError, match=r"expired.*Waited 0 s for a human approval of the spec review"):
        asyncio.run(REAL_GATE("r1", {}, _noop, get_control, _noop, _noop))


# ── nothing stays pending when a run ends ────────────────────────────────────

def test_expire_pending_closes_only_pending_rows_of_that_run(gw):
    import uuid
    run_id, other = str(uuid.uuid4()), str(uuid.uuid4())
    for rid, st in ((run_id, "pending"), (run_id, "approved"), (other, "pending")):
        gw.sql("INSERT INTO decisions (id, run_id, org_id, decision_type, title, what, why, status, timeout_seconds, created_at) "
               "VALUES (?, ?, 'o', 't', 'T', 'w', 'y', ?, 300, ?)",
               (str(uuid.uuid4()), rid, st, "2026-11-28 00:00:00"))
    n = gw.client.portal.call(de.get_decision_engine().expire_pending, run_id, "expired")
    assert n == 1
    assert [r[0] for r in gw.sql("SELECT status FROM decisions WHERE run_id = ? ORDER BY status", (run_id,))] == [
        "approved", "expired"]
    assert gw.sql("SELECT status FROM decisions WHERE run_id = ?", (other,))[0][0] == "pending"
