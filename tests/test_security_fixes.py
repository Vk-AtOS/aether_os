"""Regression tests for the gateway security fixes (P0/P1 list in docs/codebase_map).

Real code paths throughout: the real FastAPI app via TestClient, a throwaway SQLite
database, two real registered orgs.  The only stand-ins are for things outside the
process (Razorpay's API, the generated-app upstream), never the function under test.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

warnings.filterwarnings("ignore", category=ResourceWarning)

_ENV = {
    "AETHER_SECRET_KEY": "test-secret-key-12345678901234567890",
    "RAZORPAY_KEY_ID": "rzp_test_id",
    "RAZORPAY_KEY_SECRET": "rzp_test_secret",
}


class _Echo(BaseHTTPRequestHandler):
    """Stand-in for a generated app: replies with the request headers it received."""
    seen: list = []

    def _reply(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        record = {"headers": {k.lower(): v for k, v in self.headers.items()}, "body": raw.decode()}
        _Echo.seen.append(record)
        body = json.dumps(record).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _reply

    def log_message(self, *args):  # keep test output quiet
        return


@pytest.fixture(scope="module")
def upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    import aether_os.core.db as db_mod
    import aether_os.core.rate_limiter as rl_mod
    from aether_os.gateway.api import create_app
    from aether_os.gateway.auth import decode_access_token

    db_file = str(tmp_path_factory.mktemp("sec") / "sec.db")
    saved = {k: os.environ.get(k) for k in (*_ENV, "DATABASE_URL", "CI_WEBHOOK_SECRET")}
    os.environ.update(_ENV, DATABASE_URL=f"sqlite+aiosqlite:///{db_file}")
    os.environ.pop("CI_WEBHOOK_SECRET", None)
    db_mod._engine = None
    db_mod._session_factory = None
    rl_mod._mem = rl_mod._MemoryStore()
    rl_mod._instance = None
    rl_mod._redis_available = False
    rl_mod._async_redis_client = None

    def sql(stmt, args=()):
        conn = sqlite3.connect(db_file)
        try:
            rows = conn.execute(stmt, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    with patch("aether_os.gateway.routers.auth_router.check_password_safety",
               new_callable=AsyncMock, return_value=(True, "")), \
         TestClient(create_app()) as client:

        def register(name):
            email = f"{name}_{uuid.uuid4().hex[:10]}@test.com"
            resp = client.post("/auth/register", json={
                "email": email, "password": "TestPass@123!", "org_name": name,
                "terms_accepted": True, "dpa_accepted": True,
            })
            assert resp.status_code == 200, resp.text
            sql("UPDATE users SET email_verified = 1 WHERE email = ?", (email,))
            body = resp.json()
            claims = decode_access_token(body["access_token"])
            return SimpleNamespace(
                email=email, token=body["access_token"], refresh=body["refresh_token"],
                org_id=claims["org_id"], claims=claims,
                auth={"Authorization": f"Bearer {body['access_token']}"},
            )

        a, b = register("orga"), register("orgb")
        run_a = str(uuid.uuid4())
        sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
            "VALUES (?, ?, 'factory: secret project', 'completed', ?, 0, 1)",
            (run_a, a.org_id, time.time()))
        yield SimpleNamespace(client=client, a=a, b=b, run_a=run_a, sql=sql, app=client.app)

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    db_mod._engine = None
    db_mod._session_factory = None


def _token_with(claims, **overrides):
    from aether_os.gateway.auth import create_access_token
    data = {k: v for k, v in claims.items() if k not in ("exp", "iat", "jti")}
    return {"Authorization": f"Bearer {create_access_token({**data, **overrides})}"}


# ── 2. Refresh tokens are not access tokens ───────────────────────────────────

def test_refresh_token_rejected_as_access_token(env):
    c = env.client
    assert c.get("/factory/runs", headers=env.a.auth).status_code == 200
    as_refresh = {"Authorization": f"Bearer {env.a.refresh}"}
    assert c.get("/factory/runs", headers=as_refresh).status_code == 401
    assert c.get("/billing/invoices", headers=as_refresh).status_code == 401
    # MCP used its own decoder; it now shares the dependency.
    assert c.get("/mcp/list_runs", headers=as_refresh).status_code == 401
    assert c.get("/mcp/list_runs", headers=env.a.auth).status_code == 200


def test_refresh_endpoint_still_accepts_only_refresh_tokens(env):
    c = env.client
    ok = c.post("/auth/refresh", json={"refresh_token": env.a.refresh})
    assert ok.status_code == 200, ok.text
    assert ok.json()["access_token"]
    assert c.post("/auth/refresh", json={"refresh_token": env.a.token}).status_code == 401


def test_decode_bearer_token_only_returns_access_tokens(env):
    from aether_os.gateway.auth import (
        create_preview_token, decode_access_token, decode_bearer_token,
    )
    assert decode_bearer_token(env.a.token)["org_id"] == env.a.org_id
    assert decode_access_token(env.a.refresh)["token_type"] == "refresh"  # signature is valid…
    assert decode_bearer_token(env.a.refresh) is None                      # …but it is not a credential
    assert decode_bearer_token(create_preview_token(env.run_a, env.a.org_id)) is None


# ── 6. IDOR: every {run_id} route is org-scoped ───────────────────────────────

# Routes with their own credential type, not the user JWT.
_NOT_JWT_SCOPED = ("/portal/", "/ci/", "/questionnaire/", "/factory/runs/{run_id}/stream")


# One body that satisfies every run route's schema, so no route can hide behind a 422.
_ANY_BODY = {
    "priority": "high", "from_phase": "p01", "path": "a.txt", "content": "x", "vars": [],
    "github_token": "t", "repo_name": "r", "message": "hi", "phase_name": "p01",
    "stage_id": "x", "respondent_email": "x@test.com", "answers": {}, "rating": 5,
}


def _run_routes(app):
    for route in app.routes:
        path = getattr(route, "path", "")
        if "{run_id}" not in path or any(path.startswith(p) or path == p for p in _NOT_JWT_SCOPED):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, path


def test_every_run_route_hides_other_orgs_runs(env):
    """Org B asks for org A's run on every {run_id} route: all must answer 404."""
    leaks, checked = [], 0
    for method, path in _run_routes(env.app):
        url = (path.replace("{run_id}", env.run_a)
               .replace("{trace_id}", "t1").replace("{decision_id}", "d1")
               .replace("{snapshot_id}", "s1").replace("{phase_name}", "p01"))
        assert "{" not in url, f"unfilled path param in {path}"
        kwargs = {"json": _ANY_BODY} if method in ("POST", "PUT", "PATCH") else {}
        resp = env.client.request(method, url, headers=env.b.auth,
                                  params={"path": "x", "file_path": "x"}, **kwargs)
        checked += 1
        if resp.status_code not in (404, 403):  # 403: questionnaire routes deny that way
            leaks.append((method, path, resp.status_code))
    assert checked >= 40, f"only {checked} run routes found — route discovery is broken"
    assert not leaks, f"routes that did not 404 for another org's run: {leaks}"


