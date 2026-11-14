"""KAN-110: OAuth/SAML/SCIM users are verified; MFA is not skipped by federated sign-in."""
import asyncio
import urllib.parse

from aether_os.gateway import auth_oauth


def test_oauth_verifies_pre_registered_email_and_rotates_password(gw):
    u = gw.register("fedorg")
    gw.sql("UPDATE users SET email_verified = 0 WHERE email = ?", (u.email,))
    old = gw.sql("SELECT password_hash FROM users WHERE email = ?", (u.email,))[0][0]
    user, _ = asyncio.run(auth_oauth._upsert_oauth_user(u.email))
    assert user.email_verified is True
    assert user.password_hash != old


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
