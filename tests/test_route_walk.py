"""KAN-241: FastAPI 0.16x keeps included routers as one opaque entry in app.routes, and request.scope["route"]
is the route as declared inside its router (no include prefix). core/route_walk.py restores both views."""
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient

from aether_os.core.route_walk import iter_routes, route_template


def _app(seen):
    def dep(request: Request):
        seen[request.url.path] = route_template(request.scope)

    inner = APIRouter(prefix="/x", dependencies=[Depends(dep)])

    @inner.post("/{item_id}")
    def item(item_id: str):
        return {}

    mid = APIRouter(prefix="/api")
    mid.include_router(inner)
    app = FastAPI()
    app.include_router(mid)
    app.include_router(inner, prefix="/v2")

    @app.post("/top/{a}", dependencies=[Depends(dep)])
    def top(a: str):
        return {}

    return app


def test_iter_routes_flattens_nested_includes_with_their_prefixes():
    paths = {(r.path, tuple(sorted(r.methods or ()))) for r in iter_routes(_app({}).routes)}
    assert {("/api/x/{item_id}", ("POST",)), ("/v2/x/{item_id}", ("POST",)), ("/top/{a}", ("POST",))} <= paths


def test_route_template_has_every_include_prefix():
    seen = {}
    client = TestClient(_app(seen))
    for url in ("/api/x/1", "/v2/x/2", "/top/3"):
        assert client.post(url).status_code == 200
    assert seen == {"/api/x/1": "/api/x/{item_id}", "/v2/x/2": "/v2/x/{item_id}", "/top/3": "/top/{a}"}


def test_gateway_routes_are_all_visible():
    """The role gate, docs check and tenant walks rely on this: without flattening only a handful show up."""
    from aether_os.gateway.api import app as gateway_app

    routes = iter_routes(gateway_app.routes)
    assert len(routes) > 500
    paths = {r.path for r in routes}
    assert {"/health", "/factory/runs/{run_id}", "/v2/plugins/install"} <= paths