def test_owner_can_still_reach_own_run(env):
    c = env.client
    assert c.get(f"/factory/runs/{env.run_a}/traces", headers=env.a.auth).json() == []
    assert c.get(f"/factory/runs/{env.run_a}/decisions", headers=env.a.auth).status_code == 200
    assert c.get(f"/factory/runs/{env.run_a}/run-app/status", headers=env.a.auth).json()["running"] is False


@pytest.mark.parametrize("path", [
    "/intelligence/arch-governor/review",
    "/intelligence/truth-engine/validate",
    "/intelligence/conflict-resolver/resolve",
    "/intelligence/maintenance-engine/scan",
])
def test_intelligence_body_run_id_is_org_scoped(env, path):
    resp = env.client.post(path, json={"run_id": env.run_a}, headers=env.b.auth)
    assert resp.status_code == 404, resp.text


def test_improvement_loop_query_run_id_is_org_scoped(env):
    resp = env.client.post("/intelligence/improvement-loop/cycle",
                           params={"run_id": env.run_a}, headers=env.b.auth)
    assert resp.status_code == 404, resp.text


def test_kill_does_not_touch_other_orgs_run(env):
    resp = env.client.post(f"/factory/runs/{env.run_a}/kill", headers=env.b.auth)
    assert resp.status_code == 404
    assert env.sql("SELECT status FROM runs WHERE id = ?", (env.run_a,))[0][0] == "completed"


# ── 1. SAML ───────────────────────────────────────────────────────────────────

def test_saml_tenant_idp_cannot_log_in_another_orgs_user(env):
    from aether_os.gateway.auth_saml import _resolve_saml_user
    portal = env.client.portal

    # Org B's IdP asserts org A's owner — the takeover.
    with pytest.raises(HTTPException) as exc:
        portal.call(_resolve_saml_user, env.a.email, env.b.org_id)
    assert exc.value.status_code == 403

    # Org A's own IdP asserting the same user is fine.
    user, org = portal.call(_resolve_saml_user, env.a.email, env.a.org_id)
    assert (user.email, org.id) == (env.a.email, env.a.org_id)

    # The platform (env-var) IdP is operator-controlled and may log in anyone.
    user, org = portal.call(_resolve_saml_user, env.a.email, None)
    assert org.id == env.a.org_id


