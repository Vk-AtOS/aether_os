"""
Deterministic CRUD, seed, and stats code generators driven by Domain IR.

Extracted from ir_generators.py to keep that file under 600 lines.
Contains generators for:
  - crud.py   (paginated CRUD FastAPI routers for all entities)
  - seed.py   (deterministic realistic seed data — 20 rows per entity)
  - stats.py  (aggregated KPI endpoint: counts, success rate, cost totals)
"""
from __future__ import annotations

from aether_os.core.domain_ir import AetherType, DomainIR, IREntity, IRField


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
        f"        raise HTTPException(status_code=403, detail='Insufficient permissions')",
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
        f"    _new_status = data.model_dump(exclude_unset=True).get('status')",
        f"    if _new_status is not None and _new_status != obj.status:",
        f"        _allowed = {const_name}.get(obj.status, [])",
        f"        if _new_status not in _allowed:",
        f"            raise HTTPException(",
        f"                status_code=422,",
        f"                detail=f'Invalid status transition: {{obj.status!r}} → {{_new_status!r}}. Allowed from {{obj.status!r}}: {{_allowed}}',",
        f"            )",
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
    _mt_create = f", org_id=current_user.get('org_id')" if multi_tenancy else ""

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
        f"    page: int = Query(1, ge=1),",
        f"    limit: int = Query(20, ge=1, le=100),",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user=Depends(get_current_user),",
        f"):",
        *read_guard,
        f"    offset = (page - 1) * limit",
        f"    total_q = await db.execute(select(func.count()).select_from(models.{n}){_mt_list})",
        f"    total = total_q.scalar_one()",
        f"    result = await db.execute(select(models.{n}){_mt_list}.offset(offset).limit(limit))",
        f"    items = [schemas.{n}Response.model_validate(o) for o in result.scalars().all()]",
        f"    return {{'items': items, 'total': total, 'page': page, 'limit': limit}}",
        "",
        f"@{router_var}.post('', response_model=schemas.{n}Response, status_code=201)",
        f"async def create_{var}(",
        f"    data: schemas.{n}Create,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user: dict = Depends(get_current_user),",
        f"):",
        *create_guard,
        f"    obj = models.{n}(**data.model_dump(exclude_unset=True){_mt_create})",
        f"    db.add(obj)",
        f"    await db.flush()",
        f"    await _log_action(db, str(current_user.get('id', '') if isinstance(current_user, dict) else getattr(current_user, 'id', '')), 'CREATE', '{n}', str(getattr(obj, 'id', '')))",
        f"    await db.refresh(obj)",
        f"    return obj",
        "",
        f"@{router_var}.get('/{{item_id}}', response_model=schemas.{n}Response)",
        f"async def get_{var}(",
        f"    item_id: int,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user: dict = Depends(get_current_user),",
        f"):",
        *read_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id{_mt}))",
        f"    obj = result.scalar_one_or_none()",
        f"    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        f"    return obj",
        "",
        f"@{router_var}.patch('/{{item_id}}', response_model=schemas.{n}Response)",
        f"async def update_{var}(",
        f"    item_id: int,",
        f"    data: schemas.{n}Update,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user: dict = Depends(get_current_user),",
        f"):",
        *update_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id{_mt}))",
        f"    obj = result.scalar_one_or_none()",
        f"    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        *guard_lines,
        f"    for k, v in data.model_dump(exclude_unset=True).items():",
        f"        setattr(obj, k, v)",
        f"    await db.flush()",
        f"    await _log_action(db, str(current_user.get('id', '') if isinstance(current_user, dict) else getattr(current_user, 'id', '')), 'UPDATE', '{n}', str(item_id))",
        f"    await db.refresh(obj)",
        f"    return obj",
        "",
        f"@{router_var}.put('/{{item_id}}', response_model=schemas.{n}Response, include_in_schema=False)",
        f"async def update_{var}_put(item_id: int, data: schemas.{n}Update, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
        f"    return await update_{var}(item_id, data, db, current_user)",
        "",
        f"@{router_var}.delete('/{{item_id}}', status_code=204)",
        f"async def delete_{var}(",
        f"    item_id: int,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user: dict = Depends(get_current_user),",
        f"):",
        *delete_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id{_mt}))",
        f"    obj = result.scalar_one_or_none()",
        f"    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        f"    await _log_action(db, str(current_user.get('id', '') if isinstance(current_user, dict) else getattr(current_user, 'id', '')), 'DELETE', '{n}', str(item_id))",
        f"    await db.delete(obj)",
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
    for entity in ir.entities:
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

    for entity in ir.entities:
        role_map = _role_sets(ir, entity.name)
        entity_transitions = (workflow_transitions or {}).get(entity.name)
        lines.extend(_entity_router_with_rbac(entity, role_map, transitions=entity_transitions, multi_tenancy=multi_tenancy))

    # all_routers list — every entity gets included
    router_vars = [f"{e.table}_router" for e in ir.entities]
    lines.append(f"all_routers = [{', '.join(router_vars)}]")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# seed.py generator  (Gap 1 — realistic deterministic data, no LLM needed)
