"""
Deterministic CRUD, seed, and stats code generators driven by Domain IR.

Extracted from ir_generators.py to keep that file under 600 lines.
Contains generators for:
  - crud.py   (paginated CRUD FastAPI routers for all entities)
  - seed.py   (deterministic realistic seed data — 20 rows per entity)
  - stats.py  (aggregated KPI endpoint: counts, success rate, cost totals)
"""
from __future__ import annotations

import re

from aether_os.core.domain_ir import AetherType, DomainIR, IREntity
from aether_os.phases.p04a_backend_codegen.ir_client_fields import client_fields, is_user_entity  # noqa: F401
from aether_os.phases.p04a_backend_codegen.ir_seed_generator import (  # noqa: F401  (re-exported for callers)
    _seed_value,
    _sort_entities_by_deps,
    generate_seed_py,
    validate_seed_dependencies,
)


# ---------------------------------------------------------------------------
# crud.py generator
# ---------------------------------------------------------------------------

_CRUD_IMPORTS = """\
from __future__ import annotations
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db
from auth import get_current_user
import models, schemas
"""


_ACTIONS = ("read", "create", "update", "delete")

# Default role model for an IR that defines no permissions (decision D1): admin everything, member and
# user read+create+update, viewer read, delete admin-only. Also used by the fallback generator.
DEFAULT_ROLE_MODEL = {
    "read": ["admin", "member", "user", "viewer"],
    "create": ["admin", "member", "user"],
    "update": ["admin", "member", "user"],
    "delete": ["admin"],
}


def _role_sets(ir: DomainIR, entity_name: str) -> dict:
    """
    Build per-action allowed-role sets from ir.permissions for one entity.
    Returns: {"read": ["admin","manager"], "create": ["admin"], ...}

    Deny by default once the IR defines a permission model at all: an action that no grant covers is
    admin-only, and admin is always allowed. Before, an entity or action without a grant had NO guard,
    so any signed-in user could create and delete it (KAN-169). When the IR defines no permissions
    anywhere, DEFAULT_ROLE_MODEL applies (it used to allow every signed-in user everything).
    """
    if not ir.permissions:
        return {k: list(v) for k, v in DEFAULT_ROLE_MODEL.items()}
    mapping: dict = {a: {"admin"} for a in _ACTIONS}
    for perm in ir.permissions:
        if perm.entity.lower() != entity_name.lower():
            continue
        for action in perm.actions:
            mapping.setdefault(str(action).lower(), {"admin"}).add(str(perm.role).lower())
    return {k: sorted(v) for k, v in mapping.items()}


def _role_guard(roles: list) -> list:
    """Return lines that raise 403 unless the caller's role (case-insensitive) is in roles."""
    if not roles:
        return []
    roles_repr = repr([r.lower() for r in roles])
    return [
        f"    if str((current_user.get('role') if isinstance(current_user, dict) else getattr(current_user, 'role', None)) or '').lower() not in {roles_repr}:",
        "        raise HTTPException(status_code=403, detail='Insufficient permissions')",
    ]


def _workflow_guard_lines(entity_name: str, transitions: dict) -> list:
    """
    Return module-level constant + in-handler guard lines for status transition enforcement.
    The constant is emitted once at the top of crud.py (before router definitions).
    The guard lines are injected into the PATCH handler body after the 404 check.
    Returns a tuple (module_lines, handler_lines) via the 'module' and 'handler' keys
    in the returned dict.
    """
    n = entity_name
    const_name = f"_TRANSITIONS_{n.upper()}"
    module_lines = [
        f"{const_name} = {repr(transitions)}",
        "",
    ]
    handler_lines = [
        "    _new_status = data.model_dump(exclude_unset=True).get('status')",
        "    if _new_status is not None and _new_status != obj.status:",
        f"        _allowed = {const_name}.get(obj.status, [])",
        "        if _new_status not in _allowed:",
        "            raise HTTPException(",
        "                status_code=422,",
        "                detail=f'Invalid status transition: {obj.status!r} → {_new_status!r}. Allowed from {obj.status!r}: {_allowed}',",
        "            )",
    ]
    return {"module": module_lines, "handler": handler_lines}