def test_saml_tenant_idp_provisions_into_its_own_org_as_member(env):
    from aether_os.gateway.auth_saml import _resolve_saml_user
    email = f"new_{uuid.uuid4().hex[:8]}@test.com"
    user, org = env.client.portal.call(_resolve_saml_user, email, env.b.org_id)
    assert org.id == env.b.org_id
    assert user.org_id == env.b.org_id
    assert user.role == "member"


def test_saml_rejects_deactivated_user(env):
    from aether_os.gateway.auth_saml import _resolve_saml_user
    email = f"gone_{uuid.uuid4().hex[:8]}@test.com"
    env.client.portal.call(_resolve_saml_user, email, env.b.org_id)
    env.sql("UPDATE users SET is_active = 0 WHERE email = ?", (email,))
    with pytest.raises(HTTPException) as exc:
        env.client.portal.call(_resolve_saml_user, email, env.b.org_id)
    assert exc.value.status_code == 403


def test_sso_settings_require_admin(env):
    body = {"idp_entity_id": "https://idp.example/e", "idp_sso_url": "https://idp.example/sso",
            "idp_cert": "MIIB"}
    member = _token_with(env.b.claims, role="member")
    assert env.client.put("/settings/sso", json=body, headers=member).status_code == 403
    assert env.client.delete("/settings/sso", headers=member).status_code == 403
    assert env.sql("SELECT count(*) FROM saml_configs WHERE org_id = ?", (env.b.org_id,))[0][0] == 0
    assert env.client.put("/settings/sso", json=body, headers=env.b.auth).status_code == 200
    assert env.client.delete("/settings/sso", headers=env.b.auth).status_code == 200


# ── 3. Billing ────────────────────────────────────────────────────────────────

def _plan(env, org_id):
    return env.sql("SELECT plan FROM organisations WHERE id = ?", (org_id,))[0][0]


@pytest.mark.parametrize("target", ["enterprise", "pro", "starter", "trial"])
def test_downgrade_cannot_raise_or_keep_plan(env, target):
    assert _plan(env, env.b.org_id) == "trial"
    resp = env.client.post("/billing/downgrade", json={"target_plan": target}, headers=env.b.auth)
    assert resp.status_code == 403, resp.text
    assert _plan(env, env.b.org_id) == "trial"


def test_plan_changes_require_owner_or_admin(env):
    member = _token_with(env.b.claims, role="member")
    assert env.client.post("/billing/downgrade", json={"target_plan": "free"},
                           headers=member).status_code == 403
    assert env.client.post("/billing/cancel", headers=member).status_code == 403
    assert _plan(env, env.b.org_id) == "trial"


