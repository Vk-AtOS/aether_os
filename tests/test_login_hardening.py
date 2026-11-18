"""KAN-69 F17: login throttled per IP only, unknown e-mail answered before bcrypt (timing), e-mail case-sensitive
(Bob@x.io and bob@x.io were two accounts, and a mixed-case login missed the account)."""
from aether_os.gateway.routers import auth_router


def _body(email, password):
    return {"email": email, "password": password, "org_name": "o", "terms_accepted": True, "dpa_accepted": True}


def test_emails_are_case_insensitive(gw):
    u = gw.register("casey")
    assert gw.client.post("/auth/register", json=_body(u.email.upper(), gw.password)).status_code == 400
    r = gw.client.post("/auth/login", json={"email": u.email.upper(), "password": gw.password})
    assert r.status_code == 200, r.text


def test_an_unknown_email_costs_a_password_check(gw, monkeypatch):
    calls = []
    real = auth_router.verify_password
    monkeypatch.setattr(auth_router, "verify_password", lambda p, h: calls.append(h) or real(p, h))
    r = gw.client.post("/auth/login", json={"email": "nobody_here@test.com", "password": "whatever-123"})
    assert r.status_code == 401 and len(calls) == 1


def test_wrong_passwords_lock_the_account_whatever_the_address(gw, monkeypatch):
    import time
    from aether_os.core.rate_limiter import _mem, get_rate_limiter
    monkeypatch.setattr(get_rate_limiter(), "max_login_attempts", 5)     # the test environment raises it to 1000
    u = gw.register("locky")
    # five failures for this account (spread over other addresses, so the per-IP counter never fills); Redis is
    # not available in the gateway fixture, so the in-memory store is the counter here
    _mem.login_attempts[f"email:{u.email.lower()}"] = [time.time()] * 5
    r = gw.client.post("/auth/login", json={"email": u.email, "password": gw.password})
    assert r.status_code == 429
    assert gw.client.post("/auth/login", json={"email": gw.register("other").email, "password": gw.password}).status_code == 200
