"""Production run 21 (22 Nov 2026): the generated users router guards every route with Depends(require_role("admin"))
and the formal-verification gate reported INV-001 'accessible without authentication', blocking s05. require_role's
dependency itself depends on get_current_user, so these routes are authenticated."""
import ast

from aether_os.phases.p04a_backend_codegen.templates_users import _USERS_ROUTER_PY
from aether_os.phases.p06b_formal_verification.z3_encoder import extract_routes

_SRC = '''
from fastapi import APIRouter, Depends
router = APIRouter()

@router.get("/a")
async def guarded(admin: dict = Depends(require_role("admin"))):
    return 1

@router.get("/b", dependencies=[Depends(require_role("admin", "manager"))])
async def guarded_by_decorator():
    return 1

@router.get("/c")
async def open_route():
    return 1

@router.get("/d")
async def other_factory(x: dict = Depends(make_something("admin"))):
    return 1
'''


def _auth(src):
    return {r.name: r.has_auth_depends for r in extract_routes(ast.parse(src))}


def test_role_guard_factory_counts_as_authentication():
    found = _auth(_SRC)
    assert found["guarded"] is True
    assert found["guarded_by_decorator"] is True


def test_unguarded_and_unknown_factories_are_still_unauthenticated():
    found = _auth(_SRC)
    assert found["open_route"] is False
    assert found["other_factory"] is False


def test_every_route_of_the_generated_users_router_is_authenticated():
    found = _auth(_USERS_ROUTER_PY)
    assert found and all(found.values()), found
