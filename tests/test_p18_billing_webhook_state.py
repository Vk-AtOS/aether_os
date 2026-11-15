"""KAN-196: the generated Stripe webhook changes tenant billing state (it used to only log)."""
import asyncio
import importlib.util
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aether_os.phases.p18_billing_metering.metering_generator import generate_stripe_webhook_handler


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    src = generate_stripe_webhook_handler("demo")
    assert "TODO" not in src
    f = tmp_path / "billing_webhook.py"
    f.write_text(src)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    spec = importlib.util.spec_from_file_location("billing_webhook_gen", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # signature checking is Stripe's code; here the payload is the event
    monkeypatch.setattr(m.stripe.Webhook, "construct_event", lambda payload, sig, secret: json.loads(payload))
    app = FastAPI()
    app.include_router(m.router)

    @app.get("/data")
    async def data(t: str = m.Depends(m.require_active_billing(lambda: "t1"))):
        return {"tenant": t}

    return m, TestClient(app)


def _send(client, etype, **obj):
    r = client.post("/billing/stripe/webhook", headers={"Stripe-Signature": "x"},
                    json={"type": etype, "data": {"object": obj}})
    assert r.status_code == 200, r.text


def test_billing_events_change_tenant_state(app_mod):
    m, c = app_mod
    status = lambda: asyncio.run(m.tenant_billing_status("t1"))  # noqa: E731
    assert status() == "none" and c.get("/data").status_code == 200

    _send(c, "invoice.payment_failed", customer="cus_1")  # unknown customer: nothing invented
    assert status() == "none"

    _send(c, "checkout.session.completed", customer="cus_1", client_reference_id="t1")
    assert status() == "active"
    assert asyncio.run(m._get_tenant_by_customer("cus_1")) == "t1"

    _send(c, "invoice.payment_failed", customer="cus_1")
    assert status() == "past_due" and c.get("/data").status_code == 200  # inside grace

    _send(c, "invoice.payment_succeeded", customer="cus_1")
    assert status() == "active"

    _send(c, "customer.subscription.deleted", customer="cus_1")
    assert status() == "suspended" and c.get("/data").status_code == 402
    _send(c, "invoice.payment_succeeded", customer="cus_1")  # late invoice must not revive it
    assert status() == "suspended"


def test_grace_period_expires_and_retries_do_not_extend_it(app_mod, monkeypatch):
    m, c = app_mod
    _send(c, "checkout.session.completed", customer="cus_2", client_reference_id="t1")
    _send(c, "invoice.payment_failed", customer="cus_2")
    real = m.time.time
    monkeypatch.setattr(m.time, "time", lambda: real() + m.GRACE_SECONDS - 60)
    _send(c, "invoice.payment_failed", customer="cus_2")  # Stripe retry near the end of grace
    monkeypatch.setattr(m.time, "time", lambda: real() + m.GRACE_SECONDS + 60)
    assert asyncio.run(m.tenant_billing_status("t1")) == "restricted"
    assert c.get("/data").status_code == 402


def test_webhook_refused_without_signing_secret(app_mod, monkeypatch):
    _, c = app_mod
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
    r = c.post("/billing/stripe/webhook", headers={"Stripe-Signature": "x"},
               json={"type": "customer.subscription.deleted", "data": {"object": {"customer": "cus_1"}}})
    assert r.status_code == 503
