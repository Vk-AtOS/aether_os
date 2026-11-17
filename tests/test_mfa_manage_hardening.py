"""KAN-69 F11: MFA verify-setup and disable had no attempt limit, no replay claim, and disable needed no password."""
import time

import pyotp
import pytest
from collections import Counter


@pytest.fixture(autouse=True)
def _attempt_counters(monkeypatch):
    """The rate limiter's Redis is not available in the gateway fixture (and then denies by design); the
    counters are replaced by a dict with the same contract."""
    from aether_os.gateway import auth_mfa
    seen = Counter()

    async def check(key, max_attempts=5, window=300):
        return seen[key] < max_attempts

    async def record(key):
        seen[key] += 1
    monkeypatch.setattr(auth_mfa, "_check_mfa_attempts", check)
    monkeypatch.setattr(auth_mfa, "_record_mfa_attempt", record)


def _mfa_user(gw, enabled=True):
    """A user with MFA set up through the API (the secret column is encrypted, so no raw SQL)."""
    u = gw.register("mfa")
    totp = pyotp.TOTP(gw.client.post("/auth/mfa/setup", headers=u.auth).json()["secret"])
    if enabled:
        r = gw.client.post("/auth/mfa/verify-setup", headers=u.auth, json={"code": totp.at(time.time() - 30)})
        assert r.status_code == 200, r.text
    return u, totp


def test_disable_needs_the_password(gw):
    u, totp = _mfa_user(gw)
    r = gw.client.post("/auth/mfa/disable", headers=u.auth, json={"code": totp.now(), "password": "wrong-password-1"})
    assert r.status_code == 403, r.text
    assert gw.sql("SELECT mfa_enabled FROM users WHERE id = ?", (u.user_id,))[0][0]
    r = gw.client.post("/auth/mfa/disable", headers=u.auth, json={"code": totp.now(), "password": gw.password})
    assert r.status_code == 200, r.text


def test_wrong_codes_lock_the_endpoint(gw):
    u, totp = _mfa_user(gw, enabled=False)
    for _ in range(5):
        assert gw.client.post("/auth/mfa/verify-setup", headers=u.auth, json={"code": "000000"}).status_code == 400
    assert gw.client.post("/auth/mfa/verify-setup", headers=u.auth, json={"code": totp.now()}).status_code == 429


def test_a_spent_code_cannot_be_replayed(gw):
    u, totp = _mfa_user(gw)                       # enabling spent the code of the previous 30 s step
    r = gw.client.post("/auth/mfa/disable", headers=u.auth,
                       json={"code": totp.at(time.time() - 30), "password": gw.password})
    assert r.status_code == 400 and "already been used" in r.text
