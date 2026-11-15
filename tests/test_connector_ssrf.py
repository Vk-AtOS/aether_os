"""KAN-110: org-supplied URLs/hosts must not reach the platform's own network."""
import asyncio

import pytest

from aether_os.core.plugins.connectors import ConnectorError, assert_public_urls
from aether_os.core.schema_importer import import_schema


@pytest.mark.parametrize("key", ["base_url", "url", "instance_url"])
@pytest.mark.parametrize("target", ["http://127.0.0.1:8000", "http://169.254.169.254/latest", "http://localhost/x",
                                    "http://10.0.0.5"])
def test_private_targets_are_rejected(key, target):
    with pytest.raises(ConnectorError):
        asyncio.run(assert_public_urls({key: target}))


def test_schema_importer_refuses_internal_database_host():
    out = asyncio.run(import_schema("postgresql://u:p@127.0.0.1:5432/db"))
    assert out["tables"] == [] and "rejected" in out["error"]
    out = asyncio.run(import_schema("postgresql://u:p@169.254.169.254/db"))
    assert "rejected" in out["error"]


def test_member_cannot_probe_and_admin_gets_400_for_internal_salesforce(gw):
    org = gw.register("ssrforg")
    r = gw.client.post("/v2/plugins/connectors/salesforce/validate", headers=org.auth,
                       json={"instance_url": "http://127.0.0.1:9", "access_token": "x"})
    assert r.status_code == 400


def test_org_url_connectors_connect_through_the_pinned_client(monkeypatch):
    """DNS rebinding: a check at install time is not enough, the connection itself must be pinned
    to an address that passed the check. GitLab/Jira/Supabase used plain httpx."""
    from aether_os.core.plugins import connectors, connectors_registry

    seen = []

    class R:
        status_code = 200
        def json(self):
            return [] if seen and seen[-1].endswith("/projects") else {"username": "u", "displayName": "d"}
        def raise_for_status(self):
            pass

    async def fake(method, url, **kw):
        seen.append(url)
        return R()

    monkeypatch.setattr(connectors, "safe_request", fake)
    monkeypatch.setattr(connectors_registry, "safe_request", fake)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: (_ for _ in ()).throw(AssertionError("plain httpx")))
    for conn, cfg in (
        (connectors.GitLabConnector, {"base_url": "https://git.example.com", "token": "t"}),
        (connectors.JiraConnector, {"base_url": "https://j.example.com", "email": "e", "api_token": "t"}),
        (connectors_registry.SupabaseConnector, {"url": "https://s.example.com"}),
    ):
        assert asyncio.run(conn(cfg).test())["ok"]
    assert asyncio.run(connectors.GitLabConnector({"base_url": "https://g.x"}).action_list_projects({})) == []
    assert len(seen) == 4
