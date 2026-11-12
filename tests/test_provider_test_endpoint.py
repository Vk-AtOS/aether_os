"""/settings/test-provider: an org admin tests only the org's own stored key; platform
credentials (env keys, Bedrock) are superadmin-only; no provider error text reaches the client.

The provider SDKs / HTTP endpoint are the only stand-ins (they are outside the
process and tests make no network calls); the endpoint itself runs for real.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

_SECRET = "arn:aws:iam::123456789012:user/ops AKIAIOSFODNN7EXAMPLE sk-ant-leaked"
_GENERIC = "Connection test failed for {}. Check the credentials; details are in the server log."


def _boom(*_args, **_kwargs):
    raise RuntimeError(_SECRET)


@pytest.fixture(scope="module")
def org(gw):
    owner = gw.register("prov")
    return SimpleNamespace(owner=owner, member=gw.user_with_role("member", owner.org_id),
                           superadmin=gw.user_with_role("superadmin", owner.org_id))


def _test(gw, who, provider):
    return gw.client.post("/settings/test-provider", headers=who.auth, json={"provider": provider})


def _denials(gw, org_id, action):
    return [json.loads(m) for (m,) in gw.sql(
        "SELECT log_metadata FROM audit_log WHERE org_id = ? AND action = 'policy.denied'", (org_id,))
        if json.loads(m).get("action") == action]


@pytest.mark.parametrize("who", ["member", "owner"])
def test_only_superadmin_reaches_platform_bedrock_credentials(gw, org, who):
    with patch("boto3.client") as boto:
        resp = _test(gw, getattr(org, who), "bedrock")
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "role_insufficient"
    boto.assert_not_called()


@pytest.mark.parametrize("who", ["member", "owner"])
def test_platform_env_key_is_not_testable_by_the_org(gw, org, who, monkeypatch):
    """No stored org key: the only key left is the operator's, and the org admin must not spend it."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-platform")
    with patch("httpx.AsyncClient") as http:
        resp = _test(gw, getattr(org, who), "openrouter")
    assert resp.status_code == 403, resp.text
    http.assert_not_called()
    wanted = "provider.test" if who == "member" else "provider.test_platform"
    assert _denials(gw, org.owner.org_id, wanted), "the denial must be in the ledger"


def test_superadmin_bedrock_failure_is_generic_and_logged(gw, org, caplog):
    with patch("boto3.client", side_effect=_boom), caplog.at_level(logging.WARNING):
        resp = _test(gw, org.superadmin, "bedrock")
    assert resp.status_code == 400
    assert resp.json()["detail"] == _GENERIC.format("bedrock")
    assert "AKIA" not in resp.text and "arn:aws" not in resp.text
    assert any("AKIAIOSFODNN7EXAMPLE" in r.getMessage() for r in caplog.records)  # detail stays server-side


def test_superadmin_bedrock_success(gw, org):
    with patch("boto3.client") as boto:
        resp = _test(gw, org.superadmin, "bedrock")
    assert resp.status_code == 200 and resp.json() == {"success": True, "message": "Connected"}
    boto.return_value.invoke_model.assert_called_once()


def test_superadmin_may_test_the_platform_env_key(gw, org, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "platform-google-key")
    with patch("google.genai.Client") as sdk:
        resp = _test(gw, org.superadmin, "gemini")
    assert resp.status_code == 200, resp.text
    assert sdk.call_args.kwargs == {"api_key": "platform-google-key"}


def test_org_admin_tests_the_orgs_own_key_member_does_not_and_errors_stay_generic(gw, org, monkeypatch):
    # The platform has keys too: the org's stored key must be the one that is used.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-platform")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-platform")
    for provider in ("anthropic", "openrouter"):
        saved = gw.client.post("/settings/api-keys", headers=org.owner.auth,
                               json={"provider": provider, "key": f"org-key-{provider}"})
        assert saved.status_code == 200, saved.text

    with patch("anthropic.Anthropic") as sdk:
        assert _test(gw, org.member, "anthropic").status_code == 403  # a member tests nothing
    sdk.assert_not_called()

    with patch("anthropic.Anthropic", side_effect=_boom) as sdk:
        resp = _test(gw, org.owner, "anthropic")
    assert sdk.call_args.kwargs == {"api_key": "org-key-anthropic"}
    assert resp.status_code == 400 and resp.json()["detail"] == _GENERIC.format("anthropic")
    assert "sk-ant-leaked" not in resp.text

    # openrouter: a real httpx client whose transport answers like a failing provider.
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(500, text=f"upstream exploded: {_SECRET}")

    real_client = httpx.AsyncClient
    with patch("httpx.AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
        resp = _test(gw, org.owner, "openrouter")
    assert seen["auth"] == "Bearer org-key-openrouter"
    assert resp.status_code == 400 and resp.json()["detail"] == _GENERIC.format("openrouter")
    assert "exploded" not in resp.text and "AKIA" not in resp.text


def test_unknown_provider_is_rejected_without_echoing_it(gw, org):
    resp = _test(gw, org.owner, "<script>x</script>")
    assert resp.status_code == 400 and "script" not in resp.text
    assert gw.client.post("/settings/test-provider", json={"provider": "bedrock"}).status_code == 401
