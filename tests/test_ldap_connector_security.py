"""KAN-110: LDAP user lookup escapes the username; an empty password never authenticates."""
import asyncio

import pytest

from aether_os.core.connectors.ldap_connector import LDAPConnector



def test_empty_password_is_refused_without_touching_the_server(monkeypatch):
    c = LDAPConnector({"server": "ldap.invalid", "bind_dn": "x", "bind_password": "y", "base_dn": "dc=a"})
    monkeypatch.setattr(c, "_make_connection", lambda *a, **k: pytest.fail("must not connect"))
    assert asyncio.run(c.authenticate_user("alice", "")) is False


def test_username_is_escaped_in_the_search_filter(monkeypatch):
    seen = {}

    class Conn:
        entries = []
        def search(self, search_base, search_filter, **kw): seen["f"] = search_filter
        def unbind(self): pass

    c = LDAPConnector({"server": "ldap.invalid", "bind_dn": "x", "bind_password": "y", "base_dn": "dc=a"})
    monkeypatch.setattr(c, "_make_connection", lambda *a, **k: Conn())
    asyncio.run(c.authenticate_user("*)(uid=*))(|(uid=*", "pw"))
    assert "(uid=*)" not in seen["f"] and "\\2a" in seen["f"]
