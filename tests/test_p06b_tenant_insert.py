"""Production run 22 (22 Nov 2026): s05 failed on INV-005 for the generated users router's create_user. It stamps the
admin's org_id on the new row and checks email uniqueness across all tenants; an INSERT is not a tenant query."""
import ast

from aether_os.phases.p04a_backend_codegen.templates_users import _USERS_ROUTER_PY
from aether_os.phases.p06b_formal_verification.z3_encoder import Z3Encoder

_SRC = '''
from fastapi import APIRouter, Depends
router = APIRouter()

@router.post("/items")
async def create_item(data: ItemIn, db=Depends(get_db), user=Depends(get_current_user)):
    taken = await db.execute(select(Item.id).where(Item.code == data.code))
    extra = {}
    extra["org_id"] = user["org_id"]
    item = Item(name=data.name, org_id=user["org_id"], **extra)
    item.tenant_id = user["org_id"]
    db.add(item)
    return item

@router.get("/items")
async def leaky_list(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.execute(select(Item))
    return [r for r in rows.scalars() if r.org_id]

@router.get("/scoped")
async def scoped_list(db=Depends(get_db), user=Depends(get_current_user)):
    return (await db.execute(select(Item).where(Item.org_id == user["org_id"]))).scalars().all()

@router.get("/by")
async def filter_by_list(db=Depends(get_db), user=Depends(get_current_user)):
    return (await db.execute(select(Item).filter_by(org_id=user["org_id"]))).scalars().all()
'''


def _inv005(src):
    return {r.route_name: r.status for r in Z3Encoder(ast.parse(src)).verify_all() if r.invariant_id == "INV-005"}


def test_insert_that_stamps_the_tenant_is_not_a_tenant_query():
    assert _inv005(_SRC)["create_item"] == "N/A"


def test_reads_without_a_tenant_filter_are_still_violations():
    assert _inv005(_SRC)["leaky_list"] == "VIOLATED"


def test_where_and_filter_by_on_the_tenant_column_verify():
    found = _inv005(_SRC)
    assert found["scoped_list"] == "VERIFIED"
    assert found["filter_by_list"] == "VERIFIED"


def test_generated_users_router_has_no_inv005_violation():
    found = _inv005(_USERS_ROUTER_PY)
    assert found and "VIOLATED" not in found.values(), found
