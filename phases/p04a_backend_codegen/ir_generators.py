"""
Deterministic backend code generators driven by Domain IR.

No LLM involved. Given a validated DomainIR, these functions generate:
  - models.py   (SQLAlchemy ORM models for all entities)
  - schemas.py  (Pydantic v2 Base/Create/Update/Response schemas)
  - crud.py     (paginated CRUD FastAPI routers for all entities)
  - seed.py     (deterministic realistic seed data — 5 rows per entity)
  - stats.py    (aggregated KPI endpoint: counts, success rate, cost totals)

The generated code is structurally correct by construction — not dependent on
any model's ability to write Python.
"""
from __future__ import annotations

from aether_os.core.domain_ir import AetherType, DomainIR, IREntity, IRField, SA_TYPE_MAP

# ---------------------------------------------------------------------------
# models.py generator
# ---------------------------------------------------------------------------

_SA_IMPORTS = """\
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, JSON
from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import relationship
from database import Base
"""


def _pluralise(word: str) -> str:
    """English pluralisation for SQLAlchemy table names."""
    w = word.lower()
    if w.endswith("ies") or w.endswith("ses") or w.endswith("xes") or w.endswith("ches") or w.endswith("shes"):
        return w  # already plural
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        return w[:-1] + "ies"
    if w.endswith("ss") or w.endswith("sh") or w.endswith("ch") or w.endswith("x") or w.endswith("z"):
        return w + "es"
    if w.endswith("s"):
        return w  # already plural
    return w + "s"


def _ref_to_table_name(ref: str) -> str:
    """Convert PascalCase entity ref to snake_case plural table name.
    'Class' → 'classes', 'MembershipPlan' → 'membership_plans'
    """
    snake = "".join(
        ["_" + c.lower() if c.isupper() else c for c in ref]
    ).lstrip("_")
    return _pluralise(snake)


def _sa_column(field: IRField) -> str:
    """Return SQLAlchemy Column(...) definition for one IRField."""
    atype = field.type

    # Build column type string
    if atype == AetherType.FK:
        ref = field.ref_entity or "users"
        table_name = _ref_to_table_name(ref)
        col_type = f"Integer, ForeignKey('{table_name}.id')"
    elif atype == AetherType.EMAIL:
        col_type = "String(320)"
    elif atype == AetherType.URL:
        col_type = "String(2048)"
    elif atype == AetherType.ENUM:
        col_type = "String(50)"
    elif atype == AetherType.STRING:
        col_type = "String(255)"
    elif atype == AetherType.DECIMAL:
        col_type = "Numeric(14, 2)"
    else:
        col_type = SA_TYPE_MAP.get(atype, "String(255)")

    parts = [col_type]
    if not field.nullable:
        parts.append("nullable=False")
    if field.unique:
        parts.append("unique=True")
    if field.index:
        parts.append("index=True")
    if field.default is not None and atype == AetherType.BOOLEAN:
        parts.append(f"default={str(field.default).capitalize()}")

    return f"    {field.name} = Column({', '.join(parts)})"


def _relationship_line(field: IRField) -> str | None:
    """Return an ORM relationship() line for an FK field."""
    if field.type != AetherType.FK or not field.ref_entity:
        return None
    return f"    {field.ref_entity.lower()} = relationship('{field.ref_entity}', back_populates=None, lazy='select')"


import re as _re


def _sql_check_constraints(entity_name: str, rules: list) -> list[str]:
    """
    Convert IRBusinessRule expressions to SQLAlchemy CheckConstraint strings.
    Handles patterns: field op value, field op field (e.g. 'salary > 0').
    Returns list of CheckConstraint(...) strings for __table_args__.
    """
    constraints = []
    sql_op_pattern = _re.compile(
        r'^(\w+)\s*(>=|<=|!=|>|<|=)\s*(.+)$'
    )
    for rule in rules:
        if rule.entity != entity_name:
            continue
        m = sql_op_pattern.match(rule.expression.strip())
        if m:
            expr = rule.expression.strip()
            cname = f"ck_{entity_name.lower()}_{rule.name}"[:63]
            constraints.append(f"        CheckConstraint('{expr}', name='{cname}')")
    return constraints


_USER_MODEL = """\
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(320), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default='user')
    is_active = Column(Boolean, nullable=False, default=True)
    full_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
"""