def _signed_payment(order_id, payment_id="pay_1"):
    sig = hmac.new(_ENV["RAZORPAY_KEY_SECRET"].encode(),
                   f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return {"razorpay_order_id": order_id, "razorpay_payment_id": payment_id,
            "razorpay_signature": sig}


def _fake_razorpay(order):
    """Stands in for Razorpay's API only — verify_payment itself runs for real."""
    return lambda: SimpleNamespace(order=SimpleNamespace(fetch=lambda _oid: order))


def test_verify_payment_ignores_plan_in_request_body(env, monkeypatch):
    from aether_os.gateway.routers import billing_router
    paid_pro = {"id": "order_1", "amount": 99900, "status": "paid",
                "notes": {"org_id": env.b.org_id, "plan": "pro"}}
    monkeypatch.setattr(billing_router, "_razorpay_client", _fake_razorpay(paid_pro))
    try:
        resp = env.client.post("/billing/verify-payment",
                               json={**_signed_payment("order_1"), "plan": "enterprise"},
                               headers=env.b.auth)
        assert resp.status_code == 200, resp.text
        assert resp.json()["plan"] == "pro"
        assert _plan(env, env.b.org_id) == "pro"
    finally:
        env.sql("UPDATE organisations SET plan = 'trial' WHERE id = ?", (env.b.org_id,))


@pytest.mark.parametrize("order", [
    {"amount": 99900, "status": "paid", "notes": {"org_id": "some-other-org", "plan": "pro"}},
    {"amount": 99900, "status": "created", "notes": {"org_id": "ORG_B", "plan": "pro"}},
    {"amount": 99900, "status": "paid", "notes": {"org_id": "ORG_B", "plan": "enterprise"}},
    {"amount": 99900, "status": "paid", "notes": {}},
])
def test_verify_payment_rejects_orders_that_do_not_match(env, monkeypatch, order):
    from aether_os.gateway.routers import billing_router
    notes = {k: (env.b.org_id if v == "ORG_B" else v) for k, v in order["notes"].items()}
    monkeypatch.setattr(billing_router, "_razorpay_client", _fake_razorpay({**order, "notes": notes}))
    resp = env.client.post("/billing/verify-payment",
                           json={**_signed_payment("order_2"), "plan": "enterprise"},
                           headers=env.b.auth)
    assert resp.status_code == 400, resp.text
    assert _plan(env, env.b.org_id) == "trial"


# ── 4. /app-preview ───────────────────────────────────────────────────────────

def test_app_preview_requires_preview_cookie(env):
    c = env.client
    c.cookies.clear()
    assert c.get("/app-preview/").status_code == 401
    # A platform bearer token is not a preview session either.
    assert c.get("/app-preview/", headers=env.a.auth).status_code == 401
    # Nor is a platform access token smuggled into the cookie.
    c.cookies.set("aether_preview", env.a.token)
    assert c.get("/app-preview/").status_code == 401
    c.cookies.clear()


def test_app_preview_is_run_scoped_and_strips_platform_credentials(env, upstream):
    from aether_os.core import app_state
    c = env.client
    c.cookies.clear()
    alive = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    app_state.set_proc(env.run_a, alive)
    app_state.set_port(env.run_a, upstream)
    try:
        # Another org cannot obtain a preview session for this run.
        assert c.get(f"/factory/runs/{env.run_a}/run-app/status", headers=env.b.auth).status_code == 404
        assert "aether_preview" not in c.cookies
        assert c.get("/app-preview/whoami").status_code == 401

        # The owner's status call issues the HttpOnly, path-scoped cookie.
        resp = c.get(f"/factory/runs/{env.run_a}/run-app/status", headers=env.a.auth)
        assert resp.json()["running"] is True
        set_cookie = resp.headers["set-cookie"]
        assert "aether_preview=" in set_cookie
        assert "HttpOnly" in set_cookie and "Path=/app-preview" in set_cookie

        # Proxied request: platform token, cookie and org header never reach the app.
        resp = c.get("/app-preview/whoami", headers={**env.a.auth, "X-Org-ID": env.a.org_id})
        assert resp.status_code == 200, resp.text
        got = resp.json()["headers"]
        assert "authorization" not in got
        assert "cookie" not in got
        assert "x-org-id" not in got

        # Refresh tokens and API keys are platform credentials too.
        for cred in (f"Bearer {env.a.refresh}", "Bearer aesk_abc123"):
            got = c.get("/app-preview/whoami", headers={"Authorization": cred}).json()["headers"]
            assert "authorization" not in got

        # The generated app's own bearer token still passes through.
        got = c.get("/app-preview/whoami", headers={"Authorization": "Bearer app-own-token"}).json()["headers"]
        assert got["authorization"] == "Bearer app-own-token"
    finally:
        app_state.del_proc(env.run_a)
        app_state.del_port(env.run_a)
        c.cookies.clear()


def test_preview_cookie_is_not_an_api_credential(env):
    from aether_os.gateway.auth import create_preview_token
    tok = create_preview_token(env.run_a, env.a.org_id)
    assert env.client.get("/factory/runs", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


# ── 5. CI webhook and metrics ─────────────────────────────────────────────────

def test_ci_endpoints_fail_closed_without_secret(env, monkeypatch):
    monkeypatch.delenv("CI_WEBHOOK_SECRET", raising=False)
    body = {"repo_name": "r", "branch": "main", "ci_job_name": "j", "ci_log": "boom"}
    assert env.client.post("/ci/webhook", json=body).status_code == 503
    assert env.client.get(f"/ci/jobs/{env.run_a}").status_code == 503
    # A logged-in user is not a CI system.
    assert env.client.post("/ci/webhook", json=body, headers=env.a.auth).status_code == 503


def test_ci_endpoints_require_valid_signature(env, monkeypatch):
    monkeypatch.setenv("CI_WEBHOOK_SECRET", "ci-secret")
    c = env.client
    body = {"repo_name": "r", "branch": "main", "ci_job_name": "j", "ci_log": "boom"}
    assert c.post("/ci/webhook", json=body).status_code == 401
    assert c.post("/ci/webhook", json=body, headers={"X-Gitlab-Token": "wrong"}).status_code == 401
    assert c.post("/ci/webhook", json=body,
                  headers={"X-Hub-Signature-256": "sha256=" + "0" * 64}).status_code == 401
    assert c.get(f"/ci/jobs/{env.run_a}").status_code == 401

    # Correctly signed but schema-invalid body: passes auth (422, not 401) and queues nothing.
    raw = b'{"repo_name": "r"}'
    sig = "sha256=" + hmac.new(b"ci-secret", raw, hashlib.sha256).hexdigest()
    resp = c.post("/ci/webhook", content=raw,
                  headers={"X-Hub-Signature-256": sig, "content-type": "application/json"})
    assert resp.status_code == 422, resp.text
    # Token auth reaches the handler (unknown job → 404).
    assert c.get(f"/ci/jobs/{uuid.uuid4()}", headers={"X-Gitlab-Token": "ci-secret"}).status_code == 404


def test_metrics_internal_is_gone_and_metrics_needs_key(env):
    assert "/_metrics_internal" not in {getattr(r, "path", "") for r in env.app.routes}
    resp = env.client.get("/_metrics_internal")
    assert resp.status_code in (401, 404), resp.status_code
    assert env.client.get("/metrics").status_code == 401
    assert env.client.get("/metrics", headers={"X-Metrics-Key": "guess"}).status_code == 401


# ── 7. Outbound webhook signing ───────────────────────────────────────────────

def test_webhook_delivery_refuses_empty_secret_and_signs_with_real_one(env, upstream, monkeypatch):
    from aether_os.core.webhooks import delivery
    monkeypatch.setattr(delivery, "_assert_safe_url", lambda url: None)  # allow the loopback echo server
    url = f"http://127.0.0.1:{upstream}/hook"
    sender = delivery.WebhookDelivery()

    _Echo.seen.clear()
    assert env.client.portal.call(sender.send, url, "", "pipeline.complete", {"a": 1}) is False
    assert _Echo.seen == [], "a delivery signed with an empty key must never be sent"

    assert env.client.portal.call(sender.send, url, "s3cret", "pipeline.complete", {"a": 1}) is True
    sent = _Echo.seen[-1]
    expected = hmac.new(b"s3cret", sent["body"].encode(), hashlib.sha256).hexdigest()
    assert sent["headers"]["x-aetheros-signature-256"] == f"sha256={expected}"


def test_created_webhook_secret_is_recoverable_for_signing(env):
    from aether_os.core.webhooks.delivery import _get_org_webhooks, _signing_secret
    resp = env.client.post("/webhooks", json={"url": "https://hooks.example.org/in", "events": []},
                           headers=env.a.auth)
    assert resp.status_code == 200, resp.text
    raw_secret = resp.json()["secret"]
    stored = env.sql("SELECT secret FROM webhooks WHERE id = ?", (resp.json()["id"],))[0][0]
    assert stored and raw_secret not in stored, "secret must be stored, and not in plaintext"
    assert _signing_secret(stored) == raw_secret

    hooks = env.client.portal.call(_get_org_webhooks, env.a.org_id, "pipeline.complete")
    assert [h["secret"] for h in hooks] == [raw_secret]
    assert env.client.portal.call(_get_org_webhooks, env.b.org_id, "pipeline.complete") == []


def test_signing_secret_handles_missing_and_legacy_rows():
    from aether_os.core.webhooks.delivery import _signing_secret
    assert _signing_secret(None) == ""
    assert _signing_secret("") == ""
    assert _signing_secret("legacy-plaintext") == "legacy-plaintext"


# ── Feature flags are process-wide: platform operator only ────────────────────

def test_feature_flags_can_only_be_set_by_platform_operator(env, monkeypatch):
    from aether_os.core.feature_flags import flags
    flag = next(iter(flags.all_flags()))
    key = f"FEATURE_{flag.upper()}"
    monkeypatch.delenv(key, raising=False)
    url = f"/system/feature-flags/{flag}"
    # An org owner is not the platform operator: the flag affects every organisation.
    assert env.client.post(url, json={"enabled": False}, headers=env.a.auth).status_code == 403
    assert key not in os.environ
    operator = _token_with(env.a.claims, role="superadmin")
    assert env.client.post("/system/feature-flags/not_a_flag", json={}, headers=operator).status_code == 404
    assert "FEATURE_NOT_A_FLAG" not in os.environ
    monkeypatch.setenv(key, "true")  # registered with monkeypatch, so teardown removes the endpoint's write
    assert env.client.post(url, json={"enabled": False}, headers=operator).status_code == 200
    assert os.environ[key] == "false"
