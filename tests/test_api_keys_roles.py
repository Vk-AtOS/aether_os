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


def test_read_scoped_key_can_read_but_not_write_and_scopes_are_validated(gw):
    org = gw.register("keyscope")
    assert gw.client.post("/auth/api-keys", headers=org.auth, json={"name": "x", "scopes": ["admin"]}).status_code == 422
    assert gw.client.post("/auth/api-keys", headers=org.auth, json={"name": "x", "scopes": []}).status_code == 422
    ro = gw.client.post("/auth/api-keys", headers=org.auth, json={"name": "ci-read", "scopes": ["read"]}).json()
    rw = gw.client.post("/auth/api-keys", headers=org.auth, json={"name": "ci-rw"}).json()
    assert ro["scopes"] == ["read"] and rw["scopes"] == ["read", "write"]
    ro_auth = {"Authorization": f"Bearer {ro['api_key']}"}
    rw_auth = {"Authorization": f"Bearer {rw['api_key']}"}
    assert gw.client.get("/billing/status", headers=ro_auth).status_code == 200
    denied = gw.client.post("/factory/runs/does-not-matter/cancel", headers=ro_auth)
    assert denied.status_code == 403 and "write" in denied.json()["detail"]
    assert gw.client.post("/factory/runs/does-not-matter/cancel", headers=rw_auth).status_code != 403
    listed = {k["name"]: k["scopes"] for k in gw.client.get("/auth/api-keys", headers=org.auth).json()}
    assert listed == {"ci-read": ["read"], "ci-rw": ["read", "write"]}
