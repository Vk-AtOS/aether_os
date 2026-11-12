"""Generated apps live on their own origin.

  * preview tokens: bound to run, purpose and the run's own origin; expire; the
    one-time enter token cannot be replayed; platform tokens are not accepted;
  * the dashboard origin never serves generated content (/app-preview is a 404 there);
  * the exchange endpoint issues links only for the caller's org's runs, and
    refuses when the configuration would put the preview on the dashboard's side;
  * the preview server sets its session only on its own origin, sends strict
    headers and strips platform credentials before proxying.
Real gateway and real preview server; nothing under test is stubbed.
"""
from __future__ import annotations

import os
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from fastapi.testclient import TestClient

from aether_os.core.run_app import preview_token as pt
from aether_os.gateway.auth import create_access_token
from aether_os.gateway.preview_server import create_preview_app, forward_headers, is_platform_credential
from aether_os.tests.gateway_env import gateway_env

ORIGIN = "http://preview.test:8100"
RUN_A = "11111111-1111-4111-8111-111111111111"
RUN_B = "22222222-2222-4222-8222-222222222222"
RUN_ORIGIN = f"http://{RUN_A}.preview.test:8100"
DASH = "http://dash.test:8000"
ENV = {"AETHER_PREVIEW_ORIGIN": ORIGIN, "AETHER_PREVIEW_SECRET": "s" * 40,
       "AETHER_DASHBOARD_ORIGIN": DASH, "CORS_ORIGINS": DASH}


@pytest.fixture(autouse=True)
def preview_env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    # Platform signer, only to mint platform tokens the preview side must refuse.
    monkeypatch.setenv("AETHER_SECRET_KEY", os.environ.get("AETHER_SECRET_KEY") or "x" * 40)


# ── tokens ────────────────────────────────────────────────────────────────────

def test_token_is_bound_to_run_purpose_and_audience():
    tok = pt.issue(RUN_A, "org-1", "user-1", pt.ENTER, 60)
    claims = pt.verify(tok, pt.ENTER, RUN_ORIGIN)
    assert (claims["run_id"], claims["org_id"], claims["sub"], claims["aud"]) == (RUN_A, "org-1", "user-1", RUN_ORIGIN)
    assert pt.verify(tok, pt.SESSION, RUN_ORIGIN) is None                    # an enter token is not a session


def test_expired_token_is_refused():
    old = pt.issue(RUN_A, "org-1", "u", pt.SESSION, 60, now=time.time() - 3600)
    assert pt.verify(old, pt.SESSION, RUN_ORIGIN) is None
    fresh = pt.issue(RUN_A, "org-1", "u", pt.SESSION, 60)
    assert pt.verify(fresh, pt.SESSION, RUN_ORIGIN, now=time.time() + 61) is None


def test_wrong_audience_is_refused(monkeypatch):
    tok = pt.issue(RUN_A, "org-1", "u", pt.SESSION, 60)
    monkeypatch.setenv("AETHER_PREVIEW_ORIGIN", "http://other-preview.test:8100")
    assert pt.verify(tok, pt.SESSION, "http://other-preview.test:8100") is None
    assert pt.verify(tok, pt.SESSION, f"http://{RUN_B}.preview.test:8100") is None   # another run's origin


def test_wrong_key_and_platform_tokens_are_refused(monkeypatch):
    platform = create_access_token({"token_type": "access", "run_id": RUN_A, "org_id": "org-1"})
    assert pt.verify(platform, pt.SESSION, RUN_ORIGIN) is None
    tok = pt.issue(RUN_A, "org-1", "u", pt.SESSION, 60)
    monkeypatch.setenv("AETHER_PREVIEW_SECRET", "t" * 40)
    assert pt.verify(tok, pt.SESSION, RUN_ORIGIN) is None


def test_enter_token_is_single_use():
    guard = pt.ReplayGuard()
    assert guard.first_use("jti-1", time.time() + 60)
    assert not guard.first_use("jti-1", time.time() + 60)


@pytest.mark.parametrize("change, problem", [
    ({"AETHER_PREVIEW_ORIGIN": ""}, "AETHER_PREVIEW_ORIGIN"),
    ({"AETHER_PREVIEW_SECRET": "short"}, "AETHER_PREVIEW_SECRET"),
    ({"AETHER_PREVIEW_ORIGIN": DASH}, "differ"),
])
def test_misconfiguration_fails_closed(monkeypatch, change, problem):
    for k, v in change.items():
        monkeypatch.setenv(k, v)
    assert problem in (pt.config_problem() or "")
    with pytest.raises(RuntimeError):
        create_preview_app()


