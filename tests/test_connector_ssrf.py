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
