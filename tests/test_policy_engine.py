"""The policy engine decides, deterministically and deny-by-default, and every
denial is ledgered with a machine-readable reason.

Rules are tested as pure functions; enforcement through the real gateway and
database (the pipeline never starts in these tests: each request is refused first).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import replace
from unittest.mock import patch

import pytest

from aether_os.core.policy.enforce import authorize
from aether_os.core.policy.engine import get_policy_engine
from aether_os.core.policy.rules import ACTIONS, PLAN_ENTITLEMENTS, Facts, evaluate

OK = Facts(org_exists=True, plan="pro", role="member", trial_runs_limit=3)


def _reason(action, **changes):
    return evaluate(action, replace(OK, **changes)).reason


# ── Rules (pure) ─────────────────────────────────────────────────────────────

def test_allowed_when_every_rule_holds():
    decision = evaluate("run.start", OK)
    assert decision.allowed and decision.reason == "ok"


def test_unknown_action_is_denied_even_for_a_superadmin():
    for action in ("", "run.delete_everything", "RUN.START", "pipeline_start"):
        decision = evaluate(action, replace(OK, role="superadmin"))
        assert not decision.allowed and decision.reason == "unknown_action"


def test_defaults_deny():
    assert evaluate("run.start", Facts()).reason == "org_not_found"
    assert not any(evaluate(action, Facts()).allowed for action in ACTIONS)


def test_org_must_exist_and_be_active():
    assert _reason("run.start", org_exists=False) == "org_not_found"
    assert _reason("run.start", org_deleted=True) == "org_inactive"
    assert _reason("billing.change_plan", org_deleted=True, role="owner") == "org_inactive"


@pytest.mark.parametrize("action,role,expected", [
    ("run.start", "viewer", "role_insufficient"),
    ("run.start", "member", "ok"),
    ("run.start", "api", "ok"),
    ("run.start", "", "role_unknown"),
    ("run.start", "root", "role_unknown"),
    ("billing.change_plan", "member", "role_insufficient"),
    ("billing.change_plan", "api", "role_insufficient"),
    ("billing.change_plan", "admin", "ok"),
    ("portal.token.issue", "member", "role_insufficient"),
    ("portal.token.issue", "owner", "ok"),
    ("provider.test", "member", "role_insufficient"),
    ("provider.test", "admin", "ok"),
    ("provider.test_platform", "owner", "role_insufficient"),
    ("provider.test_platform", "superadmin", "ok"),
])
def test_role_required_for_the_action(action, role, expected):
    assert _reason(action, role=role) == expected


def test_role_denial_names_the_role_needed():
    assert evaluate("provider.test_platform", replace(OK, role="owner")).detail == {"required_role": "superadmin"}


def test_plan_entitlements_and_quotas():
    assert _reason("run.start", plan="platinum") == "plan_unknown"
    assert _reason("run.start", plan="") == "plan_unknown"
    assert _reason("billing.change_plan", plan="platinum", role="owner") == "ok"   # can still fix the plan

    # trial: the org's lifetime allowance
    assert _reason("run.start", plan="trial", trial_runs_used=2) == "ok"
    assert _reason("run.start", plan="trial", trial_runs_used=3) == "trial_limit_reached"
    # free: runs per rolling period
    cap = PLAN_ENTITLEMENTS["free"].runs_per_period
    assert _reason("run.start", plan="free", runs_in_period=cap - 1) == "ok"
    denied = evaluate("run.start", replace(OK, plan="free", runs_in_period=cap))
    assert denied.reason == "quota_runs_per_period" and denied.detail == {"used": cap, "limit": cap, "period_days": 30}
    # pro: no period cap
    assert _reason("run.start", plan="pro", runs_in_period=10_000) == "ok"

    # concurrent runs, per plan
    for plan, entitlement in PLAN_ENTITLEMENTS.items():
        limit = entitlement.concurrent_runs
        assert _reason("run.start", plan=plan, active_runs=limit - 1) == "ok", plan
        assert _reason("run.start", plan=plan, active_runs=limit) == "quota_concurrent_runs", plan
    # a restart needs a slot but is not a new run
    assert _reason("run.restart", plan="trial", trial_runs_used=3) == "ok"
    assert _reason("run.restart", plan="trial", active_runs=3) == "quota_concurrent_runs"


def test_first_failing_rule_wins_in_a_fixed_order():
    everything_wrong = Facts(org_exists=True, org_deleted=True, plan="nope", role="viewer", active_runs=99)
    assert evaluate("nope", everything_wrong).reason == "unknown_action"
    assert evaluate("run.start", everything_wrong).reason == "org_inactive"
    assert evaluate("run.start", replace(everything_wrong, org_deleted=False)).reason == "role_insufficient"
    assert evaluate("run.start", replace(everything_wrong, org_deleted=False, role="member")).reason == "plan_unknown"


def test_legacy_sync_entry_point_no_longer_allows_everything():
    engine = get_policy_engine()
    assert engine.check_pipeline_start(org_id="org_1", plan="trial") == (True, "ok")
    assert engine.check_pipeline_start(org_id="", plan="trial") == (False, "org_not_found")
    assert engine.check_pipeline_start(org_id="org_1", plan="platinum") == (False, "plan_unknown")


# ── Enforcement (real gateway, database and ledger) ──────────────────────────

def _denials(gw, org_id):
    return [json.loads(m) for (m,) in gw.sql(
        "SELECT log_metadata FROM audit_log WHERE org_id = ? AND action = 'policy.denied' ORDER BY created_at",
        (org_id,))]


def _start(gw, who):
    # If policy ever lets one of these through, fail loudly instead of starting a real build.
    with patch("aether_os.orchestrator.factory_pipeline.get_factory",
               side_effect=AssertionError("policy let the build start")):
        return gw.client.post("/factory/start", headers=who.auth, json={"raw_input": "build a todo app"})


def _add_run(gw, org_id, status, started_at=None):
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) VALUES (?, ?, 'x', ?, ?, 0, 1)",
           (str(uuid.uuid4()), org_id, status, started_at or time.time()))


def test_build_start_is_refused_for_a_role_that_may_not_start_one(gw):
    owner = gw.register("polrole")
    viewer = gw.user_with_role("viewer", owner.org_id)
    resp = _start(gw, viewer)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == {"error": "role_insufficient", "action": "run.start", "required_role": "member"}
    assert _denials(gw, owner.org_id) == [
        {"action": "run.start", "reason": "role_insufficient", "role": "viewer", "required_role": "member"}]
    assert gw.sql("SELECT count(*) FROM runs WHERE org_id = ?", (owner.org_id,))[0][0] == 0


def test_build_start_quota_denials_have_reasons_and_are_ledgered(gw):
    owner = gw.register("polquota")
    org = owner.org_id

    for _ in range(3):                                             # trial: three concurrent runs
        _add_run(gw, org, "running")
    resp = _start(gw, owner)
    assert resp.status_code == 429 and resp.json()["detail"]["error"] == "quota_concurrent_runs"
    gw.sql("UPDATE runs SET status = 'completed' WHERE org_id = ?", (org,))

    gw.sql("UPDATE organisations SET trial_runs_used = trial_runs_limit WHERE id = ?", (org,))
    resp = _start(gw, owner)
    assert resp.status_code == 402
    assert resp.json()["detail"]["error"] == "trial_limit_reached" and resp.json()["detail"]["upgrade_url"] == "/pricing"

    # A lapsed paid plan is the free plan: 3 runs per 30 days (it used to be unlimited).
    gw.sql("UPDATE organisations SET plan = 'pro', plan_period_end = ? WHERE id = ?", (time.time() - 5, org))
    _add_run(gw, org, "completed"), _add_run(gw, org, "failed")
    _add_run(gw, org, "completed", started_at=time.time() - 40 * 86400)   # outside the window: not counted
    resp = _start(gw, owner)
    assert resp.status_code == 402 and resp.json()["detail"]["error"] == "quota_runs_per_period"

    gw.sql("UPDATE organisations SET plan = 'platinum', plan_period_end = NULL WHERE id = ?", (org,))
    resp = _start(gw, owner)
    assert resp.status_code == 403 and resp.json()["detail"]["error"] == "plan_unknown"

    assert [d["reason"] for d in _denials(gw, org)] == [
        "quota_concurrent_runs", "trial_limit_reached", "quota_runs_per_period", "plan_unknown"]
    # Each denial is linked into the hash chain.
    assert gw.sql("SELECT count(*) FROM audit_log WHERE org_id = ? AND action = 'policy.denied' "
                  "AND prev_hash IS NOT NULL", (org,))[0][0] == 4


def test_other_ways_to_start_a_build_go_through_the_same_policy(gw):
    owner = gw.register("polmcp")
    viewer = gw.user_with_role("viewer", owner.org_id)
    with patch("aether_os.orchestrator.factory_pipeline.get_factory",
               side_effect=AssertionError("policy let the build start")):
        mcp = gw.client.post("/mcp/start_pipeline", headers=viewer.auth, json={"requirement": "x"})
        gw.sql("UPDATE organisations SET trial_runs_used = trial_runs_limit WHERE id = ?", (owner.org_id,))
        mcp_owner = gw.client.post("/mcp/start_pipeline", headers=owner.auth, json={"requirement": "x"})
    assert mcp.status_code == 403 and mcp.json()["detail"]["error"] == "role_insufficient"
    assert mcp_owner.status_code == 402 and mcp_owner.json()["detail"]["error"] == "trial_limit_reached"

    member = gw.user_with_role("member", owner.org_id)
    resp = gw.client.post("/billing/create-order", headers=member.auth, json={"plan": "pro"})
    assert resp.status_code == 403 and resp.json()["detail"]["action"] == "billing.change_plan"


def test_authorize_allows_without_a_ledger_entry_and_denies_unknown_actions_with_one(gw):
    owner = gw.register("polauth")
    call = gw.client.portal.call

    async def ask(action, role="owner", org_id=owner.org_id):
        return await authorize(action, org_id=org_id, role=role, actor=owner.user_id)

    allowed = call(ask, "run.start")
    assert allowed.allowed and allowed.reason == "ok"
    assert _denials(gw, owner.org_id) == []

    assert call(ask, "org.transfer_ownership").reason == "unknown_action"
    assert call(ask, "run.start", "owner", "org_does_not_exist").reason == "org_not_found"
    gw.sql("UPDATE organisations SET is_deleted = 1 WHERE id = ?", (owner.org_id,))
    assert call(ask, "run.start").reason == "org_inactive"
    assert [d["reason"] for d in _denials(gw, owner.org_id)] == ["unknown_action", "org_inactive"]


def test_policy_fails_closed_when_the_facts_cannot_be_read(gw):
    owner = gw.register("polclosed")

    async def ask():
        with patch("aether_os.core.policy.enforce.gather_facts", side_effect=RuntimeError("db down")):
            return await authorize("run.start", org_id=owner.org_id, role="owner", actor=owner.user_id)

    decision = gw.client.portal.call(ask)
    assert not decision.allowed and decision.reason == "policy_unavailable"
