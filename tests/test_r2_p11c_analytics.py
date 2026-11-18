"""KAN-100: generated analytics service/router import and store events (they raised NameError / stored nothing)."""
import asyncio
import importlib.util
import sys
import types
from types import SimpleNamespace

from aether_os.phases.p11c_analytics import task_agent


def _generate(tmp_path):
    asyncio.run(task_agent.run(SimpleNamespace(input_data={"project_dir": str(tmp_path)}), [], tmp_path / "out"))
    return tmp_path / "out" / "analytics"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_service_works_without_the_posthog_package(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTHOG_API_KEY", "k")
    monkeypatch.setitem(sys.modules, "posthog", None)          # import posthog -> ImportError
    mod = _load(_generate(tmp_path) / "analytics_service.py", "an_service")
    assert mod._get_posthog() is None
    mod.track("signup", {"a": 1}, user_id=1)                   # was NameError: _ph


def test_router_writes_through_the_session_factory_with_a_bindable_cast(tmp_path, monkeypatch):
    seen = {}

    class Sess:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, stmt, params=None): seen["sql"], seen["params"] = str(stmt), params
        async def commit(self): seen["committed"] = True

    db = types.ModuleType("database")
    db.AsyncSessionLocal = lambda: Sess()
    auth = types.ModuleType("auth")
    auth.get_current_user = auth.require_admin = lambda: None
    monkeypatch.setitem(sys.modules, "database", db)
    monkeypatch.setitem(sys.modules, "auth", auth)
    monkeypatch.setenv("POSTHOG_API_KEY", "")
    mod = _load(_generate(tmp_path) / "analytics_router.py", "an_router")
    out = asyncio.run(mod.track_event({"event": "login", "user_id": 7, "data": {"x": 1}}, user={"id": "3", "org_id": "o1"}))
    assert out == {"status": "ok"} and seen.get("committed")
    assert "CAST(:d AS jsonb)" in seen["sql"] and "::jsonb" not in seen["sql"]
    assert seen["params"]["u"] == "3" and seen["params"]["o"] == "o1"      # from the token, not the body


# ── on a generated app: the endpoints had no authentication at all (KAN-100) ──

_RUNNER = r'''
import json, os, sys
app_dir = sys.argv[1]
os.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, "src")); sys.path.insert(0, os.path.join(app_dir, "analytics"))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(app_dir, "t.db")
import main, analytics_router
main.app.include_router(analytics_router.router, prefix="/api")
seen = []
class Sess:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def execute(self, stmt, params=None):
        seen.append(params)
        class R:
            def fetchall(self): return []
            def fetchone(self): return (0, 0, None, None)
        return R()
    async def commit(self): pass
analytics_router.AsyncSessionLocal = lambda: Sess()     # the SQL is Postgres-only; who may call is what is tested
from fastapi.testclient import TestClient
out = {}
with TestClient(main.app, raise_server_exceptions=False) as c:
    r = c.post("/api/auth/register", json={"email": "u1@x.io", "password": "Passw0rd!xyz", "name": "U"})
    u = {"Authorization": "Bearer " + r.json()["access_token"]}
    me = c.get("/api/auth/me", headers=u).json()
    r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": os.environ["ADMIN_PASSWORD"]})
    a = {"Authorization": "Bearer " + r.json()["access_token"]}
    ev = {"event": "login", "user_id": 999, "data": {"x": 1}}
    out["anon_track"] = c.post("/api/analytics/track", json=ev).status_code
    out["anon_events"] = c.get("/api/analytics/events").status_code
    out["user_track"] = c.post("/api/analytics/track", headers=u, json=ev).status_code
    out["stored_as_caller"] = bool(seen) and seen[-1]["u"] == str(me["id"])
    out["user_events"] = c.get("/api/analytics/events", headers=u).status_code
    out["admin_events"] = c.get("/api/analytics/events", headers=a).status_code
    out["org_scoped"] = all("o" in p for p in seen)
    out["big"] = c.post("/api/analytics/track", headers=u, json={"event": "e", "data": {"x": "y" * 9000}}).status_code
print("RESULT " + json.dumps(out))
'''


def test_generated_app_analytics_endpoints_need_a_signed_in_user_and_events_need_an_admin(tmp_path, monkeypatch):
    import json
    import os
    import subprocess

    import pytest
    from aether_os.tests.test_p04a_generated_backend import generate
    for mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx"):
        pytest.importorskip(mod)
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, monkeypatch=monkeypatch)
    asyncio.run(task_agent.run(SimpleNamespace(input_data={"project_dir": str(app)}), [], app))
    env = {**os.environ, "ADMIN_PASSWORD": "Test-only-Admin-9z", "ENVIRONMENT": "test", "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, "-c", _RUNNER, str(app)], capture_output=True, text=True, env=env, timeout=120, cwd=str(app))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"generated app did not run:\n{p.stdout[-800:]}\n{p.stderr[-1500:]}"
    assert json.loads(line[7:]) == {
        "anon_track": 401, "anon_events": 401, "user_track": 200, "stored_as_caller": True,
        "user_events": 403, "admin_events": 200, "org_scoped": True, "big": 413,
    }
