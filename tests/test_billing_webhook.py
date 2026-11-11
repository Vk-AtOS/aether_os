"""
AetherOS — Billing Webhook Tests (LAUNCH-011, LAUNCH-012)
Tests for Razorpay webhook signature validation and subscription lifecycle.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import sys
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Suppress ResourceWarning from anyio/httpx teardown in TestClient fixtures.
warnings.filterwarnings("ignore", category=ResourceWarning)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_app(tmp_path=None):
    os.environ["AETHER_SECRET_KEY"] = "test-secret-key-32-chars-minimum"
    os.environ["AETHER_ADMIN_EMAIL"] = "admin@aetheros.ai"
    os.environ["AETHER_ADMIN_PASS"] = "admintest1234"  # INFRA-H2: standardised name
    os.environ["CORS_ORIGINS"] = "http://localhost:3000"
    os.environ["RAZORPAY_KEY_ID"] = "rzp_test_key"
    os.environ["RAZORPAY_KEY_SECRET"] = "rzp_test_secret"
    os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret_abc123"
    if tmp_path:
        db_path = str(tmp_path / "test.db")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    import aether_os.core.config.loader as cfg_mod
    cfg_mod.AetherConfig._instance = None
    import aether_os.core.db as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    import aether_os.core.rate_limiter as _rl_mod
    _rl_mod._mem = _rl_mod._MemoryStore()
    _rl_mod._instance = None
    _rl_mod._redis_available = False   # force in-memory mode — Redis state bleeds across runs
    _rl_mod._async_redis_client = None

    from aether_os.gateway.api import create_app
    return create_app()


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    app = _make_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _make_webhook_payload(event: str = "payment.captured", org_id: str = "org-123", plan_id: str = "pro") -> bytes:
    payload = {
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "notes": {
                        "org_id": org_id,
                        "plan": plan_id,
                    }
                }
            }
        }
    }
    return json.dumps(payload).encode()


def _sign_payload(body: bytes, secret: str = "test_webhook_secret_abc123") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── LAUNCH-011: Webhook signature validation ──────────────────────────────────

def test_webhook_valid_signature_returns_200(client):
    """Valid webhook with correct signature must return 200."""
    body = _make_webhook_payload()
    sig = _sign_payload(body)
    resp = client.post(
        "/billing/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json().get("received") is True


def test_webhook_missing_signature_returns_400(client):
    """Webhook without X-Razorpay-Signature header must be rejected."""
    body = _make_webhook_payload()
    resp = client.post(
        "/billing/webhook",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_webhook_invalid_signature_returns_400(client):
    """Webhook with wrong signature must be rejected."""
    body = _make_webhook_payload()
    resp = client.post(
        "/billing/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": "deadbeefdeadbeef" * 4,
        },
    )
    assert resp.status_code == 400


def test_webhook_missing_secret_env_returns_500(tmp_path):
    """If RAZORPAY_WEBHOOK_SECRET is not set, webhook must return 500."""
    from fastapi.testclient import TestClient
    app = _make_app(tmp_path)
    # Remove the secret after app creation (simulating missing config)
    old_secret = os.environ.pop("RAZORPAY_WEBHOOK_SECRET", None)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            body = _make_webhook_payload()
            resp = c.post(
                "/billing/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Signature": _sign_payload(body),
                },
            )
            assert resp.status_code == 500
    finally:
        if old_secret:
            os.environ["RAZORPAY_WEBHOOK_SECRET"] = old_secret


# ── LAUNCH-012: Subscription lifecycle ────────────────────────────────────────

def _register_and_login(client):
    import sqlite3
    email = "billingtest@example.com"
    client.post("/auth/register", json={
        "email": email,
        "password": "BillingTest@123!",
        "org_name": "BillingTestOrg",
        "terms_accepted": True,
        "dpa_accepted": True,
    })
    # Email verification uses Redis (unavailable in tests); set directly in the DB.
    db_url = os.environ.get("DATABASE_URL", "")
    db_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if db_path:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE users SET email_verified = 1 WHERE email = ?", (email,))
        conn.commit()
        conn.close()
    resp = client.post("/auth/login", json={
        "email": email,
        "password": "BillingTest@123!",
    })
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


def test_cancel_subscription(client):
    """POST /billing/cancel must downgrade plan to free."""
    token = _register_and_login(client)
    if not token:
        pytest.skip("Could not authenticate")
    resp = client.post(
        "/billing/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert data.get("plan") == "free"


def test_downgrade_cannot_be_used_to_upgrade(client):
    """A fresh trial org asking to "downgrade" to starter is a free upgrade and must be refused.

    This test used to expect 200: it asserted the billing self-upgrade defect.
    Real downgrades are covered in tests/test_security_fixes.py.
    """
    token = _register_and_login(client)
    if not token:
        pytest.skip("Could not authenticate")
    resp = client.post(
        "/billing/downgrade",
        json={"target_plan": "starter"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (400, 403)


def test_downgrade_subscription_invalid_plan_rejected(client):
    """POST /billing/downgrade with invalid target_plan must return 400."""
    token = _register_and_login(client)
    if not token:
        pytest.skip("Could not authenticate")
    resp = client.post(
        "/billing/downgrade",
        json={"target_plan": "diamond_ultra_plus"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_cancel_requires_auth(client):
    """POST /billing/cancel must reject unauthenticated requests."""
    resp = client.post("/billing/cancel")
    assert resp.status_code == 401


def test_downgrade_requires_auth(client):
    """POST /billing/downgrade must reject unauthenticated requests."""
    resp = client.post("/billing/downgrade", json={"target_plan": "free"})
    assert resp.status_code == 401


def test_invoices_endpoint_requires_auth(client):
    """GET /billing/invoices must reject unauthenticated requests."""
    resp = client.get("/billing/invoices")
    assert resp.status_code == 401


def test_invoices_endpoint_returns_list(client):
    """GET /billing/invoices must return a list for authenticated users."""
    token = _register_and_login(client)
    if not token:
        pytest.skip("Could not authenticate")
    resp = client.get(
        "/billing/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "invoices" in data
    assert isinstance(data["invoices"], list)
