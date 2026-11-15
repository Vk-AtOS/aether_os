"""KAN-110/D7: the role floor is enforced centrally for every authenticated mutating route."""
import inspect
import re

import pytest

from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.role_gate import ADMIN_ONLY, POLICY_GATED, VIEWER_EXACT, VIEWER_MAY, _matches

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
        if _matches(path, VIEWER_MAY) or path in VIEWER_EXACT or path in POLICY_GATED:
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
    assert hit >= 4
    admin = gw.user_with_role("admin", owner.org_id)
    assert gw.client.post("/webhooks", headers=admin.auth, json={}).status_code != 403


def test_api_key_callers_are_not_admins(gw):
    owner = gw.register("gate3")
    secret = gw.client.post("/auth/api-keys", headers=owner.auth, json={"name": "k"}).json()
    secret = secret.get("key") or secret.get("api_key")
    r = gw.client.post("/webhooks", headers={"Authorization": f"Bearer {secret}"}, json={})
    assert r.status_code == 403


def _deps(dep):
    for d in dep.dependencies:
        yield d.call
        yield from _deps(d)


def test_every_policy_gated_entry_really_enforces_policy(gw):
    """An entry here removes the viewer floor, so its handler must itself ask the policy engine."""
    routes = {r.path: r for r in gw.app.routes if getattr(r, "dependant", None) is not None}
    for path in POLICY_GATED:
        r = routes.get(path)
        assert r is not None, f"{path} is not a route (stale entry)"
        src = inspect.getsource(r.endpoint) + "".join(
            inspect.getsource(c) for c in _deps(r.dependant)
            if callable(c) and not str(getattr(c, "__module__", "")).startswith(("fastapi", "starlette")))
        assert re.search(r"await enforce\(|admit_run_start\(|_require_billing_admin\(", src), \
            f"{path} is exempt from the viewer floor but its handler never calls the policy engine"
    assert not any(p.endswith("/") for p in POLICY_GATED), "POLICY_GATED must list exact routes, not prefixes"


def test_agents_run_is_policy_gated_for_every_agent_and_snapshots_stay_in_the_callers_org(gw):
    a, b = gw.register("agtA"), gw.register("agtB")
    viewer = gw.user_with_role("viewer", a.org_id)
    for agent in ("policy_agent", "snapshot_agent", "risk_agent"):
        r = gw.client.post(f"/agents/{agent}/run", headers=viewer.auth, json={"metadata": {}})
        assert r.status_code == 403 and r.json()["detail"]["action"] == "agent.run", (agent, r.text)
    member = gw.user_with_role("member", a.org_id)
    run_b = "run-of-org-b"
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'x', 'completed', 1, 0, 1)", (run_b, b.org_id))
    r = gw.client.post("/agents/snapshot_agent/run", headers=member.auth, json={"metadata": {"run_id": run_b}})
    assert r.status_code == 200 and r.json()["status"] != "ok"
    assert gw.sql("SELECT count(*) FROM snapshots WHERE run_id = ?", (run_b,))[0][0] == 0


def test_a_viewer_cannot_use_new_account_routes_only_its_own_two(gw):
    """'/account' was a prefix entry: a viewer reached POST /account/import-codebase (organisation-wide profile)."""
    owner = gw.register("gate4")
    viewer = gw.user_with_role("viewer", owner.org_id)
    r = gw.client.post("/account/import-codebase", headers=viewer.auth, json={"repo_url": "https://github.com/a/b"})
    assert r.status_code == 403
    assert gw.client.put("/account/preferences", headers=viewer.auth, json={}).status_code != 403
