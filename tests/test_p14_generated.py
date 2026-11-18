"""KAN-99/KAN-109: generated client portal has a logger, escapes ticket text and needs auth."""
import asyncio
import py_compile
import sys
from types import SimpleNamespace

from aether_os.phases.p14_client_portal import task_agent


def _generate(tmp_path):
    asyncio.run(task_agent.run(SimpleNamespace(input_data={"project_name": "Demo"}), [], tmp_path))
    return next(tmp_path.rglob("portal_router.py")).parent


def test_router_defines_logger_and_compiles(tmp_path):
    d = _generate(tmp_path)
    src = (d / "portal_router.py").read_text()
    py_compile.compile(str(d / "portal_router.py"), doraise=True)
    assert "logger = logging.getLogger" in src


def test_html_escapes_user_fields(tmp_path):
    html = (_generate(tmp_path) / "client_portal.html").read_text()
    assert "${t.title}" not in html and "${esc(t.title)}" in html
    assert "${t.status}" not in html


def test_portal_requires_auth(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    d = _generate(tmp_path)
    sys.path.insert(0, str(d))
    try:
        import portal_router
        app = FastAPI()
        app.include_router(portal_router.router)
        c = TestClient(app)
        assert c.post("/portal/tickets", json={"title": "t", "description": "d"}).status_code in (401, 403, 503)
        assert c.get("/portal/tickets").status_code in (401, 403, 503)
    finally:
        sys.path.remove(str(d))
        sys.modules.pop("portal_router", None)


def _client(tmp_path, monkeypatch, user):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    d = _generate(tmp_path)
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, str(d))
    import portal_router
    app = FastAPI()
    app.include_router(portal_router.router)
    app.dependency_overrides[portal_router.get_current_user] = lambda: user
    app.dependency_overrides[portal_router.require_admin] = lambda: user
    return TestClient(app), portal_router, d


def test_tickets_are_scoped_to_the_organisation_and_the_author(tmp_path, monkeypatch):
    """KAN-100 p14: every signed-in user listed and read every other user's and organisation's tickets."""
    alice = {"sub": "1", "org_id": "A", "role": "user"}
    admin_a = {"sub": "2", "org_id": "A", "role": "admin"}
    admin_b = {"sub": "3", "org_id": "B", "role": "admin"}
    try:
        c, pr, d = _client(tmp_path, monkeypatch, alice)
        t = c.post("/portal/tickets", json={"title": "mine", "description": "d"}).json()
        c.app.dependency_overrides[pr.get_current_user] = lambda: {"sub": "9", "org_id": "A", "role": "user"}
        assert c.get("/portal/tickets").json()["total"] == 0                       # same org, not the author
        assert c.get(f"/portal/tickets/{t['id']}").status_code == 404
        c.app.dependency_overrides[pr.get_current_user] = lambda: admin_a
        assert c.get("/portal/tickets").json()["total"] == 1                       # the org's admin sees it
        c.app.dependency_overrides[pr.get_current_user] = lambda: admin_b
        assert c.get("/portal/tickets").json()["total"] == 0                       # another org: nothing
        assert c.get(f"/portal/tickets/{t['id']}").status_code == 404
        c.app.dependency_overrides[pr.require_admin] = lambda: admin_b
        assert c.patch(f"/portal/tickets/{t['id']}", json={"status": "closed"}).status_code == 404
    finally:
        sys.path.remove(str(d))
        sys.modules.pop("portal_router", None)


def test_p10_portal_path_outside_the_project_is_never_touched_and_text_is_escaped(tmp_path):
    import json
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "client_portal.html").write_text("<html><body><div>x</div>\n</body></html>" * 3)
    proj = tmp_path / "proj"
    out = proj / "p14"
    (proj / "p10_docs_delivery").mkdir(parents=True)
    (proj / "p10_docs_delivery" / "consolidated.json").write_text(
        json.dumps({"phases": {"client_portal": {"output_path": str(outside)}}}))
    before = (outside / "client_portal.html").read_text()
    asyncio.run(task_agent.run(SimpleNamespace(input_data={"project_dir": str(proj), "quality_score": "<b>9</b>"}), [], out))
    assert (outside / "client_portal.html").read_text() == before        # the path was outside the project

    inside = proj / "p10_docs_delivery" / "portal"
    inside.mkdir()
    (inside / "client_portal.html").write_text("<html><body><div>x</div>\n</div>\n</body></html>")
    (proj / "p10_docs_delivery" / "consolidated.json").write_text(
        json.dumps({"phases": {"client_portal": {"output_path": str(inside)}}}))
    for _ in range(2):
        asyncio.run(task_agent.run(SimpleNamespace(input_data={"project_dir": str(proj), "quality_score": "<b>9</b>",
                                                               "council_verdict": "<script>x</script>"}), [], out))
    html = (inside / "client_portal.html").read_text()
    assert "&lt;b&gt;9&lt;/b&gt;" in html and "<script>x" not in html
    assert html.count("data-aether-quality") == 1                         # injected once across two runs


def test_gate_reports_a_missing_page_instead_of_crashing(tmp_path):
    from aether_os.phases.base import TaskResult
    from aether_os.phases.p14_client_portal import gate
    out = asyncio.run(gate.validate(TaskResult(output_path=str(tmp_path / "none"), confidence=1.0, metadata={}, success=True), None))
    assert not out.passed and any("missing" in i for i in out.issues)


def test_a_symlinked_portal_page_or_directory_is_never_written_through(tmp_path):
    """The path check passed for a portal inside the project, but the page itself (or its directory) could be a symlink to a
    file outside it: the enhancement read and wrote it by plain path. It now goes through safe_fs (O_NOFOLLOW)."""
    import json
    victim = tmp_path / "victim.html"
    victim.write_text("<html><body><div>x</div>\n</div>\n</body></html>")
    before = victim.read_text()
    proj = tmp_path / "proj"
    (proj / "p10_docs_delivery").mkdir(parents=True)
    portal = proj / "p10_docs_delivery" / "portal"
    portal.mkdir()
    (portal / "client_portal.html").symlink_to(victim)                         # the page is a link out of the project
    (proj / "p10_docs_delivery" / "consolidated.json").write_text(
        json.dumps({"phases": {"client_portal": {"output_path": str(portal)}}}))
    asyncio.run(task_agent.run(SimpleNamespace(input_data={"project_dir": str(proj), "quality_score": "9"}), [], proj / "p14"))
    assert victim.read_text() == before

    linked_dir = proj / "p10_docs_delivery" / "portal_link"                     # the directory is a link out of the project
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "client_portal.html").write_text(before)
    linked_dir.symlink_to(outside_dir)
    (proj / "p10_docs_delivery" / "consolidated.json").write_text(
        json.dumps({"phases": {"client_portal": {"output_path": str(linked_dir)}}}))
    asyncio.run(task_agent.run(SimpleNamespace(input_data={"project_dir": str(proj), "quality_score": "9"}), [], proj / "p14b"))
    assert (outside_dir / "client_portal.html").read_text() == before
