"""KAN-224: the generated backend serves the admin users API that the generated Users page calls.
Run 20's UI called GET /users?page=&page_size= and POST /users; the backend had no users router (404).
The generated app is run in a subprocess (it has modules named main, models, auth, database) over httpx ASGI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from aether_os.tests.test_p04a_generated_backend import generate

_RUNNER = r'''
import asyncio, json, os, sys
app_dir = sys.argv[1]
os.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, "src"))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(app_dir, "t.db")
import httpx
import main

async def go():
    out = {}
    async with main.app.router.lifespan_context(main.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            r = await c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]})
            a = {"Authorization": "Bearer " + r.json()["access_token"]}
            r = await c.post("/api/auth/register", json={"email": "plain@x.io", "password": "Passw0rd!xyz"})
            u = {"Authorization": "Bearer " + r.json()["access_token"]}
            r = await c.get("/api/users?page=1&page_size=1", headers=a)
            out["list"] = [r.status_code, sorted(r.json()), r.json()["page_size"], len(r.json()["items"]), r.json()["total"], "password_hash" in r.text]
            r = await c.post("/api/users", headers=a, json={"email": "New@X.io", "password": "Passw0rd!xyz", "role": "user", "full_name": "New One"})
            out["create"] = [r.status_code, r.json().get("email"), r.json().get("full_name"), "password_hash" in r.text, "password" in r.json()]
            uid = r.json()["id"]
            out["dup"] = (await c.post("/api/users", headers=a, json={"email": "new@x.io", "password": "Passw0rd!xyz"})).status_code
            out["weak"] = (await c.post("/api/users", headers=a, json={"email": "w@x.io", "password": "x"})).status_code
            out["login_new"] = (await c.post("/api/auth/login", json={"email": "new@x.io", "password": "Passw0rd!xyz"})).status_code
            out["get"] = (await c.get(f"/api/users/{uid}", headers=a)).json()["email"]
            r = await c.patch(f"/api/users/{uid}", headers=a, json={"role": "manager", "full_name": "Renamed", "password": "An0ther-Pass!word"})
            out["patch"] = [r.status_code, r.json()["role"], r.json()["full_name"], "password_hash" in r.text]
            out["login_old_pw"] = (await c.post("/api/auth/login", json={"email": "new@x.io", "password": "Passw0rd!xyz"})).status_code
            out["login_new_pw"] = (await c.post("/api/auth/login", json={"email": "new@x.io", "password": "An0ther-Pass!word"})).status_code
            r = await c.delete(f"/api/users/{uid}", headers=a)
            out["delete"] = [r.status_code, r.json()["is_active"]]
            out["login_deactivated"] = (await c.post("/api/auth/login", json={"email": "new@x.io", "password": "An0ther-Pass!word"})).status_code
            out["get_after"] = (await c.get(f"/api/users/{uid}", headers=a)).status_code
            out["missing"] = (await c.get("/api/users/99999", headers=a)).status_code
            admin_id = (await c.get("/api/users?page_size=50", headers=a)).json()["items"][0]["id"]
            out["self_deactivate"] = (await c.delete(f"/api/users/{admin_id}", headers=a)).status_code
            out["user_list"] = (await c.get("/api/users", headers=u)).status_code
            out["user_create"] = (await c.post("/api/users", headers=u, json={"email": "z@x.io", "password": "Passw0rd!xyz"})).status_code
            out["user_delete"] = (await c.delete(f"/api/users/{admin_id}", headers=u)).status_code
            out["anon"] = (await c.get("/api/users")).status_code
            out["entity_list"] = (await c.get("/api/customers", headers=a)).status_code
    return out

print("RESULT " + json.dumps(asyncio.run(go())))
'''


@pytest.fixture(params=[("crm", True, False), ("crm", False, False), ("crm", True, True)], ids=["ir", "fallback", "ir-tenant"])
def run(request, tmp_path, monkeypatch):
    for mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx"):
        pytest.importorskip(mod)
    monkeypatch.setenv("ENVIRONMENT", "test")
    domain, use_ir, tenancy = request.param
    _, app = generate(tmp_path, domain=domain, use_ir=use_ir, tenancy=tenancy, monkeypatch=monkeypatch)
    env = {**os.environ, "ADMIN_PASSWORD": "Test-only-Admin-9z", "ENVIRONMENT": "test", "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, "-c", _RUNNER, str(app)], capture_output=True, text=True, env=env, timeout=180, cwd=str(app))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"generated app did not run:\n{p.stdout[-800:]}\n{p.stderr[-2000:]}"
    return json.loads(line[7:])


def test_users_admin_api(run):
    r = run
    status, keys, page_size, n_items, total, leaked = r["list"]
    assert status == 200 and keys == ["items", "limit", "page", "page_size", "total"]
    assert page_size == 1 and n_items == 1 and total >= 1 and not leaked
    assert r["create"] == [201, "new@x.io", "New One", False, False]
    assert r["dup"] == 409 and r["weak"] == 422
    assert r["login_new"] == 200                      # stored hash verifies with the app's own hasher
    assert r["get"] == "new@x.io"
    assert r["patch"] == [200, "manager", "Renamed", False]
    assert r["login_old_pw"] == 401 and r["login_new_pw"] == 200
    assert r["delete"] == [200, False] and r["login_deactivated"] == 401
    assert r["get_after"] == 200 and r["missing"] == 404
    assert r["self_deactivate"] == 400


def test_users_api_is_admin_only_and_does_not_break_entities(run):
    r = run
    assert r["user_list"] == r["user_create"] == r["user_delete"] == 403
    assert r["anon"] == 401
    assert r["entity_list"] == 200
