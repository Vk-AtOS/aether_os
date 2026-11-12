"""The spec review gate fails closed and every approval is ledgered.

- No decision before SPEC_REVIEW_TIMEOUT: the run is blocked (never auto-approved).
- A gate error blocks the run instead of being logged and skipped.
- Only the organisation's autonomous_mode skips review, read from the database,
  and the skip is recorded on the run (context, checkpoint, ledger, event).
- A checkpoint saved after s01 but before the gate resumes AT s01 (re-review).
- Dashboard, client-portal and Prime approvals all go through
  core.spec_approval.decide_spec, which ledgers who approved.

Real gateway / database / ledger (conftest `gw`, SQLite) plus the real gate code;
the LLM spec critique is replaced (no model is called).
"""
from __future__ import annotations

import json
import time
import uuid
from functools import partial
from unittest.mock import AsyncMock, patch

import pytest

import aether_os.orchestrator.spec_review_gate as gate_mod
from aether_os.core.errors import PipelineBlockedError
from aether_os.core.identity.portal_access import record_approval
from aether_os.core.pipeline_state import get_control, set_control
from aether_os.core.spec_approval import decide_spec
from aether_os.orchestrator.phase_selector import restore_from_checkpoint
from aether_os.orchestrator.phase_sequence import PHASE_SEQUENCE

# conftest replaces run_spec_review_gate for every test; keep the real one.
REAL_GATE = gate_mod.run_spec_review_gate


def _run(gw, org_id, checkpoint=None):
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version, checkpoint_data) "
           "VALUES (?, ?, 'factory: p', 'running', ?, 0, 1, ?)",
           (run_id, org_id, time.time(), json.dumps(checkpoint) if checkpoint else None))
    return run_id


def _ledger(gw, run_id):
    return [(a, u, json.loads(m)) for a, u, m in gw.sql(
        "SELECT action, user_id, log_metadata FROM audit_log WHERE resource_id = ? ORDER BY created_at", (run_id,))]


class Events:
    def __init__(self):
        self.items = []

    async def __call__(self, *args, **kwargs):
        self.items.append(args[-1] if args and isinstance(args[-1], dict) else args[0])


def _gate_args(run_id, ctx, events):
    return dict(run_id=run_id, accumulated_context=ctx, emit_fn=events, get_control_fn=get_control,
                set_control_fn=set_control, publish_event_fn=events)


# ── Item 4: timeout and errors fail closed ───────────────────────────────────

def test_no_decision_before_the_timeout_blocks_the_run(gw, monkeypatch):
    owner = gw.register("gatetimeout")
    run_id = _run(gw, owner.org_id)
    monkeypatch.setenv("SPEC_REVIEW_TIMEOUT", "0")
    monkeypatch.setattr(gate_mod, "_run_spec_critique", AsyncMock())
    events = Events()

    async def go():
        with pytest.raises(PipelineBlockedError, match="expired"):
            await REAL_GATE(**_gate_args(run_id, {}, events))
        return await get_control(run_id)

    assert gw.client.portal.call(go) == "spec_expired"
    timeout_evt = [e for e in events.items if e.get("type") == "spec_review_timeout"]
    assert timeout_evt and "auto-approved" not in timeout_evt[0]["message"]
    # A late approval does not count: the run is no longer waiting.
    resp = gw.client.post(f"/factory/runs/{run_id}/approve-spec", headers=owner.auth, json={})
    assert resp.status_code == 409


def test_a_stale_spec_approved_flag_is_not_taken_as_approval(gw, monkeypatch):
    owner = gw.register("gatestale")
    run_id = _run(gw, owner.org_id)
    monkeypatch.setenv("SPEC_REVIEW_TIMEOUT", "0")
    monkeypatch.setattr(gate_mod, "_run_spec_critique", AsyncMock())

    async def go():
        await set_control(run_id, "spec_approved")
        with pytest.raises(PipelineBlockedError):
            await REAL_GATE(**_gate_args(run_id, {}, Events()))

    gw.client.portal.call(go)


def test_a_gate_error_blocks_instead_of_being_skipped(gw, monkeypatch):
    owner = gw.register("gateerror")
    run_id = _run(gw, owner.org_id)

    async def broken_gate(**_kwargs):
        raise ConnectionError("redis went away")

    monkeypatch.setattr(gate_mod, "run_spec_review_gate", broken_gate)

    async def go():
        with pytest.raises(ConnectionError):
            await gate_mod.apply_spec_review(**_gate_args(run_id, {}, Events()))

    gw.client.portal.call(go)


def test_phase_hook_propagates_gate_failures(gw, monkeypatch, tmp_path):
    from aether_os.orchestrator.phase_hooks import _hook_p01_intake
    owner = gw.register("gatehook")
    run_id = _run(gw, owner.org_id)
    monkeypatch.setattr(gate_mod, "run_spec_review_gate", AsyncMock(side_effect=ValueError("boom")))

    async def go():
        with pytest.raises(ValueError):
            await _hook_p01_intake("s01_intake", tmp_path, run_id, {}, Events(), get_control, set_control, Events())

    gw.client.portal.call(go)


# ── Item 4: autonomous_mode is the only skip, and it is recorded ─────────────