# ---------------------------------------------------------------------------

_SEED_ADJECTIVES = [
    "Premier", "Advanced", "Elite", "Core", "Prime",
    "Pro", "Standard", "Enterprise", "Express", "Global",
]
_SEED_NAMES = [
    "Alpha", "Beta", "Gamma", "Delta", "Epsilon",
    "Zeta", "Eta", "Theta", "Iota", "Kappa",
]


def _seed_value(
    field: IRField,
    idx: int,
    entity_name: str,
    seed_vocabulary: dict | None = None,
    domain: str = "general",
    project_name: str = "",
) -> str:
    """Return a Python literal for a single seed value.

    When seed_vocabulary contains domain-specific terms for this entity (or domain),
    name/title/label fields use those terms instead of generic Alpha/Beta/Gamma.
    The project_name prefix is prepended to make records easily attributable in logs.
    """
    n = field.name.lower()
    t = field.type
    vocab = seed_vocabulary or {}

    if t == AetherType.FK:
        return str((idx % 3) + 1)
    if t == AetherType.BOOLEAN:
        return "True"
    if t == AetherType.INTEGER:
        if any(k in n for k in ("max", "limit", "budget")):
            return str([10, 20, 50, 100, 200][idx % 5])
        if any(k in n for k in ("count", "qty", "quantity")):
            return str([1, 2, 3, 5, 8][idx % 5])
        if "age" in n:
            return str(25 + idx * 3)
        return str([1, 2, 3, 5, 10][idx % 5])
    if t == AetherType.DECIMAL:
        if any(k in n for k in ("price", "amount", "budget", "cost", "salary")):
            return repr([99.99, 149.99, 299.99, 49.99, 199.99][idx % 5])
        if "rate" in n:
            return repr([0.05, 0.1, 0.15, 0.2, 0.08][idx % 5])
        return repr([10.0, 25.0, 50.0, 100.0, 75.0][idx % 5])
    if t == AetherType.EMAIL:
        return repr(f"user{idx + 1}@example.com")
    if t == AetherType.URL:
        return repr(f"https://example.com/{entity_name.lower()}-{idx + 1}")
    if t == AetherType.DATE:
        return f"date(2024, {(idx % 12) + 1}, {(idx % 28) + 1})"
    if t in (AetherType.DATETIME,):
        return f"datetime(2024, {(idx % 12) + 1}, {(idx % 28) + 1}, tzinfo=timezone.utc)"
    if t == AetherType.ENUM and field.enum_values:
        return repr(field.enum_values[idx % len(field.enum_values)])
    if t == AetherType.TEXT:
        return repr(f"Sample description for {entity_name} record {idx + 1}.")

    # STRING — field-name-aware defaults
    if any(k in n for k in ("name", "title", "label")):
        # Use domain-specific vocabulary when available (prefer entity → domain → generic)
        vocab_list = vocab.get(entity_name, vocab.get(entity_name.lower(), vocab.get(domain, [])))
        if vocab_list:
            term = vocab_list[idx % len(vocab_list)]
            prefix = f"{project_name} " if project_name else ""
            return repr(f"{prefix}{term}")
        prefix = f"{project_name} " if project_name else ""
        return repr(f"{prefix}{_SEED_ADJECTIVES[idx % len(_SEED_ADJECTIVES)]} {entity_name} {idx + 1}")
    if "slug" in n:
        return repr(f"{entity_name.lower()}-{idx + 1}")
    if "phone" in n:
        return repr(f"+1-555-{100 + idx:03d}-{1000 + idx:04d}")
    if "address" in n:
        return repr(f"{100 + idx * 10} Main Street, City {idx + 1}")
    if "status" in n:
        return repr(["active", "active", "active", "inactive", "pending"][idx % 5])
    if "type" in n:
        return repr(["standard", "premium", "basic", "enterprise", "free"][idx % 5])
    if "category" in n:
        return repr(["General", "Support", "Billing", "Technical", "Other"][idx % 5])
    if "priority" in n:
        return repr(["low", "medium", "high", "critical", "medium"][idx % 5])
    if "plan" in n:
        return repr(["free", "pro", "enterprise", "basic", "premium"][idx % 5])
    if "model" in n:
        return repr(["gpt-4", "claude-3", "llama-2", "gemini", "gpt-3.5"][idx % 5])
    if "role" in n:
        return repr(["admin", "manager", "user", "viewer", "editor"][idx % 5])
    if "color" in n:
        return repr(["blue", "green", "red", "purple", "orange"][idx % 5])
    return repr(f"{entity_name} {_SEED_NAMES[idx % len(_SEED_NAMES)]}")


