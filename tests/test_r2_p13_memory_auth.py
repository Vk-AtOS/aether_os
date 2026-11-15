"""KAN-99 item 3: generated memory routers need auth, never trust a client user_id, stable ids."""
import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aether_os.phases.p13_app_memory import task_agent


@pytest.fixture()
def app(tmp_path, monkeypatch):
    out = tmp_path / "out"
    asyncio.run(task_agent.run(SimpleNamespace(input_data={}), [], out))
    (out / "src").mkdir()
    (out / "src" / "__init__.py").write_text("")
    (out / "src" / "auth.py").write_text(
        "from fastapi import Header, HTTPException\n"
        "async def get_current_user(x_user: str = Header(None), x_role: str = Header('user')):\n"
        "    if not x_user: raise HTTPException(401)\n"
        "    return {'id': x_user, 'role': x_role}\n"
        "async def require_admin(x_user: str = Header(None), x_role: str = Header('user')):\n"
        "    if x_role != 'admin': raise HTTPException(403)\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(out))
    for m in [m for m in sys.modules if m.split(".")[0] in ("memory", "src")]:
        del sys.modules[m]
    a = FastAPI()
    a.include_router(importlib.import_module("memory.memory_router").router)
    a.include_router(importlib.import_module("memory.memory_graph_router").router)
    yield a, out
    for m in [m for m in sys.modules if m.split(".")[0] in ("memory", "src")]:
        del sys.modules[m]


def test_memory_requires_auth_and_scopes_to_token_user(app):
    c = TestClient(app[0])
    assert c.get("/memory/").status_code == 401
    assert c.post("/memory/", json={"content": "alice secret"}).status_code == 401
    assert c.post("/memory/", json={"content": "alice secret"}, headers={"x-user": "alice"}).status_code == 200
    # a client-supplied user_id is ignored (no such route/field any more): bob sees nothing of alice
    assert c.post("/memory/", json={"content": "x", "user_id": "alice"}, headers={"x-user": "bob"}).status_code == 200
    mine = c.get("/memory/", headers={"x-user": "bob"}).json()["memories"]
    assert all(m["user_id"] == "bob" for m in mine)
    assert c.get("/memory/alice", headers={"x-user": "bob"}).status_code in (404, 405)


def test_graph_is_admin_only(app):
    c = TestClient(app[0])
    assert c.get("/knowledge-graph/").status_code == 403
    assert c.get("/knowledge-graph/", headers={"x-role": "admin"}).status_code == 200


def test_memory_id_is_stable_across_processes(app):
    src = (app[1] / "memory" / "memory_service.py").read_text()
    assert "hash(content)" not in src and "hashlib.sha256" in src
