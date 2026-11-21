"""KAN-116 (owner decision, KAN-204): default monthly caps, org admins may only lower their cap, free models cost 0
unless priced, and prompt-injection text in requirements never reaches a model call."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from aether_os.core.llm import budget
from aether_os.core.llm.plans import PLAN_LIMITS
from aether_os.tests.injection_pack.corpus import CASES

_BLOCKED = [c for c in CASES if c[1] == "requirement" and c[3]]


def test_default_monthly_caps_follow_the_owner_decision():
    assert (PLAN_LIMITS["trial"].usd, PLAN_LIMITS["starter"].usd, PLAN_LIMITS["pro"].usd) == (5.0, 50.0, 200.0)


def test_free_models_cost_nothing_and_unknown_paid_models_do_not_slip_under_the_cap(monkeypatch):
    monkeypatch.delenv("LLM_PRICES_PER_1K", raising=False)
    assert budget.cost_usd("minimax/minimax-m2.5:free", 10_000, 10_000) == 0.0
    assert budget.cost_usd("nvidia/nemotron-super", 10_000, 10_000) == 0.0
    assert budget.cost_usd("some/unknown-paid-model", 1_000_000, 0) == pytest.approx(3.0)   # conservative default
    assert budget.cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_configured_per_1k_price_applies_to_providers_that_report_none(monkeypatch):
    monkeypatch.setenv("LLM_PRICES_PER_1K", json.dumps({"nvidia/paid-model": [0.002, 0.004]}))
    assert budget.cost_usd("nvidia/paid-model", 1000, 1000) == pytest.approx(0.006)
    monkeypatch.setenv("LLM_PRICES_PER_1K", "not json")
    assert budget.cost_usd("nvidia/paid-model", 1000, 1000) == 0.0    # bad config is logged and ignored


def test_org_admin_can_lower_but_never_raise_the_cap_and_members_cannot(gw):
    owner = gw.register("caporg")
    admin = gw.user_with_role("admin", owner.org_id)
    member = gw.user_with_role("member", owner.org_id)
    usage = gw.client.get("/settings/llm/usage", headers=admin.auth).json()
    plan_cap = PLAN_LIMITS[usage["plan"]].usd
    assert usage["cap_usd"] == plan_cap

    def put(who, v):
        return gw.client.put("/settings/llm/cap", headers=who.auth, json={"monthly_cap_usd": v})

    assert put(member, 1).status_code == 403
    assert put(admin, plan_cap + 1).status_code == 422
    assert put(admin, -1).status_code == 422
    assert put(admin, 1.5).status_code == 200
    assert gw.client.get("/settings/llm/usage", headers=admin.auth).json()["cap_usd"] == 1.5
    assert put(admin, None).status_code == 200
    assert gw.client.get("/settings/llm/usage", headers=admin.auth).json()["cap_usd"] == plan_cap


def test_global_kill_switch_stays_platform_admin_only(gw):
    owner = gw.register("killorg")
    admin = gw.user_with_role("admin", owner.org_id)
    assert gw.client.post("/admin/llm/kill-switch", headers=admin.auth, json={"on": True}).status_code == 403


@pytest.mark.parametrize("case_id,surface,text,blocked", _BLOCKED, ids=[c[0] for c in _BLOCKED])
def test_injection_in_a_requirement_is_refused_before_any_model_call(gw, case_id, surface, text, blocked):
    who = gw.register("injorg")
    with patch("aether_os.core.model_router.ModelRouter.call", new_callable=AsyncMock) as call:
        resp = gw.client.post("/factory/start", headers=who.auth, json={"raw_input": text})
    assert resp.status_code == 400
    call.assert_not_called()