def test_autonomous_org_skips_review_and_the_skip_is_recorded(gw, monkeypatch):
    owner = gw.register("gateauto")
    gw.sql("UPDATE organisations SET autonomous_mode = 1 WHERE id = ?", (owner.org_id,))
    run_id = _run(gw, owner.org_id)
    gate = AsyncMock()
    monkeypatch.setattr(gate_mod, "run_spec_review_gate", gate)
    ctx, events = {"decision_mode": "approval_required"}, Events()

    gw.client.portal.call(partial(gate_mod.apply_spec_review, **_gate_args(run_id, ctx, events)))

    gate.assert_not_awaited()
    assert ctx["spec_review"]["status"] == "skipped" and ctx["spec_review"]["reason"] == "autonomous_mode"
    assert [a for a, _, _ in _ledger(gw, run_id)] == ["run.spec_review_skipped"]
    assert any(e.get("type") == "spec_review_skipped" for e in events.items)
    ckpt = json.loads(gw.sql("SELECT checkpoint_data FROM runs WHERE id = ?", (run_id,))[0][0])
    assert ckpt["last_completed_phase"] == "s01_intake"
    assert ckpt["accumulated_context"]["spec_review"]["status"] == "skipped"


def test_context_saying_autonomous_does_not_skip_review(gw, monkeypatch):
    """Only the org setting counts — not a decision_mode value in the mutable run context."""
    owner = gw.register("gatectx")
    run_id = _run(gw, owner.org_id)
    gate = AsyncMock()
    monkeypatch.setattr(gate_mod, "run_spec_review_gate", gate)
    ctx = {"decision_mode": "autonomous"}

    gw.client.portal.call(partial(gate_mod.apply_spec_review, **_gate_args(run_id, ctx, Events())))

    gate.assert_awaited_once()
    assert ctx["spec_review"]["status"] == "approved"
    assert _ledger(gw, run_id) == []


def test_unreadable_org_setting_means_review(gw, monkeypatch):
    owner = gw.register("gateunread")
    gw.sql("UPDATE organisations SET autonomous_mode = 1 WHERE id = ?", (owner.org_id,))
    run_id = _run(gw, owner.org_id)
    gate = AsyncMock()
    monkeypatch.setattr(gate_mod, "run_spec_review_gate", gate)
    monkeypatch.setattr(gate_mod, "_org_of_run", AsyncMock(side_effect=RuntimeError("db down")))

    gw.client.portal.call(partial(gate_mod.apply_spec_review, **_gate_args(run_id, {}, Events())))
    gate.assert_awaited_once()


# ── Item 4: resume never skips an unpassed gate ──────────────────────────────

@pytest.mark.parametrize("passed,expected_first", [(False, "s01_intake"), (True, "s02_architecture")])
def test_resume_after_s01_reruns_s01_unless_the_gate_was_passed(gw, passed, expected_first):
    owner = gw.register("gateresume")
    ctx = {"raw_input": "x", **({"spec_review": {"status": "approved"}} if passed else {})}
    run_id = _run(gw, owner.org_id, {"last_completed_phase": "s01_intake", "accumulated_context": ctx})

    phases, _ = gw.client.portal.call(restore_from_checkpoint, run_id, PHASE_SEQUENCE, list(PHASE_SEQUENCE),
                                      {}, Events())
    assert phases[0] == expected_first


# ── Item 5: one ledgered approval path ───────────────────────────────────────

def test_dashboard_approval_is_ledgered_with_the_approver(gw):
    owner = gw.register("approvedash")
    run_id = _run(gw, owner.org_id)
    gw.client.portal.call(set_control, run_id, "spec_review")

    resp = gw.client.post(f"/factory/runs/{run_id}/approve-spec", headers=owner.auth, json={})
    assert resp.status_code == 200 and resp.json()["status"] == "approved"
    assert gw.client.portal.call(get_control, run_id) == "spec_approved"
    assert _ledger(gw, run_id) == [("run.spec_approved", owner.user_id, {"via": "dashboard"})]

    again = gw.client.post(f"/factory/runs/{run_id}/approve-spec", headers=owner.auth, json={})
    assert again.status_code == 409          # no longer waiting: nothing changes, nothing ledgered
    assert len(_ledger(gw, run_id)) == 1


def test_cancel_at_the_gate_is_ledgered(gw):
    owner = gw.register("approvecancel")
    run_id = _run(gw, owner.org_id)
    gw.client.portal.call(set_control, run_id, "spec_review")
    resp = gw.client.post(f"/factory/runs/{run_id}/approve-spec", headers=owner.auth, json={"action": "cancel"})
    assert resp.json()["status"] == "cancelled"
    assert gw.client.portal.call(get_control, run_id) == "cancel"
    assert [a for a, _, _ in _ledger(gw, run_id)] == ["run.spec_cancelled"]


def test_client_portal_approval_goes_through_the_same_ledgered_path(gw):
    owner = gw.register("approveportal")
    run_id = _run(gw, owner.org_id)
    gw.client.portal.call(set_control, run_id, "spec_review")
    principal = {"kind": "portal_token", "id": "tok1", "label": "Client", "org_id": owner.org_id}

    approval, created = gw.client.portal.call(record_approval, run_id, principal, True, None)
    assert created and approval["applied_to"] == "spec_review"
    actions = [(a, u, m.get("via")) for a, u, m in _ledger(gw, run_id)]
    assert actions[0] == ("run.spec_approved", "portal_token:tok1", "client_portal")


def test_decide_spec_refuses_other_orgs_and_runs_not_waiting(gw):
    """What Prime's aetheros.run_gate executor will call (see report for the one-line change)."""
    a, b = gw.register("decidea"), gw.register("decideb")
    run_id = _run(gw, a.org_id)
    call = gw.client.portal.call
    call(set_control, run_id, "spec_review")
    assert call(decide_spec, run_id, b.org_id, "prime:req1", "prime") == "not_found"
    assert call(decide_spec, run_id, a.org_id, "prime:req1", "prime") == "approved"
    assert call(decide_spec, run_id, a.org_id, "prime:req2", "prime") == "not_waiting:spec_approved"
    assert [(x, u) for x, u, _ in _ledger(gw, run_id)] == [("run.spec_approved", "prime:req1")]
