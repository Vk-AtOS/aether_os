"""KAN-110: Stripe checkout stores the customer, cancel really cancels at Stripe, members cannot bill."""
from types import SimpleNamespace

import pytest

import aether_os.gateway.routers.billing_router as billing
import aether_os.gateway.routers.billing_stripe_router as sr


class FakeStripe:
    def __init__(self):
        self.created, self.cancelled, self.checkout_kwargs, self.fail_cancel = [], [], {}, False
        fake = self

        class Customer:
            @staticmethod
            def create(**kw):
                fake.created.append(kw)
                return SimpleNamespace(id="cus_123")

        class Session:
            @staticmethod
            def create(**kw):
                fake.checkout_kwargs = kw
                return SimpleNamespace(id="cs_1", url="https://checkout.example/x")

        class Subscription:
            @staticmethod
            def list(customer, **kw):
                return SimpleNamespace(data=[SimpleNamespace(id="sub_1")] if customer == "cus_123" else [])

            @staticmethod
            def cancel(sid):
                if fake.fail_cancel:
                    raise RuntimeError("stripe down")
                fake.cancelled.append(sid)

        self.Customer, self.checkout = Customer, SimpleNamespace(Session=Session)
        self.Subscription = Subscription
        self.api_key = None


@pytest.fixture
def fake(monkeypatch):
    f = FakeStripe()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setattr(sr, "_stripe_client", lambda: f)
    monkeypatch.setattr(billing, "_stripe", f)
    return f


def test_checkout_stores_customer_and_cancel_cancels_at_stripe(gw, fake):
    org = gw.register("stripeorg")
    r = gw.client.post("/billing/stripe/checkout", headers=org.auth, json={"plan": "pro"})
    assert r.status_code == 200, r.text
    assert fake.checkout_kwargs["customer"] == "cus_123" and "customer_email" not in fake.checkout_kwargs
    assert gw.sql("SELECT stripe_customer_id FROM organisations WHERE id=?", (org.org_id,))[0][0] == "cus_123"
    gw.sql("UPDATE organisations SET plan='pro' WHERE id=?", (org.org_id,))
    assert gw.client.post("/billing/cancel", headers=org.auth).status_code == 200
    assert fake.cancelled == ["sub_1"]


def test_cancel_failing_at_stripe_keeps_plan_and_reports_error(gw, fake):
    org = gw.register("stripefail")
    gw.sql("UPDATE organisations SET plan='pro', stripe_customer_id='cus_123' WHERE id=?", (org.org_id,))
    fake.fail_cancel = True
    r = gw.client.post("/billing/cancel", headers=org.auth)
    assert r.status_code == 502
    assert gw.sql("SELECT plan FROM organisations WHERE id=?", (org.org_id,))[0][0] == "pro"


def test_members_cannot_use_stripe_routes(gw, fake):
    org = gw.register("stripemember")
    member = gw.user_with_role("member", org.org_id)
    assert gw.client.post("/billing/stripe/checkout", headers=member.auth, json={"plan": "pro"}).status_code == 403
    assert gw.client.get("/billing/stripe/portal", headers=member.auth).status_code == 403
