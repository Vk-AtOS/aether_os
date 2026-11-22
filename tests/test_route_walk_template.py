"""KAN-241: on FastAPI 0.16x scope["route"].path lacks include prefixes ("/inner/{hid}" under "/webhooks"). The role
gate must still see the full template, and must fail closed (concrete URL) when it cannot resolve it."""
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient

from aether_os.core.route_walk import route_template
from aether_os.gateway.role_gate import check_role


def _app(user):
    seen = {}

    def gate(request: Request):
        seen[request.url.path] = route_template(request.scope)
        check_role(request, user)

    inner = APIRouter(prefix="/inner")
    outer = APIRouter(prefix="/webhooks", dependencies=[Depends(gate)])

    @inner.post("/{hid}")
    def nested(hid: int):
        return {"ok": True}

    outer.include_router(inner)

    @outer.delete("/{wid}")
    def direct(wid: int):
        return {"ok": True}

    app = FastAPI()
    app.include_router(outer)

    @app.post("/factory/estimate", dependencies=[Depends(gate)])
    def top():
        return {"ok": True}

    return TestClient(app), seen


def test_full_template_is_resolved_through_nested_includes():
    client, seen = _app({"role": "admin"})
    assert client.post("/webhooks/inner/5").status_code == 200
    assert client.delete("/webhooks/7").status_code == 200
    assert client.post("/factory/estimate").status_code == 200
    assert seen == {"/webhooks/inner/5": "/webhooks/inner/{hid}", "/webhooks/7": "/webhooks/{wid}",
                    "/factory/estimate": "/factory/estimate"}


def test_admin_only_prefix_holds_for_nested_routes():
    client, _ = _app({"role": "member"})
    assert client.post("/webhooks/inner/5").status_code == 403
    assert client.delete("/webhooks/7").status_code == 403


def test_unresolvable_included_route_falls_back_to_the_concrete_url():
    class Ctx:
        original_route = object()          # not the route handling the request
    route = type("R", (), {"path": "/{wid}"})()
    assert route_template({"route": route, "fastapi": {"effective_route_context": Ctx()}}) is None
    assert route_template({"route": route}) == "/{wid}"   # top-level route: declared path is complete
