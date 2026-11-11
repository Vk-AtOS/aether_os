"""A paid order upgrades an org once. Presented again it is refused, including when
two presentations race. Razorpay's API is the only stand-in; verify_payment, the
webhook and apply_paid_order run for real against a real (SQLite) database."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from aether_os.gateway.routers import billing_router
from aether_os.tests.gateway_env import ENV, gateway_env


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with gateway_env(tmp_path_factory.mktemp("billing")) as e:
        yield e


def _plan(env):
    return env.sql("SELECT plan FROM organisations WHERE id = ?", (env.org_id,))[0][0]


def _signed(order_id, payment_id):
    sig = hmac.new(ENV["RAZORPAY_KEY_SECRET"].encode(),
                   f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return {"razorpay_order_id": order_id, "razorpay_payment_id": payment_id, "razorpay_signature": sig}


def _paid_order(env, monkeypatch, plan="pro", amount=99900):
    order = {"amount": amount, "status": "paid", "notes": {"org_id": env.org_id, "plan": plan}}
    monkeypatch.setattr(billing_router, "_razorpay_client",
                        lambda: SimpleNamespace(order=SimpleNamespace(fetch=lambda _oid: order)))


def _webhook(env, order_id, payment_id, plan="pro"):
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": payment_id, "order_id": order_id, "amount": 99900,
        "notes": {"org_id": env.org_id, "plan": plan}}}}}).encode()
    sig = hmac.new(ENV["RAZORPAY_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    return env.client.post("/billing/webhook", content=body,
                           headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig})


def test_paid_order_cannot_be_replayed_after_cancel(env, monkeypatch):
    _paid_order(env, monkeypatch)
    first = env.client.post("/billing/verify-payment", json=_signed("order_A", "pay_A"), headers=env.auth)
    assert first.status_code == 200, first.text
    assert _plan(env) == "pro"
    assert env.sql("SELECT provider, org_id, plan, amount FROM billing_payments WHERE order_id = 'order_A'") \
        == [("razorpay", env.org_id, "pro", 99900)]

    assert env.client.post("/billing/cancel", headers=env.auth).status_code == 200
    assert _plan(env) == "free"

    replay = env.client.post("/billing/verify-payment", json=_signed("order_A", "pay_A"), headers=env.auth)
    assert replay.status_code == 409, replay.text
    assert _plan(env) == "free"
    assert env.sql("SELECT count(*) FROM billing_payments WHERE order_id = 'order_A'")[0][0] == 1


def test_webhook_redelivery_is_acknowledged_but_not_reapplied(env):
    assert _webhook(env, "order_W", "pay_W").json() == {"received": True}
    assert _plan(env) == "pro"
    env.sql("UPDATE organisations SET plan = 'free' WHERE id = ?", (env.org_id,))

    again = _webhook(env, "order_W", "pay_W")
    assert again.status_code == 200 and again.json() == {"received": True}
    assert _plan(env) == "free"


def test_order_already_applied_by_webhook_is_refused_at_verify(env, monkeypatch):
    _paid_order(env, monkeypatch)
    env.sql("UPDATE organisations SET plan = 'free' WHERE id = ?", (env.org_id,))
    resp = env.client.post("/billing/verify-payment", json=_signed("order_W", "pay_other"), headers=env.auth)
    assert resp.status_code == 409
    assert _plan(env) == "free"


def test_webhook_without_ids_is_not_applied(env):
    env.sql("UPDATE organisations SET plan = 'free' WHERE id = ?", (env.org_id,))
    assert _webhook(env, "", "").status_code == 200
    assert _plan(env) == "free"


def test_racing_presentations_apply_exactly_once(env):
    """The unique constraint, not a read-then-write check, decides the winner."""
    from aether_os.core.billing.payments import apply_paid_order

    async def race():
        return await asyncio.gather(*(
            apply_paid_order("razorpay", "order_R", f"pay_R{i % 2}", env.org_id, "pro", 99900)
            for i in range(12)))

    results = env.client.portal.call(race)
    assert sum(results) == 1
    assert env.sql("SELECT count(*) FROM billing_payments WHERE order_id = 'order_R'")[0][0] == 1