def test_cors_allowing_the_preview_origin_is_a_misconfiguration():
    assert "CORS" in pt.config_problem([DASH, ORIGIN + "/"])


# ── preview server ────────────────────────────────────────────────────────────

@pytest.fixture
def preview():
    return TestClient(create_preview_app(), base_url=RUN_ORIGIN, follow_redirects=False)


def test_enter_sets_session_on_the_preview_origin_once(preview):
    tok = pt.issue(RUN_A, "org-1", "user-1", pt.ENTER, 60)
    first = preview.get(f"/__preview/enter?t={tok}")
    assert first.status_code == 303 and first.headers["location"] == "/app-preview/"
    cookie = first.headers["set-cookie"]
    assert cookie.startswith(pt.SESSION_COOKIE + "=") and "HttpOnly" in cookie and "Domain" not in cookie
    session = pt.verify(first.cookies[pt.SESSION_COOKIE], pt.SESSION, RUN_ORIGIN)
    assert session["run_id"] == RUN_A and session["sub"] == "user-1"
    assert preview.get(f"/__preview/enter?t={tok}").status_code == 401        # replay


@pytest.mark.parametrize("make", [
    lambda: pt.issue(RUN_A, "o", "u", pt.SESSION, 60),                           # session is not enter
    lambda: pt.issue(RUN_A, "o", "u", pt.ENTER, 60, now=time.time() - 600),       # expired
    lambda: create_access_token({"token_type": "access", "org_id": "o"}),          # platform token
    lambda: "garbage",
])
def test_enter_refuses_anything_but_a_fresh_enter_token(preview, make):
    resp = preview.get(f"/__preview/enter?t={make()}")
    assert resp.status_code == 401 and "set-cookie" not in resp.headers


def test_proxy_needs_a_session_and_sends_strict_headers(preview):
    resp = preview.get("/app-preview/")
    assert resp.status_code == 401
    csp = resp.headers["content-security-policy"]
    assert f"frame-ancestors {DASH}" in csp and "connect-src 'self'" in csp
    assert resp.headers["cross-origin-opener-policy"] == "same-origin"
    assert "access-control-allow-origin" not in resp.headers
    preview.cookies.set(pt.SESSION_COOKIE, pt.issue(RUN_B, "o", "u", pt.SESSION, 60))
    assert preview.get("/app-preview/").status_code == 401                         # another run's session
    preview.cookies.set(pt.SESSION_COOKIE, pt.issue(RUN_A, "o", "u", pt.SESSION, 60))
    assert preview.get("/app-preview/").status_code == 503                         # never launched


def test_preview_server_serves_nothing_of_the_platform(preview):
    for path in ("/auth/login", "/factory/runs", "/dashboard/", "/docs", "/openapi.json"):
        assert preview.get(path).status_code == 404, path


def test_platform_credentials_are_stripped_before_proxying():
    platform_jwt = create_access_token({"token_type": "access", "org_id": "o", "user_id": "u"})
    assert is_platform_credential(f"Bearer {platform_jwt}")
    assert is_platform_credential("Bearer aesk_live_key")
    app_jwt = jwt.encode({"sub": "42"}, "the-generated-apps-own-key", algorithm="HS256")
    assert not is_platform_credential(f"Bearer {app_jwt}")                      # the app's own login passes

    class _Req:
        headers = {"authorization": f"Bearer {platform_jwt}", "cookie": "aether_refresh=x",
                   "x-api-key": "k", "accept": "text/html"}
    assert forward_headers(_Req()) == {"accept": "text/html"}


# ── dashboard origin ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def gw(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        for k, v in ENV.items():
            mp.setenv(k, v)
        with gateway_env(tmp_path_factory.mktemp("gw")) as e:
            yield e


def _new_run(gw, org_id) -> str:
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'factory: demo', 'completed', ?, 0, 1)", (run_id, org_id, time.time()))
    return run_id


def test_dashboard_origin_does_not_serve_generated_content(gw):
    run_id = _new_run(gw, gw.org_id)
    gw.client.cookies.set("aether_preview", "anything")
    for path in ("/app-preview/", f"/app-preview/{run_id}/env", "/app-preview/api/items"):
        resp = gw.client.get(path, headers=gw.auth, follow_redirects=False)
        assert resp.status_code == 404 and "location" not in resp.headers, path
    gw.client.cookies.clear()


