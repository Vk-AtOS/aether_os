"""KAN-99/KAN-100: generated metering middleware matches the routes the backend serves and ignores X-Tenant-Id."""
import importlib.util

from aether_os.phases.p18_billing_metering.metering_generator import generate_metering_middleware


def _load(tmp_path):
    f = tmp_path / "metering_mw.py"
    f.write_text(generate_metering_middleware([{"table": "invoice"}, {"table": "order_items"}], "demo"))
    spec = importlib.util.spec_from_file_location("metering_mw", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_prefixes_match_served_paths(tmp_path):
    m = _load(tmp_path)
    assert m._extract_entity("/api/invoice") == "invoice"
    assert m._extract_entity("/api/invoice/42") == "invoice"
    assert m._extract_entity("/api/order_items/") == "order_items"
    assert m._extract_entity("/api/invoices_other") is None
    assert m._extract_entity("/invoices") is None


def test_tenant_header_is_not_trusted(tmp_path):
    m = _load(tmp_path)

    class Req:
        headers = {"X-Tenant-Id": "victim"}
    assert m._get_tenant_id(Req()) == "unknown"


# ── KAN-196: the Stripe webhook changes tenant state ─────────────────────────────────────────
import hashlib
import hmac
import json as _json
import sys
import time as _time
import types

import pytest

from aether_os.phases.p18_billing_metering.metering_generator import generate_stripe_webhook_handler

SECRET = "whsec_test"


@pytest.fixture()
def billing(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/b.db")
    db = types.ModuleType("database")
    db.Base, db.AsyncSessionLocal = Base, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    auth = types.ModuleType("auth")

    async def get_current_user():
        return {"id": "u1", "org_id": "t1"}
    auth.get_current_user = get_current_user
    monkeypatch.setitem(sys.modules, "database", db)
    monkeypatch.setitem(sys.modules, "auth", auth)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    f = tmp_path / "billing_webhook_gen.py"
    f.write_text(generate_stripe_webhook_handler("demo"))
    spec = importlib.util.spec_from_file_location("billing_webhook_gen", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import asyncio

    async def create():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
    asyncio.run(create())
    app = FastAPI()
    app.include_router(mod.billing_router)
    return TestClient(app), mod


def _post(client, etype, customer="cus_1", meta=None):
    body = _json.dumps({"type": etype, "data": {"object": {"customer": customer, "metadata": meta or {}}}}).encode()
    ts = str(int(_time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return client.post("/billing/stripe/webhook", content=body, headers={"Stripe-Signature": f"t={ts},v1={sig}"})


def test_webhook_events_change_the_tenants_state_and_the_app_enforces_it(billing):
    client, mod = billing
    assert client.get("/billing/status").json()["status"] == "active"
    assert _post(client, "invoice.payment_failed", meta={"tenant_id": "t1"}).json()["tenant_status"] == "past_due"
    st = client.get("/billing/status").json()
    assert st["status"] == "past_due" and st["grace_until"] > _time.time()      # grace period started
    # inside the grace period access continues; after it, the dependency answers 402
    import asyncio
    assert asyncio.run(mod.require_active_subscription({"org_id": "t1"}))["org_id"] == "t1"
    first_grace = st["grace_until"]
    _post(client, "invoice.payment_failed")                                       # retry: grace must not move
    assert client.get("/billing/status").json()["grace_until"] == first_grace
    assert _post(client, "invoice.payment_succeeded").json()["tenant_status"] == "active"
    assert client.get("/billing/status").json()["grace_until"] is None
    _post(client, "customer.subscription.deleted")
    assert client.get("/billing/status").json()["status"] == "suspended"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.require_active_subscription({"org_id": "t1"}))
    assert exc.value.status_code == 402


def test_webhook_rejects_bad_signatures_and_ignores_unknown_customers(billing):
    client, _ = billing
    r = client.post("/billing/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=bad"})
    assert r.status_code == 400
    assert _post(client, "invoice.payment_failed", customer="cus_unknown").json()["ignored"] == "unknown customer"
