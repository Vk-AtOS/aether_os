"""The SPA catch-all patched into generated apps never answers /api paths and never serves files outside the build
(production acceptance run 14, 22 Nov 2026: /api/projects got index.html, or a crash where no build existed)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from aether_os.core.run_app.process_manager_helpers import patch_generated_project

MAIN = ("from fastapi import FastAPI, APIRouter\n"
        "app = FastAPI()\n"
        "r = APIRouter(prefix='/projects')\n"
        "@r.get('')\n"
        "def list_projects():\n"
        "    return {'items': []}\n"
        "app.include_router(r, prefix='/api')\n")


def _app(tmp_path, with_build=True):
    backend = tmp_path / "backend" / "src"
    backend.mkdir(parents=True)
    (backend / "main.py").write_text(MAIN)
    dist = tmp_path / "dist"
    dist.mkdir()
    if with_build:
        (dist / "index.html").write_text("<html>spa</html>")
        (dist / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("platform secret")
    patch_generated_project(tmp_path / "backend", tmp_path, None, dist, tmp_path / "log.txt")
    ns: dict = {}
    exec(compile((backend / "main.py").read_text(), "main.py", "exec"), ns)
    return TestClient(ns["app"])


def test_api_paths_are_json_404_not_the_spa(tmp_path):
    c = _app(tmp_path)
    assert c.get("/api/projects").json() == {"items": []}
    missing = c.get("/api/nope")
    assert missing.status_code == 404 and missing.json() == {"detail": "Not Found"}
    assert c.get("/api/projects/").status_code in (307, 404)   # never the SPA with 200


def test_spa_still_serves_build_files_and_routes(tmp_path):
    c = _app(tmp_path)
    assert "spa" in c.get("/").text and "spa" in c.get("/dashboard/settings").text
    assert "console.log" in c.get("/app.js").text


def test_no_file_outside_the_build_and_no_crash_without_one(tmp_path):
    c = _app(tmp_path)
    assert "platform secret" not in c.get("/..%2Fsecret.txt").text
    assert "platform secret" not in c.get("/../secret.txt").text
    c2 = _app(tmp_path / "nobuild", with_build=False)      # build dir named but index.html missing
    r = c2.get("/dashboard")
    assert r.status_code == 404 and r.json() == {"detail": "frontend not built"}
