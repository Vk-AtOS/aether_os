"""Every path that starts a build goes through one admission gate (policy check +
atomic trial consume); stage ids for rerun/branch and stage toggles are validated;
PolicyAgent fails closed.

Real gateway, real SQLite database and ledger (conftest `gw`). get_factory is
replaced so no build ever starts; nothing else is mocked.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aether_os.agents.base import AgentContext
from aether_os.agents.implementations import PolicyAgent
from aether_os.core.policy import enforce as enforce_mod
from aether_os.core.policy.enforce import admit_new_run
from aether_os.core.policy.rules import PLATFORM_CONCURRENT_RUNS

NO_BUILD = AssertionError("admission let the build start")


def _run(gw, org_id, status="completed"):
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, raw_input, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'factory: todo', 'todo', ?, ?, 0, 1)", (run_id, org_id, status, time.time()))
    return run_id


def _profile(gw, org_id):
    pid = str(uuid.uuid4())
    gw.sql("INSERT INTO marketplace_profiles (id, org_id, name, base_domain, profile_yaml, is_published, "
           "usage_count, price_usd, created_at) VALUES (?, ?, 'P', 'general', 'x: 1', 1, 0, 0, '2026-01-01 00:00:00')", (pid, org_id))
    return pid


def _trial_used(gw, org_id):
    return gw.sql("SELECT trial_runs_used FROM organisations WHERE id = ?", (org_id,))[0][0]


def _every_start_path(gw, who, parent, profile):
    """status code of each build-starting route for `who`, with no build allowed to start."""
    c, h = gw.client, who.auth
    with patch("aether_os.orchestrator.factory_pipeline.get_factory", side_effect=NO_BUILD), \
         patch("aether_os.gateway.services.run_start.get_factory", side_effect=NO_BUILD), \
         patch("aether_os.core.services.pipeline_service.PipelineService.start_run",
               AsyncMock(side_effect=NO_BUILD)):
        return {
            "start": c.post("/factory/start", headers=h, json={"raw_input": "build a todo app"}),
            "rerun": c.post(f"/factory/runs/{parent}/rerun", headers=h, json={"from_phase": "s03_backend"}),
            "branch": c.post(f"/factory/runs/{parent}/branch", headers=h, json={"branch_phase": "s03_backend"}),
            "mcp": c.post("/mcp/start_pipeline", headers=h, json={"requirement": "todo"}),
            "marketplace": c.post(f"/marketplace/install/{profile}", headers=h),
        }


def test_trial_org_at_its_limit_is_refused_on_every_build_path(gw):
    owner = gw.register("admitlimit")
    parent, profile = _run(gw, owner.org_id), _profile(gw, owner.org_id)
    gw.sql("UPDATE organisations SET plan = 'trial', trial_runs_used = trial_runs_limit WHERE id = ?",
           (owner.org_id,))
    used = _trial_used(gw, owner.org_id)
    for path, resp in _every_start_path(gw, owner, parent, profile).items():
        assert resp.status_code == 402, (path, resp.text)
        assert resp.json()["detail"]["error"] == "trial_limit_reached", path
    assert _trial_used(gw, owner.org_id) == used


def test_each_build_path_consumes_one_trial_run(gw):
    """MCP and marketplace used to check the policy but never consume the allowance."""
    owner = gw.register("admitconsume")
    parent, profile = _run(gw, owner.org_id), _profile(gw, owner.org_id)
    gw.sql("UPDATE organisations SET plan = 'trial', trial_runs_used = 0, trial_runs_limit = 100 WHERE id = ?",
           (owner.org_id,))
    fake = MagicMock()
    fake.run = AsyncMock(return_value={})
    with patch("aether_os.orchestrator.factory_pipeline.get_factory", return_value=fake), \
         patch("aether_os.gateway.services.run_start.get_factory", return_value=fake), \
         patch("aether_os.core.services.pipeline_service.PipelineService.start_run",
               AsyncMock(return_value={"run_id": "x"})):
        h = owner.auth
        for method, url, body in [
            ("post", "/mcp/start_pipeline", {"requirement": "todo"}),
            ("post", f"/marketplace/install/{profile}", None),
            ("post", f"/factory/runs/{parent}/rerun", {"from_phase": "s03_backend"}),
            ("post", f"/factory/runs/{parent}/branch", {"branch_phase": "s04_frontend"}),
        ]:
            before = _trial_used(gw, owner.org_id)
            resp = getattr(gw.client, method)(url, headers=h, json=body)
            assert resp.status_code == 200, (url, resp.text)
            assert _trial_used(gw, owner.org_id) == before + 1, url


def test_two_concurrent_starts_at_limit_minus_one_let_exactly_one_through(gw):
    owner = gw.register("admitrace")
    gw.sql("UPDATE organisations SET plan = 'trial', trial_runs_limit = 3, trial_runs_used = 2 WHERE id = ?",
           (owner.org_id,))

    async def both():
        return await asyncio.gather(*(admit_new_run(org_id=owner.org_id, role="owner", actor=owner.user_id)
                                      for _ in range(2)))

    decisions = gw.client.portal.call(both)
    assert sorted(d.allowed for d in decisions) == [False, True]
    assert [d.reason for d in decisions if not d.allowed] == ["trial_limit_reached"]
    assert _trial_used(gw, owner.org_id) == 3


def test_platform_capacity_is_a_policy_rule_and_fails_closed(gw):
    """The old _check_db_run_limits is gone; the policy engine owns platform capacity."""
    owner = gw.register("admitcap")
    gw.sql("UPDATE organisations SET plan = 'pro', plan_period_end = NULL WHERE id = ?", (owner.org_id,))
    other = gw.register("admitcapother")
    filler = [_run(gw, other.org_id, "running") for _ in range(PLATFORM_CONCURRENT_RUNS)]
    try:
        with patch("aether_os.orchestrator.factory_pipeline.get_factory", side_effect=NO_BUILD):
            resp = gw.client.post("/factory/start", headers=owner.auth, json={"raw_input": "todo"})
        assert resp.status_code == 503 and resp.json()["detail"]["error"] == "platform_at_capacity"
    finally:
        for run_id in filler:
            gw.sql("UPDATE runs SET status = 'completed' WHERE id = ?", (run_id,))

    async def broken_facts(*_a, **_k):
        raise RuntimeError("database is down")

    with patch.object(enforce_mod, "gather_facts", broken_facts), \
         patch("aether_os.orchestrator.factory_pipeline.get_factory", side_effect=NO_BUILD):
        resp = gw.client.post("/factory/start", headers=owner.auth, json={"raw_input": "todo"})
    assert resp.status_code == 503 and resp.json()["detail"]["error"] == "policy_unavailable"


def test_consume_failure_denies(gw):
    owner = gw.register("admitconsumefail")
    gw.sql("UPDATE organisations SET plan = 'trial', trial_runs_used = 0 WHERE id = ?", (owner.org_id,))

    async def broken(*_a, **_k):
        raise RuntimeError("lost the connection")

    async def ask():
        with patch.object(enforce_mod, "_consume_trial_run", broken):
            return await admit_new_run(org_id=owner.org_id, role="owner")

    decision = gw.client.portal.call(ask)
    assert not decision.allowed and decision.reason == "policy_unavailable"


# ── Item 15: rerun / branch stage ids ────────────────────────────────────────

def test_rerun_and_branch_reject_unknown_stage_ids_before_anything_is_created(gw):
    owner = gw.register("forkstage")
    parent = _run(gw, owner.org_id)
    used = _trial_used(gw, owner.org_id)
    runs = gw.sql("SELECT count(*) FROM runs WHERE org_id = ?", (owner.org_id,))[0][0]
    with patch("aether_os.gateway.services.run_start.get_factory", side_effect=NO_BUILD):
        rerun = gw.client.post(f"/factory/runs/{parent}/rerun", headers=owner.auth, json={"from_phase": "p99_nope"})
        branch = gw.client.post(f"/factory/runs/{parent}/branch", headers=owner.auth,
                                json={"branch_phase": "s13_magic"})
    assert rerun.status_code == 422 and "p99_nope" in rerun.json()["detail"]
    assert branch.status_code == 422 and "s13_magic" in branch.json()["detail"]
    assert _trial_used(gw, owner.org_id) == used
    assert gw.sql("SELECT count(*) FROM runs WHERE org_id = ?", (owner.org_id,))[0][0] == runs


def test_rerun_accepts_a_legacy_phase_id_and_starts_at_its_stage(gw):
    owner = gw.register("forklegacy")
    parent = _run(gw, owner.org_id)
    fake = MagicMock()
    fake.run = AsyncMock(return_value={})
    with patch("aether_os.gateway.services.run_start.get_factory", return_value=fake):
        resp = gw.client.post(f"/factory/runs/{parent}/rerun", headers=owner.auth,
                              json={"from_phase": "p04_backend"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["from_phase"] == "s03_backend"
    assert fake.run.await_args.kwargs["start_phase"] == "s03_backend"


def test_rerun_of_another_orgs_run_is_404(gw):
    a, b = gw.register("forka"), gw.register("forkb")
    parent = _run(gw, b.org_id)
    resp = gw.client.post(f"/factory/runs/{parent}/rerun", headers=a.auth, json={"from_phase": "s03_backend"})
    assert resp.status_code == 404


# ── Item 14: stage toggles ───────────────────────────────────────────────────

def test_stage_toggle_rejects_unknown_and_mandatory_stages(gw):
    owner = gw.register("toggles")
    unknown = gw.client.post("/settings/phases/p05_frontend/config", headers=owner.auth,
                             json={"enabled": False, "priority": "normal"})
    mandatory = gw.client.post("/settings/phases/s01_intake/config", headers=owner.auth,
                               json={"enabled": False, "priority": "normal"})
    optional = gw.client.post("/settings/phases/s08_observability/config", headers=owner.auth,
                              json={"enabled": False, "priority": "normal"})
    enable_mandatory = gw.client.post("/settings/phases/s05_quality/config", headers=owner.auth,
                                      json={"enabled": True, "priority": "normal"})
    assert unknown.status_code == 422 and "Unknown stage" in unknown.json()["detail"]
    assert mandatory.status_code == 422 and "cannot be disabled" in mandatory.json()["detail"]
    assert optional.status_code == 200 and enable_mandatory.status_code == 200
    saved = gw.sql("SELECT phase_name, enabled FROM phase_configs WHERE org_id = ? ORDER BY phase_name",
                   (owner.org_id,))
    assert saved == [("s05_quality", 1), ("s08_observability", 0)]


# ── Item 7: PolicyAgent ──────────────────────────────────────────────────────

def test_policy_agent_blocks_on_error_and_on_denial(gw):
    owner = gw.register("polagent")
    agent = PolicyAgent()
    call = gw.client.portal.call

    def ctx(**meta):
        return AgentContext(project_path=".", user_id=owner.user_id, metadata=meta)

    async def broken(*_a, **_k):
        raise RuntimeError("policy engine crashed")

    async def run_with_broken_engine():
        with patch("aether_os.agents.implementations.authorize", broken):
            return await agent.run(ctx(org_id=owner.org_id, role="owner"))

    assert call(run_with_broken_engine).status == "blocked"
    assert call(agent.run, ctx(org_id=owner.org_id)).status == "blocked"            # no role: denied
    assert call(agent.run, ctx(org_id=owner.org_id, role="viewer")).status == "blocked"
    assert call(agent.run, ctx(org_id=owner.org_id, role="member")).status == "ok"


def test_agents_route_takes_role_from_the_token_not_the_body(gw):
    owner = gw.register("polagentroute")
    viewer = gw.user_with_role("viewer", owner.org_id)
    resp = gw.client.post("/agents/policy_agent/run", headers=viewer.auth,
                          json={"metadata": {"role": "owner", "org_id": "someone_else"}})
    # The route asks the policy engine (agent.run) before dispatching any agent; the body's claims are ignored.
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "role_insufficient"
    denial = gw.sql("SELECT log_metadata FROM audit_log WHERE org_id = ? AND action = 'policy.denied'",
                    (owner.org_id,))
    assert json.loads(denial[-1][0])["role"] == "viewer"
