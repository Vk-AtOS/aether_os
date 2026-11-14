"""KAN-110: plugin credentials are encrypted at rest and masked; plugin routes need an admin."""
import json

from aether_os.core.plugins.registry import is_secret_key


def test_secret_looking_keys_are_masked():
    for k in ("token", "api_key", "service_key", "anon_key", "bind_password", "client_secret",
              "dsn", "access_token", "Authorization", "private_key"):
        assert is_secret_key(k), k
    assert not is_secret_key("org_slug") and not is_secret_key("region")


def test_config_is_encrypted_in_db_and_masked_in_responses(gw):
    org = gw.register("plugorg")
    r = gw.client.post("/v2/plugins/install", headers=org.auth,
                       json={"plugin_id": "figma", "config": {"access_token": "figd_SECRET123", "team": "t1"}})
    assert r.status_code == 200, r.text
    assert r.json()["config"]["access_token"] == "***"
    stored = gw.sql("SELECT config_json FROM installed_plugins WHERE org_id=?", (org.org_id,))[0][0]
    assert "figd_SECRET123" not in stored
    listed = gw.client.get("/v2/plugins/installed", headers=org.auth).json()
    assert listed[0]["config"]["access_token"] == "***" and listed[0]["config"]["team"] == "t1"
    # connectors still get the real value back
    import asyncio
    from aether_os.core.plugins.registry import get_plugin_registry
    cfg = asyncio.run(get_plugin_registry().get_installed_config("figma", org.org_id))
    assert cfg["access_token"] == "figd_SECRET123"
    # a legacy plaintext row is still readable
    gw.sql("UPDATE installed_plugins SET config_json=? WHERE org_id=?", (json.dumps({"access_token": "old"}), org.org_id))
    assert asyncio.run(get_plugin_registry().get_installed_config("figma", org.org_id))["access_token"] == "old"


def test_members_cannot_manage_plugins(gw):
    org = gw.register("plugmember")
    m = gw.user_with_role("member", org.org_id)
    body = {"plugin_id": "figma", "config": {"access_token": "x"}}
    assert gw.client.post("/v2/plugins/install", headers=m.auth, json=body).status_code == 403
    assert gw.client.delete("/v2/plugins/installed/figma", headers=m.auth).status_code == 403
    assert gw.client.put("/v2/plugins/installed/figma/config", headers=m.auth, json={"config": {}}).status_code == 403
    assert gw.client.post("/v2/plugins/installed/figma/test", headers=m.auth).status_code == 403
    assert gw.client.post("/v2/plugins/connectors/invoke", headers=m.auth,
                          json={"plugin_id": "figma", "action": "get_file"}).status_code == 403
    assert gw.client.get("/v2/plugins/installed", headers=m.auth).status_code == 200


def test_members_cannot_use_ldap_or_salesforce_routes(gw):
    org = gw.register("plugldap")
    m = gw.user_with_role("member", org.org_id)
    for path in ("/v2/plugins/connectors/ldap/users", "/v2/plugins/connectors/ldap/authenticate",
                 "/v2/plugins/connectors/ldap/validate", "/v2/plugins/connectors/salesforce/validate"):
        assert gw.client.post(path, headers=m.auth, json={}).status_code == 403, path