def _sort_entities_by_deps(entities: list) -> list:
    """Topological sort of entities based on FK dependencies."""
    sorted_entities: list = []
    visited: set = set()
    temp_visited: set = set()

    entity_map = {e.name: e for e in entities}

    def visit(name: str) -> None:
        if name in temp_visited:
            return  # Cycle or already handled
        if name not in visited:
            temp_visited.add(name)
            ent = entity_map.get(name)
            if ent:
                for f in ent.fields:
                    if f.type == AetherType.FK and f.ref_entity and f.ref_entity != name:
                        visit(f.ref_entity)
            temp_visited.remove(name)
            visited.add(name)
            if ent:
                sorted_entities.append(ent)

    for e in entities:
        visit(e.name)
    return sorted_entities


def generate_seed_py(
    ir: DomainIR,
    seed_vocabulary: dict | None = None,
    domain: str = "general",
    project_name: str = "",
    multi_tenancy: bool = False,
) -> str:
    """Generate complete deterministic seed.py from DomainIR (20 rows per entity).

    Args:
        ir: Domain IR with all entities and fields.
        seed_vocabulary: Optional dict mapping entity name (or domain) → list of
            domain-specific terms used as name/title/label values (e.g.
            {"Policy": ["GDPR Alert", "HIPAA Baseline", ...], ...}).
        domain: Domain string used as a vocabulary fallback key when no entity-
            specific terms exist (e.g. "insurance", "legal").
        project_name: Prepended to seed record names for traceability
            (e.g. "PolicyLens GDPR Alert" instead of "Premier Policy 1").
    """
    domain_entities = [e for e in ir.entities if e.name != "User" and getattr(e, "table", "") != "users"]
    domain_entities = _sort_entities_by_deps(domain_entities)
    entity_names = [e.name for e in domain_entities]
    vocab = seed_vocabulary or {}

    lines = [
        "from __future__ import annotations",
        "import logging",
        "import os",
        "from datetime import date, datetime, timezone",
        "from sqlalchemy import select, func",
        "from database import AsyncSessionLocal",
        "from auth import get_password_hash",
        "from models import User",
    ]
    if entity_names:
        lines.append(f"from models import {', '.join(entity_names)}")
    lines += [
        "",
        "_logger = logging.getLogger(__name__)",
        'def _admin_password() -> str:',
        '    # ADMIN_PASSWORD from the environment, else a random one written once to a 0600 file.',
        '    # Never a known default, and never logged.',
        "    pw = os.environ.get('ADMIN_PASSWORD')",
        '    if pw:',
        '        return pw',
        '    import secrets',
        '    pw = secrets.token_urlsafe(16)',
        "    path = os.path.join(os.getcwd(), 'admin_initial_password.txt')",
        '    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)',
        "    with os.fdopen(fd, 'w') as f:",
        '        f.write(pw)',
        "    _logger.warning('ADMIN_PASSWORD is not set: a random admin password was written to %s', path)",
        '    return pw',
        "",
        "",
        "async def seed_database() -> None:",
        "    async with AsyncSessionLocal() as db:",
        "        count = (await db.execute(select(func.count()).select_from(User))).scalar_one()",
        "        if count > 0:",
        "            return",
        "",
        "        admin = User(",
        "            email='admin@example.com',",
        "            password_hash=get_password_hash(_admin_password()),",
        "            role='admin',",
        "            is_active=True,",
        *(["            org_id='default',"] if multi_tenancy else []),
        "        )",
        "        db.add(admin)",
        "        await db.flush()",
        "",
    ]

    for entity in domain_entities:
        lines.append(f"        db.add_all([")
        for idx in range(20):
            field_parts = []
            for f in entity.fields:
                if f.name in ("id", "created_at", "updated_at"):
                    continue
                val = _seed_value(
                    f, idx, entity.name,
                    seed_vocabulary=vocab,
                    domain=domain,
                    project_name=project_name,
                )
                field_parts.append(f"                {f.name}={val},")
            lines.append(f"            {entity.name}(")
            if multi_tenancy:
                field_parts.append("                org_id='default',")
            lines.extend(field_parts)
            lines.append("            ),")
        lines.append("        ])")
        lines.append("")

    lines += [
        "        await db.commit()",
        "        _logger.info('Seeded admin user admin@example.com')",
    ]
    return "\n".join(lines) + "\n"


