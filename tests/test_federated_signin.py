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


def test_mfa_user_gets_pending_token_not_session(gw):
    u = gw.register("mfaorg")
    gw.sql("UPDATE users SET mfa_enabled = 1 WHERE email = ?", (u.email,))
    user, org = asyncio.run(auth_oauth._upsert_oauth_user(u.email))
    url = auth_oauth._signin_redirect(user, org).headers["location"]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert "token" not in q and q["mfa_required"] == ["1"]
    from aether_os.gateway.auth import decode_access_token
    assert decode_access_token(q["mfa_token"][0])["mfa_pending"] is True


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
