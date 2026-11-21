"""GET /settings/provider-status: admin only, key presence and health, never a key or a provider's error text."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from aether_os.core.llm.ahm import default_ahm
from aether_os.core.model_router_providers import _DEAD_PROVIDERS

KEY = "sk-or-very-secret-1234"


@pytest.fixture(scope="module")
def org(gw):
    owner = gw.register("provstat")
    return SimpleNamespace(owner=owner, member=gw.user_with_role("member", owner.org_id))


def _get(gw, who):
    return gw.client.get("/settings/provider-status", headers=who.auth)


def _by_id(resp):
    return {p["id"]: p for p in resp.json()["providers"]}


def test_needs_a_login_and_an_admin_role(gw, org):
    assert gw.client.get("/settings/provider-status").status_code == 401
    assert _get(gw, org.member).status_code == 403


def test_key_presence_endpoint_host_and_no_secret(gw, org, monkeypatch):
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://integrate.api.nvidia.com/v1")
    assert _by_id(_get(gw, org.owner))["openrouter"]["has_org_key"] is False
    assert gw.client.post("/settings/api-keys", headers=org.owner.auth,
                          json={"provider": "openrouter", "key": KEY}).status_code == 200
    resp = _get(gw, org.owner)
    p = _by_id(resp)["openrouter"]
    assert p["has_org_key"] is True and p["endpoint_host"] == "integrate.api.nvidia.com"
    assert KEY not in resp.text and KEY[-4:] not in resp.text
    assert _by_id(resp)["bedrock"]["uses_platform_credentials"] is True


def test_health_follows_ahm_and_the_breaker(gw, org):
    default_ahm.reset()
    _DEAD_PROVIDERS.clear()
    assert _by_id(_get(gw, org.owner))["anthropic"]["health"]["state"] == "unknown"
    for _ in range(3):
        default_ahm.record_failure("gemini", "HTTP 500 quoting sk-ant-leak")
    resp = _get(gw, org.owner)
    assert _by_id(resp)["gemini"]["health"]["state"] == "degraded" and "sk-ant-leak" not in resp.text
    default_ahm.record_success("anthropic")
    assert _by_id(_get(gw, org.owner))["anthropic"]["health"]["state"] == "healthy"
    _DEAD_PROVIDERS[("scope", "bedrock")] = time.monotonic() + 60
    h = _by_id(_get(gw, org.owner))["bedrock"]["health"]
    assert h["state"] == "down" and h["breaker_open"] is True
    _DEAD_PROVIDERS.clear()
    default_ahm.reset()
