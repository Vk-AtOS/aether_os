"""KAN-164: LDAP hosts typed in by an org must not reach the platform's own network (SSRF); the LDAP password
oracle is rate limited; Salesforce tokens never travel in a URL."""
import asyncio

import pytest

from aether_os.core.connectors.ldap_connector import LDAPConnector
from aether_os.core.plugins.connectors import ConnectorError
from aether_os.core.rate_limiter import get_rate_limiter

LDAP = {"server": "127.0.0.1", "bind_dn": "cn=x", "bind_password": "p", "base_dn": "dc=x", "username": "u", "password": "pw"}


@pytest.mark.parametrize("server", ["127.0.0.1", "169.254.169.254", "localhost", "10.0.0.5", "evil.com/x", "a@b"])
def test_ldap_connector_refuses_non_public_or_malformed_servers(server):
    with pytest.raises(ConnectorError):
        LDAPConnector({"server": server})._get_server_info()


def test_ldap_validate_route_reports_the_refusal_and_never_echoes_the_password(gw):
    org = gw.register("ldapssrf")
    r = gw.client.post("/v2/plugins/connectors/ldap/validate", headers=org.auth,
                       json={"server": "127.0.0.1", "bind_dn": "cn=x", "bind_password": "TOPSECRET"})
    assert r.status_code == 200 and r.json()["ok"] is False and "TOPSECRET" not in r.text


def test_ldap_authenticate_is_rate_limited_per_org(gw):
    org = gw.register("ldaprate")
    codes = [gw.client.post("/v2/plugins/connectors/ldap/authenticate", headers=org.auth, json=LDAP).status_code
             for _ in range(32)]
    assert codes[:30] == [400] * 30 and codes[30:] == [429, 429]
    other = gw.register("ldaprate2")
    assert gw.client.post("/v2/plugins/connectors/ldap/authenticate", headers=other.auth, json=LDAP).status_code == 400


def test_rate_limiter_allow_counts_per_key():
    rl = get_rate_limiter()
    key = "unit:allow:k1"
    assert [asyncio.run(rl.allow(key, 2, 60)) for _ in range(3)] == [True, True, False]
    assert asyncio.run(rl.allow("unit:allow:k2", 2, 60)) is True


def test_salesforce_objects_take_the_token_in_the_body_not_the_url(gw):
    org = gw.register("sfurl")
    assert gw.client.get("/v2/plugins/connectors/salesforce/objects?instance_url=https://x.my.salesforce.com&access_token=t",
                         headers=org.auth).status_code == 405
    r = gw.client.post("/v2/plugins/connectors/salesforce/objects", headers=org.auth,
                       json={"instance_url": "http://127.0.0.1", "access_token": "t"})
    assert r.status_code == 400  # non-public instance rejected before any call
