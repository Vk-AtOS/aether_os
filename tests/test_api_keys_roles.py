"""KAN-150: org API keys are credentials for the whole org: owner/admin only (D7), a key cannot mint keys,
the list never shows a secret, is paginated with a hard maximum, and revoke really stops the key."""


def test_member_and_viewer_cannot_create_list_or_revoke(gw):
    org = gw.register("keyroles")
    made = gw.client.post("/auth/api-keys", headers=org.auth, json={"name": "ci"})
    assert made.status_code == 200, made.text
    for role in ("member", "viewer"):
        u = gw.user_with_role(role, org.org_id)
        assert gw.client.post("/auth/api-keys", headers=u.auth, json={"name": "x"}).status_code == 403
        assert gw.client.get("/auth/api-keys", headers=u.auth).status_code == 403
        assert gw.client.delete(f"/auth/api-keys/{made.json()['id']}", headers=u.auth).status_code == 403


def test_create_shows_secret_once_list_never_and_revoke_stops_the_key(gw):
    org = gw.register("keylife")
    made = gw.client.post("/auth/api-keys", headers=org.auth, json={"name": "ci"}).json()
    assert made["api_key"].startswith("aesk_") and made["id"]
    listed = gw.client.get("/auth/api-keys", headers=org.auth).json()
    assert [k["id"] for k in listed] == [made["id"]] and made["api_key"] not in str(listed)
    key_auth = {"Authorization": f"Bearer {made['api_key']}"}
    # The key authenticates, but is not an admin: it cannot create more keys.
    assert gw.client.get("/billing/status", headers=key_auth).status_code == 200
    assert gw.client.post("/auth/api-keys", headers=key_auth, json={"name": "k2"}).status_code == 403
    assert gw.client.delete(f"/auth/api-keys/{made['id']}", headers=org.auth).status_code == 200
    assert gw.client.get("/billing/status", headers=key_auth).status_code == 401
    assert gw.client.get("/auth/api-keys", headers=org.auth).json() == []


def test_name_required_and_list_is_paginated_with_a_hard_maximum(gw):
    org = gw.register("keypage")
    assert gw.client.post("/auth/api-keys", headers=org.auth, json={"name": ""}).status_code == 422
    for i in range(3):
        assert gw.client.post("/auth/api-keys", headers=org.auth, json={"name": f"k{i}"}).status_code == 200
    assert len(gw.client.get("/auth/api-keys?limit=2", headers=org.auth).json()) == 2
    assert gw.client.get("/auth/api-keys?limit=101", headers=org.auth).status_code == 422
