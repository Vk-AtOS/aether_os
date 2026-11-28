"""KAN-277: the monitor probed /auth/login and /<entity>s/, but generated apps serve everything under /api."""
import asyncio

import httpx

from aether_os.core import quality_monitor as qm

SPEC = {"paths": {
    "/health": {"get": {}},
    "/api/auth/login": {"post": {}},
    "/api/task_items/": {"get": {}, "post": {}},
    "/api/task_items/{item_id}": {"get": {}},
}}


def _install(monkeypatch, seen, spec):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json=spec) if spec else httpx.Response(404)
        if request.url.path == "/health":
            return httpx.Response(200, json={})
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path in ("/api/task_items/", "/api/taskitems/"):
            return httpx.Response(200, json=[{"id": 1}])
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(qm.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_probes_use_route_table_paths(monkeypatch):
    seen = []
    _install(monkeypatch, seen, SPEC)
    mon = qm.QualityMonitor("http://app", "a@b.c", "pw", entities=["TaskItem"])
    results = asyncio.run(mon.run_full_check())
    assert all(r.passed for r in results), results
    assert ("POST", "/api/auth/login") in seen and ("GET", "/api/task_items/") in seen


def test_falls_back_to_api_prefix_when_docs_are_off(monkeypatch):
    seen = []
    _install(monkeypatch, seen, None)
    mon = qm.QualityMonitor("http://app", "a@b.c", "pw", entities=["TaskItem"])
    asyncio.run(mon.check_auth())
    assert ("POST", "/api/auth/login") in seen
    assert mon._crud_path() == "/api/task_items/"
