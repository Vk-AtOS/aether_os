"""SAML RelayState: only a same-site relative path is honoured, and it is never a redirect target.

python3-saml is not installed locally, so `onelogin` is replaced by a recording
stand-in (the library is outside this codebase); /auth/saml/login and
/auth/saml/callback themselves run for real.
"""
from __future__ import annotations

import sys
import types
import urllib.parse

import pytest

from aether_os.gateway.auth_saml import _org_from_relay_state, _relay_state_for


class _FakeAuth:
    """Records which IdP settings the callback chose; never authenticates anyone."""
    seen: list = []

    def __init__(self, req, settings):
        _FakeAuth.seen.append(settings["idp"]["entityId"])

    def login(self, return_to=None):
        return "https://idp.example/sso?" + urllib.parse.urlencode({"RelayState": return_to or "LIBRARY-DEFAULT"})

    def process_response(self):
        return None

    def is_authenticated(self):
        return False

    def get_errors(self):
        return ["not authenticated (test stand-in)"]


@pytest.fixture(scope="module")
def saml(gw):
    mp = pytest.MonkeyPatch()
    pkg, saml2, auth_mod = (types.ModuleType(n) for n in ("onelogin", "onelogin.saml2", "onelogin.saml2.auth"))
    auth_mod.OneLogin_Saml2_Auth = _FakeAuth
    for name, mod in (("onelogin", pkg), ("onelogin.saml2", saml2), ("onelogin.saml2.auth", auth_mod)):
        mp.setitem(sys.modules, name, mod)
    mp.setenv("SAML_SP_ENTITY_ID", "https://sp.test/metadata")
    mp.setenv("SAML_SP_ACS_URL", "https://sp.test/auth/saml/callback")
    mp.setenv("FRONTEND_URL", "https://app.test")
    for var in ("SAML_IDP_ENTITY_ID", "SAML_IDP_SSO_URL", "SAML_IDP_CERT"):
        mp.delenv(var, raising=False)

    owner = gw.register("samlorg")
    resp = gw.client.put("/settings/sso", headers=owner.auth, json={
        "idp_entity_id": "urn:idp:org-a", "idp_sso_url": "https://idp.example/sso", "idp_cert": "CERT"})
    assert resp.status_code == 200, resp.text
    yield owner
    mp.undo()


def _callback(gw, relay_state):
    _FakeAuth.seen.clear()
    data = {"SAMLResponse": "x"}
    if relay_state is not None:
        data["RelayState"] = relay_state
    return gw.client.post("/auth/saml/callback", data=data, follow_redirects=False)


@pytest.mark.parametrize("value", [
    "https://evil.example/?org=acme", "http://evil.example/login?org=acme", "//evil.example/?org=acme",
    "/\\evil.example/?org=acme", "\\\\evil.example?org=acme", "javascript:alert(1)//?org=acme",
    "login?org=acme", "?org=acme", "/login\r\nLocation: https://evil.example?org=acme",
    "/login?org=acme" + "a" * 600, "", None, 7,
])
def test_non_relative_relay_state_is_ignored(value):
    assert _org_from_relay_state(value) is None


def test_issued_relay_state_round_trips():
    assert _relay_state_for("acme-1a2b3c") == "/login?org=acme-1a2b3c"
    assert _org_from_relay_state(_relay_state_for("acme-1a2b3c")) == "acme-1a2b3c"
    assert _org_from_relay_state(_relay_state_for("a&b=c d")) == "a&b=c d"
    assert _relay_state_for(None) == "/login" and _org_from_relay_state("/login") is None


def test_login_issues_a_relative_relay_state_naming_the_org(gw, saml):
    resp = gw.client.get("/auth/saml/login", params={"org": saml.org_slug}, follow_redirects=False)
    assert resp.status_code in (302, 307), resp.text
    query = urllib.parse.parse_qs(urllib.parse.urlparse(resp.headers["location"]).query)
    assert query["RelayState"] == [f"/login?org={saml.org_slug}"]
    assert _FakeAuth.seen[-1] == "urn:idp:org-a"


def test_callback_honours_the_issued_relay_state(gw, saml):
    resp = _callback(gw, f"/login?org={saml.org_slug}")
    assert _FakeAuth.seen == ["urn:idp:org-a"]
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://app.test/login?error=")


@pytest.mark.parametrize("template", [
    "https://evil.example/?org={slug}", "//evil.example/?org={slug}", "/\\evil.example/?org={slug}",
])
def test_callback_ignores_absolute_relay_state_and_never_redirects_to_it(gw, saml, template):
    resp = _callback(gw, template.format(slug=saml.org_slug))
    # Org not taken from the hostile value; with no platform IdP configured that is a 400.
    assert _FakeAuth.seen == []
    assert resp.status_code == 400
    assert "evil.example" not in resp.headers.get("location", "")


def test_callback_falls_back_to_platform_idp_and_default_landing(gw, saml, monkeypatch):
    monkeypatch.setenv("SAML_IDP_ENTITY_ID", "urn:idp:platform")
    monkeypatch.setenv("SAML_IDP_SSO_URL", "https://idp.platform/sso")
    monkeypatch.setenv("SAML_IDP_CERT", "CERT")
    for relay in (f"https://evil.example/?org={saml.org_slug}", None):
        resp = _callback(gw, relay)
        assert _FakeAuth.seen == ["urn:idp:platform"]
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("https://app.test/")
