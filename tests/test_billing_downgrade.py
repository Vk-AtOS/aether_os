"""KAN-155: cancel and downgrade are one path for Razorpay and Stripe orgs: provider first, then the org."""
import time

import pytest

import aether_os.gateway.routers.billing_router as billing


class Sub(dict):
    id = "sub_1"


class FakeStripe:
    def __init__(self):
        self.modified, self.cancelled, self.searched, self.fail = [], [], [], False
        fake = self

        class Subscription:
            @staticmethod
            def list(customer, **kw):
                return type("L", (), {"data": [Sub(items={"data": [{"id": "si_1"}]})] if customer == "cus_1" else []})

            @staticmethod
            def search(query):
                fake.searched.append(query)
                return type("L", (), {"data": []})

            @staticmethod
            def modify(sid, **kw):
                if fake.fail:
                    raise RuntimeError("stripe down")
                fake.modified.append((sid, kw))

            @staticmethod
            def cancel(sid):
                if fake.fail:
                    raise RuntimeError("stripe down")
                fake.cancelled.append(sid)

        self.Subscription = Subscription
        self.api_key = None


@pytest.fixture
def fake(monkeypatch):
    f = FakeStripe()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setattr(billing, "_stripe", f)
    return f


def _org(gw, plan, customer=None):
    org = gw.register("down")
    gw.sql("UPDATE organisations SET plan=?, plan_period_end=?, stripe_customer_id=? WHERE id=?",
           (plan, time.time() + 86400 * 10, customer, org.org_id))
    return org


def _row(gw, org):
    return gw.sql("SELECT plan, plan_period_end FROM organisations WHERE id=?", (org.org_id,))[0]


def test_stripe_org_downgrade_to_pro_switches_the_subscription_price_and_keeps_the_period(gw, fake):
    org = _org(gw, "enterprise", "cus_1")
    r = gw.client.post("/billing/downgrade", headers=org.auth, json={"target_plan": "pro"})
    assert r.status_code == 200, r.text
    sid, kw = fake.modified[0]
    assert sid == "sub_1" and kw["items"] == [{"id": "si_1", "price": "price_pro"}] and kw["proration_behavior"] == "none"
    assert fake.cancelled == []
    plan, end = _row(gw, org)
    assert plan == "pro" and end and r.json()["period_end"] == pytest.approx(end)
    assert gw.client.get("/billing/status", headers=org.auth).json()["plan"] == "pro"


def test_stripe_org_downgrade_to_free_cancels_at_stripe_and_ends_the_period(gw, fake):
    org = _org(gw, "pro", "cus_1")
    assert gw.client.post("/billing/downgrade", headers=org.auth, json={"target_plan": "free"}).status_code == 200
    assert fake.cancelled == ["sub_1"]
    assert _row(gw, org) == ("free", None)


def test_stripe_failure_changes_nothing_for_downgrade_and_cancel(gw, fake):
    org = _org(gw, "enterprise", "cus_1")
    fake.fail = True
    assert gw.client.post("/billing/downgrade", headers=org.auth, json={"target_plan": "pro"}).status_code == 502
    assert gw.client.post("/billing/cancel", headers=org.auth).status_code == 502
    assert _row(gw, org)[0] == "enterprise"


def test_razorpay_org_downgrade_is_local_and_never_an_upgrade(gw, fake):
    org = _org(gw, "enterprise")
    assert gw.client.post("/billing/downgrade", headers=org.auth, json={"target_plan": "enterprise"}).status_code == 403
    assert gw.client.post("/billing/downgrade", headers=org.auth, json={"target_plan": "gold"}).status_code == 400
    assert gw.client.post("/billing/downgrade", headers=org.auth, json={"target_plan": "pro"}).status_code == 200
    assert fake.modified == [] and fake.searched == [] and _row(gw, org)[0] == "pro"


def test_non_admin_cannot_downgrade_or_cancel(gw, fake):
    org = _org(gw, "pro")
    member = gw.user_with_role("member", org.org_id)
    assert gw.client.post("/billing/downgrade", headers=member.auth, json={"target_plan": "free"}).status_code == 403
    assert gw.client.post("/billing/cancel", headers=member.auth).status_code == 403
    assert _row(gw, org)[0] == "pro"