def generate_models_py(ir: DomainIR) -> str:
    """Generate complete models.py from DomainIR."""
    lines = [_SA_IMPORTS, ""]

    # Always emit User model first so auth router import works
    lines.append(_USER_MODEL)

    for entity in ir.entities:
        # Skip User — always emitted above from _USER_MODEL to avoid duplicate table
        if entity.name == "User" or getattr(entity, "table", "") == "users":
            continue
        constraints = _sql_check_constraints(entity.name, ir.business_rules)
        lines.append(f"class {entity.name}(Base):")
        lines.append(f"    __tablename__ = '{entity.table}'")
        if constraints:
            lines.append("    __table_args__ = (")
            for c in constraints:
                lines.append(c + ",")
            lines.append("    )")
        lines.append("")
        lines.append("    id = Column(Integer, primary_key=True, index=True)")
        for f in entity.fields:
            lines.append(_sa_column(f))
        lines.append("    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))")
        lines.append("    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# schemas.py generator
# ---------------------------------------------------------------------------

_PYDANTIC_IMPORTS = """\
from __future__ import annotations
from datetime import date, datetime
from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr, field_validator
"""


def _pydantic_type(field: IRField) -> str:
    """Return the Python/Pydantic type annotation for an IRField."""
    atype = field.type
    type_map = {
        AetherType.STRING:   "str",
        AetherType.TEXT:     "str",
        AetherType.INTEGER:  "int",
        AetherType.DECIMAL:  "float",
        AetherType.BOOLEAN:  "bool",
        AetherType.DATE:     "date",
        AetherType.DATETIME: "datetime",
        AetherType.EMAIL:    "EmailStr",
        AetherType.URL:      "str",
        AetherType.ENUM:     "str",
        AetherType.FK:       "int",
        AetherType.JSON:     "Any",
    }
    base = type_map.get(atype, "str")
    if field.nullable:
        return f"Optional[{base}]"
    return base


_VALIDATOR_OP_MAP = {">": ">", ">=": ">=", "<": "<", "<=": "<=", "!=": "!=", "=": "=="}
_VALIDATOR_EXPR_RE = _re.compile(r'^(\w+)\s*(>=|<=|!=|>|<|=)\s*([0-9.]+)$')


def _pydantic_validators(entity_name: str, rules: list) -> list[str]:
    """
    Generate @field_validator methods for simple scalar constraints
    (e.g. 'salary > 0', 'age >= 18') on numeric fields.
    """
    validators = []
    for rule in rules:
        if rule.entity != entity_name:
            continue
        m = _VALIDATOR_EXPR_RE.match(rule.expression.strip())
        if not m:
            continue
        field_name, op, raw_val = m.group(1), m.group(2), m.group(3)
        py_op = _VALIDATOR_OP_MAP.get(op, op)
        try:
            val = int(raw_val) if "." not in raw_val else float(raw_val)
        except ValueError:
            continue
        msg = rule.error_message or f"{field_name} must be {op} {val}"
        vname = f"check_{rule.name}"
        validators += [
            f"    @field_validator('{field_name}', mode='before')",
            f"    @classmethod",
            f"    def {vname}(cls, v):",
            f"        if v is not None and not (v {py_op} {val}):",
            f"            raise ValueError({msg!r})",
            f"        return v",
            "",
        ]
    return validators


def generate_schemas_py(ir: DomainIR) -> str:
    """Generate complete schemas.py from DomainIR."""
    lines = [_PYDANTIC_IMPORTS, ""]

    for entity in ir.entities:
        name = entity.name
        fields_block_base = []
        fields_block_update = []

        for f in entity.fields:
            ptype = _pydantic_type(f)
            if f.nullable:
                default = " = None"
            elif f.default is not None and f.type == AetherType.BOOLEAN:
                default = f" = {str(f.default).capitalize()}"
            else:
                default = ""
            optional_ptype = f"Optional[{ptype.replace('Optional[', '').rstrip(']')}]"
            fields_block_base.append(f"    {f.name}: {ptype}{default}")
            fields_block_update.append(f"    {f.name}: {optional_ptype} = None")

        validators = _pydantic_validators(name, ir.business_rules)

        # Base
        lines.append(f"class {name}Base(BaseModel):")
        if fields_block_base:
            lines.extend(fields_block_base)
        else:
            lines.append("    pass")
        if validators:
            lines.append("")
            lines.extend(validators)
        lines.append("")

        # Create
        lines.append(f"class {name}Create({name}Base):")
        lines.append("    pass")
        lines.append("")

        # Update
        lines.append(f"class {name}Update(BaseModel):")
        if fields_block_update:
            lines.extend(fields_block_update)
        else:
            lines.append("    pass")
        lines.append("")

        # Response
        lines.append(f"class {name}Response({name}Base):")
        lines.append("    id: int")
        lines.append("    created_at: datetime")
        lines.append("    updated_at: datetime")
        lines.append("    model_config = {'from_attributes': True}")
        lines.append("")

    return "\n".join(lines)


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



def _role_sets(ir: DomainIR, entity_name: str) -> dict[str, list[str]]:
    """
    Build per-action allowed-role sets from ir.permissions for one entity.
    Returns: {"read": ["admin","manager"], "create": ["admin"], ...}
    Only populated when the IR actually defines restrictions (empty = allow all).
    """
    mapping: dict[str, set[str]] = {}
    for perm in ir.permissions:
        if perm.entity.lower() != entity_name.lower():
            continue
        for action in perm.actions:
            mapping.setdefault(action, set()).add(perm.role)
    return {k: sorted(v) for k, v in mapping.items()}


def _role_guard(roles: list[str]) -> list[str]:
    """Return lines that raise 403 unless current_user.role in roles."""
    if not roles:
        return []
    roles_repr = repr(roles)
    return [
        f"    if getattr(current_user, 'role', None) not in {roles_repr}:",
        f"        raise HTTPException(status_code=403, detail='Insufficient permissions')",
    ]


def _entity_router_with_rbac(entity: IREntity, role_map: dict[str, list[str]]) -> list[str]:
    """Generate CRUD router function definitions for one entity, with optional role guards."""
    n = entity.name
    t = entity.table
    var = n.lower()
    router_var = f"{t}_router"

    read_guard   = _role_guard(role_map.get("read", []))
    create_guard = _role_guard(role_map.get("create", []))
    update_guard = _role_guard(role_map.get("update", []))
    delete_guard = _role_guard(role_map.get("delete", []))

    def _g(guard: list[str]) -> str:
        return ("\n" + "\n".join(guard) + "\n") if guard else ""

    lines = [
        f"{router_var} = APIRouter(prefix='/{t}', tags=['{n}'])",
        "",
        f"@{router_var}.get('', response_model=dict)",
        f"async def list_{t}(",
        f"    page: int = Query(1, ge=1),",
        f"    limit: int = Query(20, ge=1, le=100),",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user=Depends(get_current_user),",
        f"):",
        *read_guard,
        f"    offset = (page - 1) * limit",
        f"    total_q = await db.execute(select(func.count()).select_from(models.{n}))",
        f"    total = total_q.scalar_one()",
        f"    result = await db.execute(select(models.{n}).offset(offset).limit(limit))",
        f"    items = result.scalars().all()",
        f"    return {{'items': [schemas.{n}Response.model_validate(i) for i in items], 'total': total, 'page': page, 'limit': limit}}",
        "",
        f"@{router_var}.post('', response_model=schemas.{n}Response, status_code=201)",
        f"async def create_{var}(",
        f"    payload: schemas.{n}Create,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user=Depends(get_current_user),",
        f"):",
        *create_guard,
        f"    obj = models.{n}(**payload.model_dump(exclude_unset=True))",
        f"    db.add(obj)",
        f"    await db.flush()",
        f"    await db.refresh(obj)",
        f"    return schemas.{n}Response.model_validate(obj)",
        "",
        f"@{router_var}.get('/{{item_id}}', response_model=schemas.{n}Response)",
        f"async def get_{var}(",
        f"    item_id: int,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user=Depends(get_current_user),",
        f"):",
        *read_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id))",
        f"    obj = result.scalar_one_or_none()",
        f"    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        f"    return schemas.{n}Response.model_validate(obj)",
        "",
        f"@{router_var}.patch('/{{item_id}}', response_model=schemas.{n}Response)",
        f"async def update_{var}(",
        f"    item_id: int,",
        f"    payload: schemas.{n}Update,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user=Depends(get_current_user),",
        f"):",
        *update_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id))",
        f"    obj = result.scalar_one_or_none()",
        f"    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        f"    for k, v in payload.model_dump(exclude_unset=True).items():",
        f"        setattr(obj, k, v)",
        f"    await db.flush()",
        f"    await db.refresh(obj)",
        f"    return schemas.{n}Response.model_validate(obj)",
        "",
        f"@{router_var}.delete('/{{item_id}}', status_code=204)",
        f"async def delete_{var}(",
        f"    item_id: int,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user=Depends(get_current_user),",
        f"):",
        *delete_guard,
        f"    result = await db.execute(select(models.{n}).where(models.{n}.id == item_id))",
        f"    obj = result.scalar_one_or_none()",
        f"    if not obj:",
        f"        raise HTTPException(status_code=404, detail='{n} not found')",
        f"    await db.delete(obj)",
        "",
    ]
    return lines


