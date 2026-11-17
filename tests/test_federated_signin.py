"""KAN-110: OAuth/SAML/SCIM users are verified; MFA is not skipped by federated sign-in."""
import asyncio
import urllib.parse

from aether_os.gateway import auth_oauth


def test_oauth_refuses_to_link_unverified_account(gw):
    import pytest
    from fastapi import HTTPException
    u = gw.register("fedorg")
    gw.sql("UPDATE users SET email_verified = 0 WHERE email = ?", (u.email,))
    with pytest.raises(HTTPException) as ei:
        asyncio.run(auth_oauth._upsert_oauth_user(u.email))
    assert ei.value.status_code == 403
    # the pre-registrant keeps nothing new: account untouched, still unverified
    assert gw.sql("SELECT email_verified FROM users WHERE email = ?", (u.email,))[0][0] == 0


def test_oauth_new_user_is_verified(gw):
    user, _ = asyncio.run(auth_oauth._upsert_oauth_user("brandnew_fed@test.com"))
    assert user.email_verified is True


def _redirect(monkeypatch, user, org):
    """Redis clients are bound to the loop that made them: this test's asyncio.run and the app's loop each need their own."""
    from aether_os.core import pipeline_state
    from aether_os.gateway import auth_refresh
    monkeypatch.setattr(auth_refresh, "_own_client", None)
    monkeypatch.setattr(pipeline_state, "_redis", None)
    resp = asyncio.run(auth_oauth._signin_redirect(user, org))
    monkeypatch.setattr(auth_refresh, "_own_client", None)
    monkeypatch.setattr(pipeline_state, "_redis", None)
    return resp


def _code_of(resp):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(resp.headers["location"]).query)
    assert set(q) == {"code"}, "the redirect carries a one-time code and nothing else (no token in the URL)"
    return q["code"][0]


def test_mfa_user_gets_pending_challenge_not_session(gw, monkeypatch):
    u = gw.register("mfaorg")
    gw.sql("UPDATE users SET mfa_enabled = 1 WHERE email = ?", (u.email,))
    user, org = asyncio.run(auth_oauth._upsert_oauth_user(u.email))
    code = _code_of(_redirect(monkeypatch, user, org))
    got = gw.client.post("/auth/oauth/exchange", json={"code": code})
    assert got.status_code == 200 and got.json()["kind"] == "mfa" and "token" not in got.json()
    from aether_os.gateway.auth import decode_access_token
    assert decode_access_token(got.json()["mfa_token"])["mfa_pending"] is True


def test_the_jwt_is_never_in_the_redirect_url_and_the_code_is_single_use(gw, monkeypatch):
    """Root cause: the callback redirected to /auth/callback?token=<JWT>, so the session token landed in browser
    history, proxy/access logs and Referer headers. It now redirects with a 60 s single-use code."""
    u = gw.register("codeorg")
    user, org = asyncio.run(auth_oauth._upsert_oauth_user(u.email))
    resp = _redirect(monkeypatch, user, org)
    assert "eyJ" not in resp.headers["location"] and "token=" not in resp.headers["location"]
    code = _code_of(resp)
    first = gw.client.post("/auth/oauth/exchange", json={"code": code})
    assert first.status_code == 200 and first.json()["kind"] == "session" and first.json()["token"].count(".") == 2
    assert gw.client.post("/auth/oauth/exchange", json={"code": code}).status_code == 400      # spent
    assert gw.client.post("/auth/oauth/exchange", json={"code": "x" * 43}).status_code == 400  # unknown
    assert gw.client.post("/auth/oauth/exchange", json={"code": 7}).status_code == 400


def test_oauth_state_survives_a_different_worker(gw, monkeypatch):
    """The state is issued by one worker and spent by another: it must live in Redis, not in a module dict."""
    import urllib.parse
    import redis
    from aether_os.core.pipeline_state import REDIS_URL

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    r = gw.client.get("/auth/oauth/google", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    assert not hasattr(auth_oauth, "_pending_states")
    assert redis.Redis.from_url(REDIS_URL, decode_responses=True).get(f"oauthstate:{state}") == "google"


def test_oauth_callback_needs_the_cookie_of_the_browser_that_started_the_flow(gw, monkeypatch):
    """KAN-69 F9: a valid state alone let an attacker's callback URL log a victim into the attacker's account."""
    import urllib.parse
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    r = gw.client.get("/auth/oauth/google", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["state"][0]
    assert "httponly" in r.headers["set-cookie"].lower() and state in r.headers["set-cookie"]
    gw.client.cookies.clear()                      # the victim's browser never started the flow
    r = gw.client.get(f"/auth/oauth/google/callback?code=c&state={state}", follow_redirects=False)
    assert "mismatch" in urllib.parse.unquote(r.headers["location"])
