"""KAN-110: forged X-Forwarded-For must not choose the rate-limit bucket; MFA limits are per user."""
from types import SimpleNamespace

from aether_os.core.rate_limiter import get_client_ip


def _req(host, xff):
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={"X-Forwarded-For": xff})


def test_forged_leftmost_xff_is_ignored():
    # client sent "1.2.3.4"; our proxy appended the real peer 203.0.113.9
    assert get_client_ip(_req("10.0.0.5", "1.2.3.4, 203.0.113.9")) == "203.0.113.9"


def test_chain_of_trusted_proxies_is_skipped():
    assert get_client_ip(_req("10.0.0.5", "203.0.113.9, 10.0.0.7")) == "203.0.113.9"


def test_untrusted_peer_header_ignored():
    assert get_client_ip(_req("198.51.100.1", "1.2.3.4")) == "198.51.100.1"


def test_garbage_xff_falls_back_to_peer():
    assert get_client_ip(_req("10.0.0.5", "not-an-ip")) == "10.0.0.5"


def test_mfa_confirm_keys_by_user(gw, monkeypatch):
    from aether_os.gateway import auth_mfa
    from aether_os.gateway.auth import create_access_token
    seen = []

    async def check(key, *a, **k):
        seen.append(key)
        return not key.startswith("user:")
    monkeypatch.setattr(auth_mfa, "_check_mfa_attempts", check)
    tok = create_access_token({"mfa_pending": True, "user_id": "u-1"}, expires_hours=1)
    r = gw.client.post("/auth/mfa/confirm", json={"mfa_token": tok, "code": "000000"})
    assert r.status_code == 429
    assert "user:u-1" in seen
