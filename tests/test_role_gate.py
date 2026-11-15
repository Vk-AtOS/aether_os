"""KAN-110/D7: the role floor is enforced centrally for every authenticated mutating route."""
import re

import pytest

from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.role_gate import VIEWER_MAY, ADMIN_ONLY, _matches

MUTATING = ("POST", "PUT", "PATCH", "DELETE")


def _uses_auth(dep):
    return any(d.call is get_current_user or _uses_auth(d) for d in dep.dependencies)


def _auth_routes(app):
    for r in app.routes:
        dep = getattr(r, "dependant", None)
        if dep is not None and _uses_auth(dep):
            for m in sorted(set(r.methods or ()) & set(MUTATING)):
                yield m, r.path


def _url(path):
    return re.sub(r"{(\w+)(?::\w+)?}", "x", path)


def test_viewer_cannot_mutate_anything_outside_the_self_service_allowlist(gw):
    owner = gw.register("gate")
    viewer = gw.user_with_role("viewer", owner.org_id)
    checked = 0
    for method, path in _auth_routes(gw.app):
        if _matches(path, VIEWER_MAY):
            continue
        checked += 1
        resp = gw.client.request(method, _url(path), headers=viewer.auth, json={})
        assert resp.status_code == 403, f"viewer reached {method} {path}: {resp.status_code}"
    assert checked > 60


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_org_wide_routes_need_admin(gw, role):
    owner = gw.register("gate2")
    user = gw.user_with_role(role, owner.org_id)
    hit = 0
    for method, path in _auth_routes(gw.app):
        if _matches(path, ADMIN_ONLY):
            hit += 1
            resp = gw.client.request(method, _url(path), headers=user.auth, json={})
            assert resp.status_code == 403, f"{role} reached {method} {path}: {resp.status_code}"
    assert hit >= 5
    admin = gw.user_with_role("admin", owner.org_id)
    assert gw.client.post("/webhooks", headers=admin.auth, json={}).status_code != 403


def test_api_key_callers_are_not_admins(gw):
    owner = gw.register("gate3")
    secret = gw.client.post("/auth/api-keys", headers=owner.auth, json={"name": "k"}).json()
    secret = secret.get("key") or secret.get("api_key")
    r = gw.client.post("/webhooks", headers={"Authorization": f"Bearer {secret}"}, json={})
    assert r.status_code == 403