def _entity_router_with_rbac(entity: IREntity, role_map: dict, transitions: dict | None = None, multi_tenancy: bool = False) -> list:
    """Generate CRUD router function definitions for one entity, with optional role guards.

    When `transitions` is provided and the entity has a `status` field, the PATCH
    handler validates status changes against the transition graph and raises HTTP 422
    for disallowed transitions.  When `multi_tenancy` is True, every query is scoped
    to the current user's org_id (which must be present in the JWT as set by auth.py).
    """
    n = entity.name
    t = entity.table
    var = n.lower()
    router_var = f"{t}_router"

    # org_id filter fragments injected when multi_tenancy is enabled.
    _mt = f", models.{n}.org_id == current_user.get('org_id')" if multi_tenancy else ""
    _mt_list = f".where(models.{n}.org_id == current_user.get('org_id'))" if multi_tenancy else ""
    _mt_create = ", org_id=current_user.get('org_id')" if multi_tenancy else ""

    read_guard   = _role_guard(role_map.get("read", []))
    create_guard = _role_guard(role_map.get("create", []))
    update_guard = _role_guard(role_map.get("update", []))
    delete_guard = _role_guard(role_map.get("delete", []))

    # Determine if this entity has a `status` field and if guards should be injected.
    has_status = any(f.name == "status" for f in entity.fields)
    guard_lines: list = []
    module_const_lines: list = []
    if transitions is not None and has_status:
        # Build both the module-level constant and the in-handler guard in one call.
        wg = _workflow_guard_lines(n, transitions)
        module_const_lines = wg["module"]
        guard_lines = wg["handler"]

    lines = [
        *module_const_lines,
        f"{router_var} = APIRouter(prefix='/{t}', tags=['{n}'])",
        "",
        f"@{router_var}.get('', response_model=schemas.PaginatedResponse)",
        f"async def list_{t}(",
        "    page: int = Query(1, ge=1),",
        "    page_size: int = Query(20, ge=1, le=200),",
        "    limit: Optional[int] = Query(None, ge=1, le=200),   # older clients; page_size is the documented name",
        "    db: AsyncSession = Depends(get_db),",
        "    current_user=Depends(get_current_user),",
        "):",
        *read_guard,
        "    size = limit or page_size",
        "    offset = (page - 1) * size",
        f"    total_q = await db.execute(select(func.count()).select_from(models.{n}){_mt_list})",
        "    total = total_q.scalar_one()",
        f"    result = await db.execute(select(models.{n}){_mt_list}.offset(offset).limit(size))",
        f"    items = [schemas.{n}Response.model_validate(o) for o in result.scalars().all()]",
        "    return {'items': items, 'total': total, 'page': page, 'page_size': size, 'limit': size}",
        "",
        f"@{router_var}.post('', response_model=schemas.{n}Response, status_code=201)",
        f"async def create_{var}(",
        f"    data: schemas.{n}Create,",
        "    db: AsyncSession = Depends(get_db),",
        "    current_user: dict = Depends(get_current_user),",
        "):",
        *create_guard,
        f"    obj = models.{n}(**data.model_dump(exclude_unset=True){_mt_create})",
        "    db.add(obj)",
        "    await db.flush()",
        f"    await _log_action(db, str(current_user.get('id', '') if isinstance(current_user, dict) else getattr(current_user, 'id', '')), 'CREATE', '{n}', str(getattr(obj, 'id', '')))",
        "    await db.refresh(obj)",
        "    return obj",
        "",
        f"@{router_var}.get('/{{item_id}}', response_model=schemas.{n}Response)",
        f"async def get_{var}(",
        "    item_id: int,",
        "    db: AsyncSession = Depends(get_db),",
        "    current_user: dict = Depends(get_current_user),",
        "):",
        *read_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id{_mt}))",
        "    obj = result.scalar_one_or_none()",
        "    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        "    return obj",
        "",
        f"@{router_var}.patch('/{{item_id}}', response_model=schemas.{n}Response)",
        f"async def update_{var}(",
        "    item_id: int,",
        f"    data: schemas.{n}Update,",
        "    db: AsyncSession = Depends(get_db),",
        "    current_user: dict = Depends(get_current_user),",
        "):",
        *update_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id{_mt}))",
        "    obj = result.scalar_one_or_none()",
        "    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        *guard_lines,
        "    for k, v in data.model_dump(exclude_unset=True).items():",
        "        setattr(obj, k, v)",
        "    await db.flush()",
        f"    await _log_action(db, str(current_user.get('id', '') if isinstance(current_user, dict) else getattr(current_user, 'id', '')), 'UPDATE', '{n}', str(item_id))",
        "    await db.refresh(obj)",
        "    return obj",
        "",
        f"@{router_var}.put('/{{item_id}}', response_model=schemas.{n}Response, include_in_schema=False)",
        f"async def update_{var}_put(item_id: int, data: schemas.{n}Update, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
        f"    return await update_{var}(item_id, data, db, current_user)",
        "",
        f"@{router_var}.delete('/{{item_id}}', status_code=204)",
        f"async def delete_{var}(",
        "    item_id: int,",
        "    db: AsyncSession = Depends(get_db),",
        "    current_user: dict = Depends(get_current_user),",
        "):",
        *delete_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id{_mt}))",
        "    obj = result.scalar_one_or_none()",
        "    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        f"    await _log_action(db, str(current_user.get('id', '') if isinstance(current_user, dict) else getattr(current_user, 'id', '')), 'DELETE', '{n}', str(item_id))",
        "    await db.delete(obj)",
        "",
    ]

    return lines


