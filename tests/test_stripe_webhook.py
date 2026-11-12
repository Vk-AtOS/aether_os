"""Stripe webhook: plan confirmed with Stripe (from the price paid, not metadata),
applied once through billing_payments, period set, no exception text echoed, and
a clean 503 when Stripe is not configured.

Stripe itself cannot be called from tests: a fake `stripe` module stands in for
the SDK (signature check + object retrieval). The router, core.billing and the
SQLite database are real.
"""
from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

import pytest

import aether_os.gateway.routers.billing_stripe_router as stripe_router

PRO, ENT = "price_pro_123", "price_ent_456"


class FakeStripe:
    """The parts of the Stripe SDK the webhook uses. Objects are plain dicts, as
    StripeObject is a dict subclass."""

    class error:
        class SignatureVerificationError(Exception):
            pass

    def __init__(self):
        self.objects = {}
        fake = self

        class Webhook:
            @staticmethod
            def construct_event(payload, sig, secret):
                if sig != "valid":
                    raise fake.error.SignatureVerificationError(f"bad sig, secret was {secret}")
                return json.loads(payload)

        class _Retrieve:
            @staticmethod
            def retrieve(obj_id, **_kw):
                return fake.objects[obj_id]

        self.Webhook = Webhook
        self.checkout = SimpleNamespace(Session=_Retrieve)
        self.Invoice = _Retrieve
        self.Subscription = _Retrieve


@pytest.fixture
def stripe_env(gw, monkeypatch):
    fake = FakeStripe()
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PRICE_PRO", PRO)
    monkeypatch.setenv("STRIPE_PRICE_ENTERPRISE", ENT)
    monkeypatch.setattr(stripe_router, "_stripe_client", lambda: fake)
    owner = gw.register("stripe")
    gw.sql("UPDATE organisations SET plan = 'trial', plan_period_end = NULL WHERE id = ?", (owner.org_id,))
    return SimpleNamespace(fake=fake, owner=owner)


def _post(gw, event, sig="valid"):
    return gw.client.post("/billing/stripe/webhook", content=json.dumps(event).encode(),
                          headers={"stripe-signature": sig})


def _checkout(org_id, price, meta_plan, sid="cs_1", paid="paid"):
    return {"id": sid, "status": "complete", "payment_status": paid, "mode": "subscription",
            "metadata": {"org_id": org_id, "plan": meta_plan}, "subscription": f"sub_{sid}",
            "amount_total": 99900, "line_items": {"data": [{"price": {"id": price}}]}}


def _org(gw, org_id):
    return gw.sql("SELECT plan, plan_period_end FROM organisations WHERE id = ?", (org_id,))[0]


def test_plan_comes_from_the_price_paid_and_a_replay_is_refused(gw, stripe_env):
    org = stripe_env.owner.org_id
    # The event body claims enterprise; Stripe says the pro price was paid.
    stripe_env.fake.objects["cs_1"] = _checkout(org, PRO, "enterprise")
    event = {"id": "evt_1", "type": "checkout.session.completed",
             "data": {"object": {"id": "cs_1", "metadata": {"org_id": org, "plan": "enterprise"}}}}

    assert _post(gw, event).status_code == 200
    plan, period_end = _org(gw, org)
    assert plan == "pro" and period_end is not None and period_end > time.time() + 29 * 86400

    assert _post(gw, event).status_code == 200            # Stripe redelivers: acknowledged, not reapplied
    assert _org(gw, org) == (plan, period_end)
    assert gw.sql("SELECT provider, order_id, plan FROM billing_payments WHERE org_id = ?", (org,)) == [
        ("stripe", "cs_1", "pro")]


def test_unpaid_or_foreign_price_checkout_changes_nothing(gw, stripe_env):
    org = stripe_env.owner.org_id
    stripe_env.fake.objects["cs_unpaid"] = _checkout(org, PRO, "pro", sid="cs_unpaid", paid="unpaid")
    stripe_env.fake.objects["cs_other"] = _checkout(org, "price_someone_elses", "pro", sid="cs_other")
    for sid in ("cs_unpaid", "cs_other"):
        resp = _post(gw, {"id": "e", "type": "checkout.session.completed", "data": {"object": {"id": sid}}})
        assert resp.status_code == 200
    assert _org(gw, org)[0] == "trial"
    assert gw.sql("SELECT count(*) FROM billing_payments WHERE org_id = ?", (org,))[0][0] == 0


def test_renewal_invoice_extends_the_period_once(gw, stripe_env):
    org = stripe_env.owner.org_id
    f = stripe_env.fake.objects
    f["cs_r"] = _checkout(org, PRO, "pro", sid="cs_r")
    f["sub_cs_r"] = {"id": "sub_cs_r", "status": "active", "metadata": {"org_id": org, "plan": "pro"}}
    f["in_2"] = {"id": "in_2", "status": "paid", "billing_reason": "subscription_cycle", "subscription": "sub_cs_r",
                 "amount_paid": 99900, "lines": {"data": [{"price": {"id": PRO}}]}}
    _post(gw, {"id": "e1", "type": "checkout.session.completed", "data": {"object": {"id": "cs_r"}}})
    first_end = _org(gw, org)[1]
    renewal = {"id": "e2", "type": "invoice.paid", "data": {"object": {"id": "in_2"}}}
    _post(gw, renewal), _post(gw, renewal)
    assert _org(gw, org)[1] == pytest.approx(first_end + 30 * 86400, abs=5)


def test_subscription_end_is_confirmed_with_stripe(gw, stripe_env):
    org = stripe_env.owner.org_id
    gw.sql("UPDATE organisations SET plan = 'pro', plan_period_end = ? WHERE id = ?", (time.time() + 86400, org))
    f = stripe_env.fake.objects
    f["sub_live"] = {"id": "sub_live", "status": "active", "metadata": {"org_id": org}}
    _post(gw, {"id": "e", "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_live"}}})
    assert _org(gw, org)[0] == "pro"                      # Stripe says it is still active
    f["sub_live"]["status"] = "canceled"
    _post(gw, {"id": "e", "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_live"}}})
    assert _org(gw, org)[0] == "free"


def test_errors_never_echo_exception_text(gw, stripe_env):
    resp = _post(gw, {"type": "x"}, sig="forged")
    assert resp.status_code == 400 and resp.json()["detail"] == "Invalid Stripe webhook"
    assert "whsec" not in resp.text
    bad = gw.client.post("/billing/stripe/webhook", content=b"not json", headers={"stripe-signature": "valid"})
    assert bad.status_code == 400 and bad.json()["detail"] == "Invalid Stripe webhook"


def test_stripe_api_failure_asks_for_redelivery(gw, stripe_env):
    resp = _post(gw, {"id": "e", "type": "checkout.session.completed", "data": {"object": {"id": "cs_missing"}}})
    assert resp.status_code == 502 and "cs_missing" not in resp.text


def test_refuses_cleanly_without_keys_or_sdk(gw, monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    assert gw.client.post("/billing/stripe/webhook", content=b"{}").status_code == 503
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert gw.client.post("/billing/stripe/webhook", content=b"{}").status_code == 503
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setitem(sys.modules, "stripe", None)       # SDK not installed
    assert gw.client.post("/billing/stripe/webhook", content=b"{}").status_code == 503
