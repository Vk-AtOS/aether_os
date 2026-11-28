"""KAN-254: INV-001/005 resolve effective dependencies on the AST (router/include/Annotated/custom) and still flag
a truly unprotected route; tenant filters are found even with nested parentheses."""
import ast
import textwrap

from aether_os.phases.p06b_formal_verification.route_deps import collect_included_auth
from aether_os.phases.p06b_formal_verification.z3_checkers import _check_inv001_auth
from aether_os.phases.p06b_formal_verification.z3_encoder import Z3Encoder, extract_routes
from aether_os.phases.p06b_formal_verification.z3_invariants import _check_inv005_tenant_isolation


def _routes(src, **kw):
    return {r.name: r for r in extract_routes(ast.parse(textwrap.dedent(src)), **kw)}


def _inv1(src, name, **kw):
    return _check_inv001_auth(_routes(src, **kw)[name]).status


def test_router_level_dependencies_guard_every_route():
    src = """
    router = APIRouter(prefix="/items", dependencies=[Depends(get_current_user)])
    @router.get("/")
    async def list_items(): ...
    """
    assert _inv1(src, "list_items") == "VERIFIED"


def test_annotated_alias_and_inline_annotated():
    src = """
    CurrentUser = Annotated[User, Depends(get_current_active_user)]
    @router.get("/a")
    async def a(user: CurrentUser): ...
    @router.get("/b")
    async def b(user: Annotated[User, Depends(get_current_user)]): ...
    """
    assert _inv1(src, "a") == "VERIFIED"
    assert _inv1(src, "b") == "VERIFIED"


def test_custom_auth_dependencies():
    src = """
    def admin_only(user=Depends(get_current_user)): return user
    @router.delete("/x", dependencies=[Depends(require_role("admin"))])
    async def x(): ...
    @router.get("/y")
    async def y(u=Depends(require_admin)): ...
    @router.get("/z")
    async def z(u=Depends(admin_only)): ...
    """
    assert [_inv1(src, n) for n in "xyz"] == ["VERIFIED"] * 3


def test_include_router_dependencies_across_files():
    main = ast.parse("app.include_router(users_router, dependencies=[Depends(get_current_user)])\n"
                     "from routers.users import router as users_router")
    users = textwrap.dedent("""
    router = APIRouter()
    @router.get("/users")
    async def list_users(): ...
    """)
    included = collect_included_auth({"main": main})
    res = Z3Encoder(ast.parse(users), "users", included).verify_all()
    assert [r.status for r in res if r.invariant_id == "INV-001"] == ["VERIFIED"]


def test_public_marker_constant_and_allowlist():
    src = """
    PUBLIC_ROUTES = ["GET /landing"]
    @router.get("/landing")
    async def landing(): ...
    @public_route
    @router.get("/pricing")
    async def pricing(): ...
    @router.get("/blog")
    async def blog(): ...
    """
    assert _inv1(src, "landing") == "N/A"
    assert _inv1(src, "pricing") == "N/A"
    assert _inv1(src, "blog") == "VIOLATED"
    assert _inv1(src, "blog", public_routes=["/api/blog"]) == "N/A"


def test_truly_unprotected_route_is_still_flagged_even_with_try_except():
    src = """
    @router.get("/secrets")
    async def secrets():
        try:
            return 1
        except Exception:
            return 2
    """
    res = Z3Encoder(ast.parse(textwrap.dedent(src))).verify_all()
    assert next(r for r in res if r.invariant_id == "INV-001").status == "VIOLATED"
    assert all(r.status == "UNVERIFIABLE" for r in res if r.invariant_id != "INV-001")


def test_tenant_filter_with_nested_parentheses_is_found():
    src = """
    @router.get("/t")
    async def t(db=Depends(get_db), u=Depends(get_current_user)):
        q = select(Task).where(and_(Task.org_id == u.org_id, func.lower(Task.title) == "x"))
        return (await db.execute(q)).scalars().all()
    @router.get("/u")
    async def u(db=Depends(get_db)):
        q = select(Task.org_id).where(Task.id == 1)
        return (await db.execute(q)).scalars().all()
    """
    routes = _routes(src)
    assert _check_inv005_tenant_isolation(routes["t"]).status == "VERIFIED"
    assert _check_inv005_tenant_isolation(routes["u"]).status == "VIOLATED"