def test_exchange_issues_a_one_time_link_for_own_runs_only(gw):
    run_id = _new_run(gw, gw.org_id)
    resp = gw.client.post(f"/factory/runs/{run_id}/preview-session", headers=gw.auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    url = urlsplit(body["url"])
    assert f"{url.scheme}://{url.netloc}" == f"http://{run_id}.preview.test:8100" and url.path == "/__preview/enter"
    claims = pt.verify(parse_qs(url.query)["t"][0], pt.ENTER, f"http://{run_id}.preview.test:8100")
    assert claims["run_id"] == run_id and claims["org_id"] == gw.org_id
    assert claims["sub"] == gw.claims["user_id"] and claims["exp"] - claims["iat"] <= 120
    assert "allow-top-navigation" not in body["iframe_sandbox"]

    other = _new_run(gw, "some-other-org")
    assert gw.client.post(f"/factory/runs/{other}/preview-session", headers=gw.auth).status_code == 404
    assert gw.client.post(f"/factory/runs/{run_id}/preview-session").status_code in (401, 403)


def test_exchange_refuses_when_cors_allows_the_preview_origin(gw, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f"{DASH},{ORIGIN}")
    run_id = _new_run(gw, gw.org_id)
    assert gw.client.post(f"/factory/runs/{run_id}/preview-session", headers=gw.auth).status_code == 503


def test_dashboard_cors_does_not_allow_the_preview_origin(gw):
    resp = gw.client.options("/factory/runs", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "GET"})
    assert resp.headers.get("access-control-allow-origin") != ORIGIN
    ok = gw.client.options("/factory/runs", headers={"Origin": DASH, "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == DASH


# ── per-run origins and hardening (one app must not reach another run's origin) ─────────

def _enter(preview, run=RUN_A):
    return preview.get(f"/__preview/enter?t={pt.issue(run, 'org-1', 'u', pt.ENTER, 60)}")


def test_enter_token_only_works_on_its_own_runs_origin():
    other = TestClient(create_preview_app(), base_url=f"http://{RUN_B}.preview.test:8100", follow_redirects=False)
    assert _enter(other, RUN_A).status_code == 401           # run A's link spent on run B's origin
    bare = TestClient(create_preview_app(), base_url=ORIGIN, follow_redirects=False)
    assert _enter(bare, RUN_A).status_code == 401            # and on the bare base host


def test_session_cookie_of_one_run_is_useless_on_another_runs_origin(preview):
    cookie = _enter(preview).cookies[pt.SESSION_COOKIE]
    other = TestClient(create_preview_app(), base_url=f"http://{RUN_B}.preview.test:8100", follow_redirects=False)
    other.cookies.set(pt.SESSION_COOKIE, cookie)
    assert other.get("/app-preview/").status_code == 401


def test_enter_and_exit_clear_site_data_and_cookie_is_host_only(preview):
    resp = _enter(preview)
    assert '"storage"' in resp.headers["clear-site-data"] and "domain" not in resp.headers["set-cookie"].lower()
    out = preview.get("/__preview/exit")
    assert '"storage"' in out.headers["clear-site-data"]


def test_service_worker_requests_are_refused(preview):
    preview.cookies.set(pt.SESSION_COOKIE, pt.issue(RUN_A, "o", "u", pt.SESSION, 60))
    assert preview.get("/app-preview/sw.js", headers={"Service-Worker": "script"}).status_code == 403


def test_csp_allows_no_remote_images_styles_or_fonts(preview):
    csp = preview.get("/app-preview/").headers["content-security-policy"]
    for directive in ("style-src", "img-src", "font-src"):
        part = next(p for p in csp.split(";") if p.strip().startswith(directive))
        assert "https:" not in part


def test_set_cookie_filter_compares_the_parsed_name():
    from aether_os.gateway.preview_server import set_cookie_name, strip_cookie_domain
    assert set_cookie_name(" aether_preview_session =x; Path=/") == "aether_preview_session"
    assert set_cookie_name("sid=1") == "sid"
    assert strip_cookie_domain("sid=1; Domain=preview.test; Path=/; Secure") == "sid=1; Path=/; Secure"


def test_dashboard_frame_src_allows_the_run_origins(gw):
    csp = gw.client.get("/health").headers["content-security-policy"]
    assert "http://*.preview.test:8100" in csp