def generate_crud_py(ir: DomainIR, workflow_transitions: dict | None = None, multi_tenancy: bool = False) -> str:
    """Generate complete routers/crud.py from DomainIR.

    Args:
        ir: The Domain IR describing all entities, permissions, and workflows.
        workflow_transitions: Optional dict mapping PascalCase entity name → transition
            graph (dict[str, list[str]]).  When provided, PATCH handlers for entities
            that have a ``status`` field will validate the requested status change
            against the allowed transitions and raise HTTP 422 on invalid moves.
        multi_tenancy: When True, every query is scoped to current_user['org_id'].
    """
    # Build schema imports list
    schema_imports = []
    for entity in (e for e in ir.entities if not is_user_entity(e)):
        schema_imports.append(f"{entity.name}Create, {entity.name}Update")

    schema_import_line = f"from schemas import {', '.join(schema_imports)}" if schema_imports else ""

    lines = [
        "from __future__ import annotations",
        "from typing import List, Optional",
        "from fastapi import APIRouter, Depends, HTTPException, Query, status",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select, func",
        "from database import get_db",
        "from auth import get_current_user",
        "import models",
        "import schemas",
        schema_import_line,
        "try:",
        "    from services.audit_service import log_action as _log_action",
        "except ImportError:",
        "    async def _log_action(*a, **kw): pass",
        "",
    ]

    for entity in (e for e in ir.entities if not is_user_entity(e)):
        role_map = _role_sets(ir, entity.name)
        entity_transitions = (workflow_transitions or {}).get(entity.name)
        lines.extend(_entity_router_with_rbac(entity, role_map, transitions=entity_transitions, multi_tenancy=multi_tenancy))

    # all_routers list — every entity gets included
    router_vars = [f"{e.table}_router" for e in ir.entities if not is_user_entity(e)]
    lines.append(f"all_routers = [{', '.join(router_vars)}]")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# stats.py router  (Gap 4 — computed KPI aggregates for dashboard)
# ---------------------------------------------------------------------------