def generate_crud_py(ir: DomainIR) -> str:
    """Generate complete routers/crud.py from DomainIR."""
    lines = [_CRUD_IMPORTS, ""]

    for entity in ir.entities:
        role_map = _role_sets(ir, entity.name)
        lines.extend(_entity_router_with_rbac(entity, role_map))

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


def _seed_value(field: IRField, idx: int, entity_name: str) -> str:
    """Return a Python literal for a single seed value."""
    n = field.name.lower()
    t = field.type

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
        return repr(f"{_SEED_ADJECTIVES[idx % len(_SEED_ADJECTIVES)]} {entity_name} {idx + 1}")
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


def generate_seed_py(ir: DomainIR) -> str:
    """Generate complete deterministic seed.py from DomainIR (5 rows per entity)."""
    domain_entities = [e for e in ir.entities if e.name != "User" and getattr(e, "table", "") != "users"]
    entity_names = [e.name for e in domain_entities]

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
        "_ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Admin1234!')",
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
        "            password_hash=get_password_hash(_ADMIN_PASSWORD),",
        "            role='admin',",
        "            is_active=True,",
        "        )",
        "        db.add(admin)",
        "        await db.flush()",
        "",
    ]

    for entity in domain_entities:
        lines.append(f"        db.add_all([")
        for idx in range(5):
            field_parts = []
            for f in entity.fields:
                if f.name in ("id", "created_at", "updated_at"):
                    continue
                val = _seed_value(f, idx, entity.name)
                field_parts.append(f"                {f.name}={val},")
            lines.append(f"            {entity.name}(")
            lines.extend(field_parts)
            lines.append("            ),")
        lines.append("        ])")
        lines.append("")

    lines += [
        "        await db.commit()",
        "        _logger.info('Seeded admin: admin@example.com / %s', _ADMIN_PASSWORD)",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# stats.py router  (Gap 4 — computed KPI aggregates for dashboard)
# ---------------------------------------------------------------------------

def generate_stats_router(ir: DomainIR) -> str:
    """Generate routers/stats.py with a /stats endpoint that returns real aggregates."""
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
        "",
    ]

    # Count per entity
    for entity in domain_entities:
        lines += [
            f"    _r = await db.execute(select(func.count()).select_from(models.{entity.name}))",
            f"    stats['total_{entity.table}'] = _r.scalar_one()",
        ]

    lines.append("")

    # Success rate: find entity with a 'status' field
    status_entity = next(
        (e for e in domain_entities if any(f.name == "status" for f in e.fields)),
        None,
    )
    if status_entity:
        lines += [
            f"    # Success rate from {status_entity.name}.status",
            f"    _total_r = await db.execute(select(func.count()).select_from(models.{status_entity.name}))",
            f"    _total_n = _total_r.scalar_one()",
            f"    _succ_r = await db.execute(",
            f"        select(func.count()).select_from(models.{status_entity.name})",
            f"        .where(models.{status_entity.name}.status.in_(['success', 'completed', 'done', 'active']))",
            f"    )",
            f"    _succ_n = _succ_r.scalar_one()",
            f"    stats['success_rate'] = round(_succ_n / _total_n * 100, 2) if _total_n else 0.0",
            f"    stats['total_{status_entity.table}'] = _total_n",
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
            f"    _cost_r = await db.execute(select(func.sum(models.{cost_entity.name}.{cost_field.name})))",
            f"    stats['total_cost'] = float(_cost_r.scalar_one() or 0.0)",
            "",
        ]

    lines += [
        "    return stats",
    ]

    return "\n".join(lines) + "\n"
