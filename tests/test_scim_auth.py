"""SCIM accepts only the organisation's provisioning token, never a user session JWT."""
from __future__ import annotations

import uuid


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_user_jwt_is_rejected_on_every_scim_route(gw):
    owner = gw.register("scimjwt")
    new_email = f"prov_{uuid.uuid4().hex[:8]}@test.com"
    calls = [
        ("GET", "/scim/v2/Users", None),
        ("GET", f"/scim/v2/Users/{owner.user_id}", None),
        ("POST", "/scim/v2/Users", {"userName": new_email}),
        ("PUT", f"/scim/v2/Users/{owner.user_id}", {"active": False}),
        ("DELETE", f"/scim/v2/Users/{owner.user_id}", None),
        ("GET", "/scim/v2/Groups", None),
    ]
    scim_paths = {r.path for r in gw.app.routes if getattr(r, "path", "").startswith("/scim/")}
    assert scim_paths == {"/scim/v2/Users", "/scim/v2/Users/{user_id}", "/scim/v2/Groups"}, scim_paths
    for method, url, body in calls:
        resp = gw.client.request(method, url, headers=owner.auth, json=body)
        assert resp.status_code == 401, (method, url, resp.status_code, resp.text)
    # Nothing was provisioned or deactivated by the rejected calls.
    assert gw.sql("SELECT count(*) FROM users WHERE email = ?", (new_email,))[0][0] == 0
    assert gw.sql("SELECT is_active FROM users WHERE id = ?", (owner.user_id,))[0][0] == 1
    assert gw.client.get("/scim/v2/Users", headers=_bearer(owner.refresh)).status_code == 401


def test_org_scim_token_works_and_is_scoped_to_its_org(gw):
    a, b = gw.register("scima"), gw.register("scimb")
    rotated = gw.client.post("/settings/scim/rotate", headers=a.auth)
    assert rotated.status_code == 200, rotated.text
    token_a = rotated.json()["token"]
    token_b = gw.client.post("/settings/scim/rotate", headers=b.auth).json()["token"]

    listed = gw.client.get("/scim/v2/Users", headers=_bearer(token_a))
    assert listed.status_code == 200, listed.text
    assert [u["userName"] for u in listed.json()["Resources"]] == [a.email]

    # Org B's token cannot read or deactivate org A's user.
    assert gw.client.get(f"/scim/v2/Users/{a.user_id}", headers=_bearer(token_b)).status_code == 404
    assert gw.client.delete(f"/scim/v2/Users/{a.user_id}", headers=_bearer(token_b)).status_code == 404

    email = f"prov_{uuid.uuid4().hex[:8]}@test.com"
    created = gw.client.post("/scim/v2/Users", headers=_bearer(token_a), json={"userName": email})
    assert created.status_code == 201, created.text
    assert gw.sql("SELECT org_id, role FROM users WHERE email = ?", (email,)) == [(a.org_id, "member")]


def test_wrong_or_superseded_scim_token_is_rejected(gw):
    a = gw.register("scimrot")
    old = gw.client.post("/settings/scim/rotate", headers=a.auth).json()["token"]
    new = gw.client.post("/settings/scim/rotate", headers=a.auth).json()["token"]
    assert gw.client.get("/scim/v2/Users", headers=_bearer(old)).status_code == 401
    assert gw.client.get("/scim/v2/Users", headers=_bearer("not-a-token")).status_code == 401
    assert gw.client.get("/scim/v2/Users").status_code == 401
    assert gw.client.get("/scim/v2/Users", headers=_bearer(new)).status_code == 200