def generate_stats_router(ir: DomainIR, multi_tenancy: bool = False) -> str:
    """Generate routers/stats.py with a /stats endpoint that returns real aggregates.

    multi_tenancy: every count and sum is limited to the caller's org_id (KAN-169); before, /stats counted
    every tenant's rows."""
    domain_entities = [e for e in ir.entities if e.name != "User" and getattr(e, "table", "") != "users"]

    lines = [
        "from __future__ import annotations",
        "from fastapi import APIRouter, Depends",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select, func",
        "from database import get_db",
        "from auth import get_current_user",
        "import models",
        "",
        "router = APIRouter(prefix='/stats', tags=['Stats'])",
        "",
        "",
        "@router.get('')",
        "async def get_stats(",
        "    db: AsyncSession = Depends(get_db),",
        "    current_user=Depends(get_current_user),",
        "):",
        "    stats: dict = {}",
        *(["    _org = current_user.get('org_id')", ""] if multi_tenancy else [""]),
    ]
    _m = lambda e: f", models.{e.name}.org_id == _org" if multi_tenancy else ""           # extra where() terms
    _w = lambda e: f".where(models.{e.name}.org_id == _org)" if multi_tenancy else ""     # a where() on its own

    # Count per entity
    for entity in domain_entities:
        lines += [
            f"    _r = await db.execute(select(func.count()).select_from(models.{entity.name}){_w(entity)})",
            f"    stats['total_{entity.table}'] = _r.scalar_one()",
        ]

    lines.append("")

    # Success rate and stage breakdown: find entity with a 'status' or 'stage' field
    status_entity = next(
        (e for e in domain_entities if any(f.name in ("status", "stage") for f in e.fields)),
        None,
    )
    if status_entity:
        status_field = next(f for f in status_entity.fields if f.name in ("status", "stage"))
        lines += [
            f"    # Stats breakdown from {status_entity.name}.{status_field.name}",
            f"    _total_r = await db.execute(select(func.count()).select_from(models.{status_entity.name}){_w(status_entity)})",
            "    _total_n = _total_r.scalar_one()",
            f"    stats['total_{status_entity.table}'] = _total_n",
        ]

        if status_field.enum_values:
            # Enum values are free text from the model ("To do", "Won't fix"): the variable name is a sanitised slug plus
            # its index (unique, never starts with a digit) and the value is a Python literal via repr(). Pasting the raw
            # value produced `_stage_to do_r = ...`, a SyntaxError that failed Stage 3 on production (22 Nov 2026).
            for idx, val in enumerate(status_field.enum_values):
                slug = re.sub(r"\W+", "_", str(val).lower()).strip("_") or "value"
                var = f"_stage_{idx}_{slug}_r"
                lines += [
                    f"    {var} = await db.execute(",
                    f"        select(func.count()).select_from(models.{status_entity.name})",
                    f"        .where(models.{status_entity.name}.{status_field.name} == {str(val)!r}{_m(status_entity)})",
                    "    )",
                    f"    stats[{('stage_' + slug)!r}] = {var}.scalar_one()",
                ]

        lines += [
            "    _succ_r = await db.execute(",
            f"        select(func.count()).select_from(models.{status_entity.name})",
            f"        .where(models.{status_entity.name}.{status_field.name}.in_(['success', 'completed', 'done', 'active', 'Won']){_m(status_entity)})",
            "    )",
            "    _succ_n = _succ_r.scalar_one()",
            "    stats['success_rate'] = round(_succ_n / _total_n * 100, 2) if _total_n else 0.0",
            "",
        ]

    # Cost/amount sum: find entity with a numeric cost-like field
    cost_entity = None
    cost_field = None
    for entity in domain_entities:
        for f in entity.fields:
            if f.type in (AetherType.DECIMAL, AetherType.INTEGER) and any(
                k in f.name.lower() for k in ("cost", "amount", "price", "revenue", "fee", "salary")
            ):
                cost_entity = entity
                cost_field = f
                break
        if cost_entity:
            break

    if cost_entity and cost_field:
        lines += [
            f"    # Total cost from {cost_entity.name}.{cost_field.name}",
            f"    _cost_r = await db.execute(select(func.sum(models.{cost_entity.name}.{cost_field.name})){_w(cost_entity)})",
            "    stats['total_cost'] = float(_cost_r.scalar_one() or 0.0)",
            "",
        ]

    lines += [
        "    return stats",
    ]

    return "\n".join(lines) + "\n"
