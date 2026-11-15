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

    db = types.ModuleType("src.database")
    db.AsyncSessionLocal = lambda: Sess()
    monkeypatch.setitem(sys.modules, "src", types.ModuleType("src"))
    monkeypatch.setitem(sys.modules, "src.database", db)
    monkeypatch.setenv("POSTHOG_API_KEY", "")
    mod = _load(_generate(tmp_path) / "analytics_router.py", "an_router")
    out = asyncio.run(mod.track_event({"event": "login", "user_id": 7, "data": {"x": 1}}))
    assert out == {"status": "ok"} and seen.get("committed")
    assert "CAST(:d AS jsonb)" in seen["sql"] and "::jsonb" not in seen["sql"]
