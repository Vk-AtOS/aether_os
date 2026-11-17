"""KAN-163: what Okta and Microsoft Entra actually send to deprovision, group-push and probe."""
from __future__ import annotations

import uuid

PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


def _scim(gw, name):
    org = gw.register(name)
    token = gw.client.post("/settings/scim/rotate", headers=org.auth).json()["token"]
    return org, {"Authorization": f"Bearer {token}"}


def _create(gw, h, prefix="p"):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"
    r = gw.client.post("/scim/v2/Users", headers=h, json={"userName": email})
    assert r.status_code == 201, r.text
    return r.json()["id"], email


def test_okta_patch_active_false_deactivates_and_kills_the_session(gw):
    org, h = _scim(gw, "scimokta")
    uid, email = _create(gw, h)
    gw.sql("UPDATE users SET email_verified = 1 WHERE id = ?", (uid,))
    # Okta: no path, value is an object
    r = gw.client.patch(f"/scim/v2/Users/{uid}", headers=h,
                        json={"schemas": [PATCH], "Operations": [{"op": "replace", "value": {"active": False}}]})
    assert r.status_code == 200 and r.json()["active"] is False
    assert gw.sql("SELECT is_active FROM users WHERE id = ?", (uid,))[0][0] == 0
    # reactivation is also a PATCH
    r = gw.client.patch(f"/scim/v2/Users/{uid}", headers=h,
                        json={"schemas": [PATCH], "Operations": [{"op": "replace", "value": {"active": True}}]})
    assert r.json()["active"] is True


def test_entra_patch_string_boolean_and_capitalised_op(gw):
    org, h = _scim(gw, "scimentra")
    uid, _ = _create(gw, h)
    r = gw.client.patch(f"/scim/v2/Users/{uid}", headers=h,
                        json={"schemas": [PATCH], "Operations": [{"op": "Replace", "path": "active", "value": "False"}]})
    assert r.status_code == 200 and r.json()["active"] is False


def test_deactivated_user_cannot_use_an_existing_token_or_log_in(gw):
    org, h = _scim(gw, "scimlogin")
    member = gw.user_with_role("member", org.org_id)
    assert gw.client.get("/webhooks", headers=member.auth).status_code == 200
    gw.client.patch(f"/scim/v2/Users/{member.user_id}", headers=h,
                    json={"Operations": [{"op": "replace", "path": "active", "value": False}]})
    assert gw.client.get("/webhooks", headers=member.auth).status_code == 401
    assert gw.client.post("/auth/login", json={"email": member.email, "password": gw.password}).status_code in (401, 403)


def test_patch_validation_and_isolation(gw):
    a, ha = _scim(gw, "scimpa")
    b, hb = _scim(gw, "scimpb")
    uid, _ = _create(gw, ha)
    bad = gw.client.patch(f"/scim/v2/Users/{uid}", headers=ha, json={"Operations": [{"op": "frobnicate"}]})
    assert bad.status_code == 400 and bad.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert gw.client.patch(f"/scim/v2/Users/{uid}", headers=ha, json={}).status_code == 400
    other = gw.client.patch(f"/scim/v2/Users/{uid}", headers=hb,
                            json={"Operations": [{"op": "replace", "path": "active", "value": False}]})
    assert other.status_code == 404 and gw.sql("SELECT is_active FROM users WHERE id = ?", (uid,))[0][0] == 1


def test_username_filter_lets_the_idp_find_before_it_creates(gw):
    org, h = _scim(gw, "scimfilter")
    uid, email = _create(gw, h)
    r = gw.client.get("/scim/v2/Users", headers=h, params={"filter": f'userName eq "{email}"'})
    assert [u["id"] for u in r.json()["Resources"]] == [uid] and r.json()["totalResults"] == 1
    r = gw.client.get("/scim/v2/Users", headers=h, params={"filter": 'userName eq "nobody@test.com"'})
    assert r.json()["totalResults"] == 0
    assert gw.client.get("/scim/v2/Users", headers=h, params={"filter": "emails co x"}).status_code == 400


def test_put_no_longer_overwrites_user_preferences_with_the_display_name(gw):
    org, h = _scim(gw, "scimput")
    uid, _ = _create(gw, h)
    gw.sql("UPDATE users SET user_preferences = ? WHERE id = ?", ('{"theme":"dark"}', uid))
    gw.client.put(f"/scim/v2/Users/{uid}", headers=h, json={"displayName": "Ada L", "active": True})
    assert gw.sql("SELECT user_preferences FROM users WHERE id = ?", (uid,))[0][0] == '{"theme":"dark"}'


def test_discovery_endpoints(gw):
    org, h = _scim(gw, "scimdisc")
    spc = gw.client.get("/scim/v2/ServiceProviderConfig", headers=h).json()
    assert spc["patch"]["supported"] is True and spc["filter"]["supported"] is True and spc["bulk"]["supported"] is False
    assert gw.client.get("/scim/v2/ResourceTypes", headers=h).json()["totalResults"] == 2
    assert {s["name"] for s in gw.client.get("/scim/v2/Schemas", headers=h).json()["Resources"]} == {"User", "Group"}
    assert gw.client.get("/scim/v2/ServiceProviderConfig").status_code == 401


