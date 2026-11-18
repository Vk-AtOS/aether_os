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


def test_ldap3_is_given_the_checked_address_not_the_name(monkeypatch):
    """KAN-69 SC-06: ldap3 resolved the name again after the check, so DNS rebinding could aim it inside."""
    import sys
    import types
    from aether_os.core.connectors import ldap_connector as lc
    seen = []

    class Srv:
        def __init__(self, host, **kw): seen.append(host)

    class Conn:
        def __init__(self, *a, **k): pass
        def unbind(self): pass

    mod = types.ModuleType("ldap3")
    mod.Server, mod.Connection, mod.ALL = Srv, Conn, "ALL"
    monkeypatch.setitem(sys.modules, "ldap3", mod)
    monkeypatch.setattr(lc, "resolve_public", lambda url: (None, ["93.184.216.34"]))
    c = LDAPConnector({"server": "ldap.example.org", "bind_dn": "x", "bind_password": "y", "base_dn": "dc=a"})
    c._make_connection()
    assert asyncio.run(c.validate(server="169.254.169.254"))["ok"] is True
    assert seen == ["93.184.216.34", "93.184.216.34"]
