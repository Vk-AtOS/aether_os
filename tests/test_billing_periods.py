"""A payment buys a 30-day period. Paying again while it runs extends it from its
end; when it ends the org is on the free plan — decided when the plan is read,
with no background job — and start, renewal and expiry are ledgered.

Razorpay's API is the only stand-in; verify_payment, the webhook, apply_paid_order
and the request dependency run for real against a real (SQLite) database.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest

from aether_os.core.billing.payments import PERIOD_SECONDS, effective_plan, next_period_end
from aether_os.gateway.routers import billing_router
from aether_os.tests.gateway_env import ENV, gateway_env

DAY = 86400


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with gateway_env(tmp_path_factory.mktemp("periods")) as e:
        yield e


@pytest.fixture(autouse=True)
def _razorpay(env, monkeypatch):
    def fetch(order_id):
        plan = "enterprise" if order_id.startswith("ent") else "pro"
        return {"amount": billing_router.RAZORPAY_PLANS[plan]["amount"], "status": "paid",
                "notes": {"org_id": env.org_id, "plan": plan}}
    monkeypatch.setattr(billing_router, "_razorpay_client",
                        lambda: SimpleNamespace(order=SimpleNamespace(fetch=fetch)))


def _org(env):
    return env.sql("SELECT plan, plan_period_end FROM organisations WHERE id = ?", (env.org_id,))[0]


def _verify(env, order_id, payment_id):
    sig = hmac.new(ENV["RAZORPAY_KEY_SECRET"].encode(), f"{order_id}|{payment_id}".encode(),
                   hashlib.sha256).hexdigest()
    return env.client.post("/billing/verify-payment", headers=env.auth, json={
        "razorpay_order_id": order_id, "razorpay_payment_id": payment_id, "razorpay_signature": sig})


def _webhook(env, order_id, payment_id):
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": payment_id, "order_id": order_id}}}}).encode()
    sig = hmac.new(ENV["RAZORPAY_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    return env.client.post("/billing/webhook", content=body,
                           headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig})


def _status(env):
    resp = env.client.get("/billing/status", headers=env.auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ledger(env, action):
    return [json.loads(m) for (m,) in env.sql(
        "SELECT log_metadata FROM audit_log WHERE org_id = ? AND action = ? ORDER BY created_at",
        (env.org_id, action))]


def test_rules_are_pure_and_deterministic():
    now = 1_000_000.0
    assert effective_plan("pro", now + 1, now) == "pro"
    assert effective_plan("pro", now, now) == "free"            # the end instant is already outside the period
    assert effective_plan("enterprise", now - 1, now) == "free"
    assert effective_plan("pro", None, now) == "pro"            # no period on record: not ours to expire
    assert effective_plan("trial", now - 1, now) == "trial"     # unpaid plans do not lapse into free
    assert next_period_end("trial", None, "pro", now) == now + PERIOD_SECONDS
    assert next_period_end("pro", now + 5 * DAY, "pro", now) == now + 5 * DAY + PERIOD_SECONDS
    assert next_period_end("pro", now - 5 * DAY, "pro", now) == now + PERIOD_SECONDS      # lapsed: from payment
    assert next_period_end("pro", now + 5 * DAY, "enterprise", now) == now + PERIOD_SECONDS  # other plan: from payment


def test_payment_starts_a_30_day_period_and_status_reports_it(env):
    assert _status(env) == {"plan": "trial", "period_end": None, "period_active": False,
                            "days_remaining": None, "period_days": 30}
    before = time.time()
    resp = _verify(env, "order_1", "pay_1")
    assert resp.status_code == 200, resp.text
    plan, period_end = _org(env)
    assert plan == "pro" and before + 30 * DAY <= period_end <= time.time() + 30 * DAY
    assert resp.json()["period_end"] == period_end

    assert _status(env) == {"plan": "pro", "period_end": period_end, "period_active": True,
                            "days_remaining": 29, "period_days": 30}
    started = _ledger(env, "billing.period_started")
    assert len(started) == 1 and started[0]["order_id"] == "order_1" and started[0]["period_end"] == period_end


def test_paying_again_while_active_extends_from_the_current_end_via_webhook_too(env):
    _, first_end = _org(env)
    assert _webhook(env, "order_2", "pay_2").status_code == 200
    plan, second_end = _org(env)
    assert plan == "pro" and second_end == first_end + 30 * DAY
    renewed = _ledger(env, "billing.period_renewed")
    assert len(renewed) == 1 and renewed[0]["previous_period_end"] == first_end

    # Redelivery of the same event extends nothing.
    assert _webhook(env, "order_2", "pay_2").status_code == 200
    assert _org(env)[1] == second_end


def test_when_the_period_ends_the_org_is_free_at_the_next_read_and_it_is_ledgered_once(env):
    ended = time.time() - 60
    env.sql("UPDATE organisations SET plan_period_end = ? WHERE id = ?", (ended, env.org_id))
    assert _org(env)[0] == "pro"                                   # nothing has run: no background job

    status = _status(env)                                          # any authenticated request settles it
    assert status["plan"] == "free" and status["period_active"] is False
    assert status["period_end"] == ended and status["days_remaining"] == 0
    assert _org(env) == ("free", ended)
    for _ in range(3):
        _status(env)
    expired = _ledger(env, "billing.period_expired")
    assert expired == [{"previous_plan": "pro", "period_end": ended}]


def test_the_request_sees_the_plan_in_force_not_the_plan_in_its_token(env):
    """The JWT still says plan=trial from sign-up; policy and plan checks must use the org row."""
    from aether_os.gateway.dependencies import get_current_user

    seen = {}

    async def probe(user=__import__("fastapi").Depends(get_current_user)):
        seen["plan"] = user["plan"]
        return {}

    env.client.app.add_api_route("/_test/plan-probe", probe)
    assert env.claims["plan"] == "trial"
    env.sql("UPDATE organisations SET plan = 'enterprise', plan_period_end = ? WHERE id = ?",
            (time.time() + DAY, env.org_id))
    env.client.get("/_test/plan-probe", headers=env.auth)
    assert seen["plan"] == "enterprise"
    env.sql("UPDATE organisations SET plan_period_end = ? WHERE id = ?", (time.time() - 1, env.org_id))
    env.client.get("/_test/plan-probe", headers=env.auth)
    assert seen["plan"] == "free"


def test_paying_after_a_lapse_starts_from_payment_time(env):
    assert _org(env)[0] == "free"
    before = time.time()
    assert _verify(env, "order_3", "pay_3").status_code == 200
    plan, period_end = _org(env)
    assert plan == "pro" and before + 30 * DAY <= period_end <= time.time() + 30 * DAY


def test_a_different_plan_starts_its_own_period_from_payment_time(env):
    before = time.time()
    assert _verify(env, "ent_order_4", "pay_4").status_code == 200
    plan, period_end = _org(env)
    assert plan == "enterprise" and before + 30 * DAY <= period_end <= time.time() + 30 * DAY


def test_cancel_ends_the_period_record(env):
    assert env.client.post("/billing/cancel", headers=env.auth).status_code == 200
    assert _org(env) == ("free", None)
    assert _status(env)["plan"] == "free"