def test_group_lifecycle_membership_and_isolation(gw):
    a, ha = _scim(gw, "scimga")
    b, hb = _scim(gw, "scimgb")
    u1, _ = _create(gw, ha, "g1")
    u2, _ = _create(gw, ha, "g2")
    foreign, _ = _create(gw, hb, "gb")
    r = gw.client.post("/scim/v2/Groups", headers=ha, json={"displayName": "Engineering", "members": [{"value": u1}]})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert [m["value"] for m in r.json()["members"]] == [u1]
    assert gw.client.post("/scim/v2/Groups", headers=ha, json={"displayName": "Engineering"}).status_code == 409
    assert gw.client.post("/scim/v2/Groups", headers=ha,
                          json={"displayName": "Bad", "members": [{"value": foreign}]}).status_code == 400
    # Okta add / Entra remove with a path filter
    r = gw.client.patch(f"/scim/v2/Groups/{gid}", headers=ha, json={"schemas": [PATCH], "Operations": [
        {"op": "add", "path": "members", "value": [{"value": u2}]}]})
    assert sorted(m["value"] for m in r.json()["members"]) == sorted([u1, u2])
    r = gw.client.patch(f"/scim/v2/Groups/{gid}", headers=ha, json={"Operations": [
        {"op": "Remove", "path": f'members[value eq "{u1}"]'}]})
    assert [m["value"] for m in r.json()["members"]] == [u2]
    r = gw.client.patch(f"/scim/v2/Groups/{gid}", headers=ha, json={"Operations": [
        {"op": "replace", "path": "displayName", "value": "Platform"}]})
    assert r.json()["displayName"] == "Platform"
    listed = gw.client.get("/scim/v2/Groups", headers=ha, params={"filter": 'displayName eq "Platform"'}).json()
    assert listed["totalResults"] == 1
    # other org: invisible and untouchable
    assert gw.client.get(f"/scim/v2/Groups/{gid}", headers=hb).status_code == 404
    assert gw.client.delete(f"/scim/v2/Groups/{gid}", headers=hb).status_code == 404
    assert gw.client.put(f"/scim/v2/Groups/{gid}", headers=ha, json={"displayName": "Platform", "members": []}).status_code == 200
    assert gw.client.delete(f"/scim/v2/Groups/{gid}", headers=ha).status_code == 204
    assert gw.client.get(f"/scim/v2/Groups/{gid}", headers=ha).status_code == 404
    assert gw.sql("SELECT count(*) FROM scim_group_members WHERE group_id = ?", (gid,))[0][0] == 0


def test_a_group_named_admin_grants_nothing(gw):
    org, h = _scim(gw, "scimadmin")
    uid, _ = _create(gw, h)
    gw.client.post("/scim/v2/Groups", headers=h, json={"displayName": "admin", "members": [{"value": uid}]})
    assert gw.sql("SELECT role FROM users WHERE id = ?", (uid,))[0][0] == "member"


def test_token_auth_does_no_bcrypt_per_organisation(gw, monkeypatch):
    """With N orgs holding a token, authentication used to bcrypt-check all N on every request."""
    from aether_os.gateway.routers import scim_router
    org, h = _scim(gw, "scimfast")
    for i in range(3):
        _scim(gw, f"scimother{i}")
    calls = []
    monkeypatch.setattr(scim_router._bcrypt, "checkpw", lambda *a, **k: calls.append(1) or False)
    assert gw.client.get("/scim/v2/Users", headers=h).status_code == 200
    assert calls == []
    assert gw.client.get("/scim/v2/Users", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_legacy_hashed_token_still_works_until_rotated(gw):
    import bcrypt
    org = gw.register("scimlegacy")
    token = "legacy-" + uuid.uuid4().hex
    gw.sql("UPDATE organisations SET scim_token_hash = ?, scim_token_lookup = NULL WHERE id = ?",
           (bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode(), org.org_id))
    assert gw.client.get("/scim/v2/Users", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_wrong_tokens_cannot_burn_bcrypt_without_limit(gw, monkeypatch):
    """KAN-69 F20: each wrong token cost a bcrypt compare per legacy org; the legacy path is now rate limited."""
    import bcrypt
    from aether_os.core import rate_limiter as rl
    from aether_os.gateway.routers import scim_router
    org = gw.register("scimflood")
    gw.sql("UPDATE organisations SET scim_token_hash = ?, scim_token_lookup = NULL WHERE id = ?",
           (bcrypt.hashpw(b"legacy-x", bcrypt.gensalt(4)).decode(), org.org_id))
    monkeypatch.setattr(scim_router, "LEGACY_PER_MINUTE", 3)
    rl._mem.windows.clear()
    calls = []
    monkeypatch.setattr(scim_router._bcrypt, "checkpw", lambda *a, **k: calls.append(1) or False)
    codes = [gw.client.get("/scim/v2/Users", headers={"Authorization": f"Bearer wrong{i}"},
                           ).status_code for i in range(6)]
    assert codes[:3] == [401] * 3 and codes[3:] == [429] * 3 
    legacy = gw.sql("SELECT COUNT(*) FROM organisations WHERE scim_token_lookup IS NULL AND scim_token_hash IS NOT NULL")[0][0]
    assert len(calls) == 3 * legacy      # only the allowed attempts reached bcrypt