async def validate_seed_dependencies(db_session) -> list:
    """Verify that all FK references in the database point to existing records."""
    # Structural check placeholder — in production this would iterate all tables and FKs.
    return []


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
            f"    _total_n = _total_r.scalar_one()",
            f"    stats['total_{status_entity.table}'] = _total_n",
        ]

        if status_field.enum_values:
            for val in status_field.enum_values:
                lines += [
                    f"    _stage_{val.lower()}_r = await db.execute(",
                    f"        select(func.count()).select_from(models.{status_entity.name})",
                    f"        .where(models.{status_entity.name}.{status_field.name} == '{val}'{_m(status_entity)})",
                    f"    )",
                    f"    stats['stage_{val.lower()}'] = _stage_{val.lower()}_r.scalar_one()",
                ]

        lines += [
            f"    _succ_r = await db.execute(",
            f"        select(func.count()).select_from(models.{status_entity.name})",
            f"        .where(models.{status_entity.name}.{status_field.name}.in_(['success', 'completed', 'done', 'active', 'Won']){_m(status_entity)})",
            f"    )",
            f"    _succ_n = _succ_r.scalar_one()",
            f"    stats['success_rate'] = round(_succ_n / _total_n * 100, 2) if _total_n else 0.0",
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
            f"    stats['total_cost'] = float(_cost_r.scalar_one() or 0.0)",
            "",
        ]

    lines += [
        "    return stats",
    ]

    return "\n".join(lines) + "\n"
