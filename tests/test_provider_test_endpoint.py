"""/settings/test-provider: platform credentials are admin-only; no provider error text reaches the client.

The provider SDKs / HTTP endpoint are the only stand-ins (they are outside the
process and tests make no network calls); the endpoint itself runs for real.
"""
from __future__ import annotations

import logging
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
    return owner, gw.user_with_role("member", owner.org_id)


def _test(gw, who, provider):
    return gw.client.post("/settings/test-provider", headers=who.auth, json={"provider": provider})


def test_member_cannot_exercise_platform_bedrock_credentials(gw, org):
    _owner, member = org
    with patch("boto3.client") as boto:
        resp = _test(gw, member, "bedrock")
    assert resp.status_code == 403, resp.text
    boto.assert_not_called()


def test_member_cannot_use_platform_key_of_other_providers(gw, org, monkeypatch):
    _owner, member = org
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-platform")
    with patch("anthropic.Anthropic") as sdk:
        resp = _test(gw, member, "anthropic")
    assert resp.status_code == 403, resp.text
    sdk.assert_not_called()


def test_admin_bedrock_failure_is_generic_and_logged(gw, org, caplog):
    owner, _member = org
    with patch("boto3.client", side_effect=_boom), caplog.at_level(logging.WARNING):
        resp = _test(gw, owner, "bedrock")
    assert resp.status_code == 400
    assert resp.json()["detail"] == _GENERIC.format("bedrock")
    assert "AKIA" not in resp.text and "arn:aws" not in resp.text
    assert any("AKIAIOSFODNN7EXAMPLE" in r.getMessage() for r in caplog.records)  # detail stays server-side


def test_admin_bedrock_success(gw, org):
    owner, _member = org
    with patch("boto3.client") as boto:
        resp = _test(gw, owner, "bedrock")
    assert resp.status_code == 200 and resp.json() == {"success": True, "message": "Connected"}
    boto.return_value.invoke_model.assert_called_once()


def test_member_may_test_the_orgs_own_key_and_errors_stay_generic(gw, org, monkeypatch):
    owner, member = org
    # save_api_key also writes the key into os.environ (known open issue); monkeypatch restores it.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    for provider in ("anthropic", "openrouter"):
        saved = gw.client.post("/settings/api-keys", headers=owner.auth,
                               json={"provider": provider, "key": f"org-key-{provider}"})
        assert saved.status_code == 200, saved.text

    with patch("anthropic.Anthropic", side_effect=_boom):
        resp = _test(gw, member, "anthropic")
    assert resp.status_code == 400 and resp.json()["detail"] == _GENERIC.format("anthropic")
    assert "sk-ant-leaked" not in resp.text

    # openrouter: a real httpx client whose transport answers like a failing provider.
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(500, text=f"upstream exploded: {_SECRET}")

    real_client = httpx.AsyncClient
    with patch("httpx.AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
        resp = _test(gw, member, "openrouter")
    assert seen["auth"] == "Bearer org-key-openrouter"
    assert resp.status_code == 400 and resp.json()["detail"] == _GENERIC.format("openrouter")
    assert "exploded" not in resp.text and "AKIA" not in resp.text


def test_unknown_provider_is_rejected_without_echoing_it(gw, org):
    owner, _member = org
    resp = _test(gw, owner, "<script>x</script>")
    assert resp.status_code == 400 and "script" not in resp.text
    assert gw.client.post("/settings/test-provider", json={"provider": "bedrock"}).status_code == 401
