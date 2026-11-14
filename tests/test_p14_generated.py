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
