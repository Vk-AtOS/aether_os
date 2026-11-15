"""KAN-131: the compliance scanner judges each route on its own text."""
from aether_os.core.compliance.code_scanner import _extract_routes

SRC = '''
@router.get("/secure")
async def secure(user=Depends(get_current_user)):
    return 1

@router.get("/open")
async def open_route():
    return 2

@router.delete("/admin/x")
async def gone(u=Depends(require_admin)):
    return 3
'''


def test_unauthenticated_route_does_not_inherit_a_neighbours_auth():
    by_path = {r.path: r for r in _extract_routes(SRC)}
    assert by_path["/secure"].has_auth is True
    assert by_path["/open"].has_auth is False
    assert by_path["/admin/x"].has_auth is True          # require_* counts


def test_decorators_of_the_next_route_do_not_leak_back():
    src = '@router.get("/a")\ndef a():\n    return 1\n\n@limiter.limit("5/m")\n@router.get("/b")\ndef b():\n    return 2\n'
    by_path = {r.path: r for r in _extract_routes(src)}
    assert by_path["/a"].has_rate_limit is False and by_path["/b"].has_rate_limit is True


def test_router_level_dependency_covers_its_routes():
    src = 'router = APIRouter(prefix="/x", dependencies=[Depends(require_admin)])\n@router.get("/")\ndef f():\n    return 1\n'
    assert _extract_routes(src)[0].has_auth is True
