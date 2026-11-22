"""Every /portal/{id}/... route needs the project's portal token or a signed-in user of the owning org."""
from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest

from aether_os.core.route_walk import iter_routes

_BODY = {"approved": True, "feedback": "ok", "comment": "c", "phase": "p01"}


@pytest.fixture(scope="module")
def portal(gw, tmp_path_factory):
    import aether_os.core.projects as pm_mod

    # _resolve_run() looks under ~/.aether_os/projects: point HOME and the project
    # manager at a temp directory so the test never touches real project files.
    mp = pytest.MonkeyPatch()
    home = tmp_path_factory.mktemp("home")
    mp.setenv("HOME", str(home))
    root = home / ".aether_os" / "projects"
    mp.setattr(pm_mod, "_manager", pm_mod.ProjectManager(root=root))

    a, b = gw.register("portala"), gw.register("portalb")
    run_a, run_b = str(uuid.uuid4()), str(uuid.uuid4())
    for run_id, org_id in ((run_a, a.org_id), (run_b, b.org_id)):
        gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
               "VALUES (?, ?, 'factory: secret project', 'completed', ?, 0, 1)", (run_id, org_id, time.time()))
    (root / run_a / "p01_intake_requirements").mkdir(parents=True)
    (root / run_a / "p01_intake_requirements" / "requirements.md").write_text("org A requirements")
    (root / run_b).mkdir(parents=True)
    (root / run_b / "secret.md").write_text("org B secret")
    yield SimpleNamespace(a=a, b=b, run_a=run_a, run_b=run_b, root=root)
    mp.undo()


def _portal_calls(app, run_id):
    for route in iter_routes(app.routes):
        path = getattr(route, "path", "")
        if not path.startswith("/portal/"):
            continue
        url = (path.replace("{project_id}", run_id).replace("{run_id}", run_id)
               .replace("{phase_name}", "p01_intake_requirements"))
        assert "{" not in url, f"unfilled path param in {path}"
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, url


def _call(gw, method, url, **kwargs):
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = _BODY
    return gw.client.request(method, url, **kwargs)


def test_no_portal_route_answers_without_credentials(gw, portal):
    calls = list(_portal_calls(gw.app, portal.run_a))
    assert len(calls) >= 6, calls  # status, phase, approve, feedback, download, provenance
    for method, url in calls:
        resp = _call(gw, method, url)
        assert resp.status_code == 401, (method, url, resp.status_code)
        assert "requirements" not in resp.text


def test_another_orgs_session_gets_404_everywhere(gw, portal):
    for method, url in _portal_calls(gw.app, portal.run_a):
        resp = _call(gw, method, url, headers=portal.b.auth)
        assert resp.status_code == 404, (method, url, resp.status_code)
    assert not (portal.root / portal.run_a / "feedback.jsonl").exists()


def test_refresh_token_is_not_a_portal_credential(gw, portal):
    resp = gw.client.get(f"/portal/{portal.run_a}/status",
                         headers={"Authorization": f"Bearer {portal.a.refresh}"})
    assert resp.status_code == 401


def _assert_let_in(method, url, resp):
    assert resp.status_code == 200, (method, url, resp.status_code, resp.text[:200])


def test_owning_org_reaches_every_route(gw, portal):
    for method, url in _portal_calls(gw.app, portal.run_a):
        _assert_let_in(method, url, _call(gw, method, url, headers=portal.a.auth))
    status = gw.client.get(f"/portal/{portal.run_a}/status", headers=portal.a.auth).json()
    assert status["requirements"] == ["org A requirements"]


def test_portal_token_grants_its_own_project_only(gw, portal):
    issued = gw.client.post(f"/factory/runs/{portal.run_a}/portal-tokens", headers=portal.a.auth, json={})
    assert issued.status_code == 200, issued.text
    token = issued.json()["token"]
    for method, url in _portal_calls(gw.app, portal.run_a):
        _assert_let_in(method, url, _call(gw, method, url, headers={"X-Portal-Token": token}))
    assert gw.client.get(f"/portal/{portal.run_a}/download", params={"portal_token": token}).status_code == 200

    # Same token on another project, a wrong token, and a token for a project that has none.
    assert gw.client.get(f"/portal/{portal.run_b}/status", headers={"X-Portal-Token": token}).status_code == 401
    assert gw.client.get(f"/portal/{portal.run_a}/status", headers={"X-Portal-Token": token + "x"}).status_code == 401
    assert gw.client.get(f"/portal/{portal.run_a}/status", headers={"X-Portal-Token": b"\xe9"}).status_code == 401
    # A wrong portal token is not rescued by also being signed in as someone else.
    assert gw.client.get(f"/portal/{portal.run_b}/status",
                         headers={"X-Portal-Token": token, **portal.a.auth}).status_code == 401


def test_failed_auth_creates_nothing_on_disk(gw, portal):
    ghost = str(uuid.uuid4())
    for headers in ({}, {"X-Portal-Token": "guess"}, portal.a.auth):
        assert gw.client.get(f"/portal/{ghost}/status", headers=headers).status_code in (401, 404)
        gw.client.get(f"/portal/{ghost}/phase/anything", headers=headers)
    assert not (portal.root / ghost).exists()


@pytest.mark.parametrize("phase", ["..", "%2e%2e", ".", "..%2F" + "x"])
def test_phase_name_cannot_leave_the_project(gw, portal, phase):
    """`..` as the phase used to read every project's .md/.json files."""
    resp = gw.client.get(f"/portal/{portal.run_a}/phase/{phase}", headers=portal.a.auth)
    assert resp.status_code == 404, resp.text
    assert "org B secret" not in resp.text


def test_phase_route_rejects_dot_dot_when_called_directly(gw, portal):
    """The same check without an HTTP client in between (clients may normalise `..`)."""
    from fastapi import HTTPException
    from aether_os.gateway.client_portal.routes import get_phase_output
    with pytest.raises(HTTPException) as exc:
        gw.client.portal.call(get_phase_output, portal.run_a, "..")
    assert exc.value.status_code == 404
    ok = gw.client.portal.call(get_phase_output, portal.run_a, "p01_intake_requirements")
    assert ok["files"] == {"requirements.md": "org A requirements"}


@pytest.mark.parametrize("project_id", ["..", "%2e%2e", "a b", "x" * 200])
def test_project_id_must_be_a_plain_name(gw, portal, project_id):
    resp = gw.client.get(f"/portal/{project_id}/status", headers={"X-Portal-Token": "t", **portal.a.auth})
    assert resp.status_code == 404, resp.text
