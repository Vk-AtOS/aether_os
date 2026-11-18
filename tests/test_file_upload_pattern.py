"""KAN-69 G9: the generated upload router checks owner and organisation on download and delete, checks the first
bytes against the declared type, and serves an attachment with nosniff. The template is executed for real."""
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aether_os.phases.patterns.file_upload import FILE_UPLOAD_CODE

pytest.importorskip("multipart")
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def api(tmp_path, monkeypatch):
    class _File:                                  # aiofiles is a runtime dependency of the generated app only
        def __init__(self, path, mode): self.f = open(path, mode)
        async def __aenter__(self): return self
        async def __aexit__(self, *a): self.f.close()
        async def write(self, b): self.f.write(b)
    if "aiofiles" not in sys.modules:
        try:
            import aiofiles  # noqa: F401
        except ImportError:
            monkeypatch.setitem(sys.modules, "aiofiles", types.SimpleNamespace(open=lambda p, m: _File(p, m)))
    who = {"user": {"id": "u1", "org_id": "o1", "role": "user"}}
    auth = types.ModuleType("routers.auth")
    auth.get_current_user = lambda: who["user"]
    monkeypatch.setitem(sys.modules, "routers", types.ModuleType("routers"))
    monkeypatch.setitem(sys.modules, "routers.auth", auth)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    ns: dict = {"__name__": "uploads_under_test"}
    exec(compile(FILE_UPLOAD_CODE, "uploads.py", "exec"), ns)
    app = FastAPI()
    app.include_router(ns["router"])
    c = TestClient(app)
    c.who = who
    return c


def _up(c, data=PNG, name="a.png", ctype="image/png"):
    return c.post("/uploads/", files={"file": (name, data, ctype)})


def test_only_the_uploader_can_download_or_delete_and_it_is_an_attachment(api):
    made = _up(api)
    assert made.status_code == 201 and "owner_id" not in made.json() and "path" not in made.json()
    fid = made.json()["id"]
    got = api.get(f"/uploads/{fid}")
    assert got.status_code == 200 and got.content == PNG
    assert got.headers["x-content-type-options"] == "nosniff" and got.headers["content-disposition"].startswith("attachment")
    api.who["user"] = {"id": "u2", "org_id": "o1", "role": "admin"}           # same organisation, another user
    assert api.get(f"/uploads/{fid}").status_code == 404 and api.delete(f"/uploads/{fid}").status_code == 404
    api.who["user"] = {"id": "u1", "org_id": "o2", "role": "user"}            # same id, another organisation
    assert api.get(f"/uploads/{fid}").status_code == 404
    api.who["user"] = {"id": "u1", "org_id": "o1", "role": "user"}
    assert api.delete(f"/uploads/{fid}").status_code == 204


def test_content_must_match_the_declared_type(api):
    assert _up(api, b"<script>alert(1)</script>", "x.png", "image/png").status_code == 415
    assert _up(api, b"MZ\x90\x00binary", "x.txt", "text/plain").status_code == 415
    assert _up(api, b"a,b\n1,2\n", "x.csv", "text/csv").status_code == 201
    assert _up(api, b"%PDF-1.7 ...", "x.pdf", "application/pdf").status_code == 201
    assert _up(api, b"RIFF\x00\x00\x00\x00WEBPVP8 ", "x.webp", "image/webp").status_code == 201
