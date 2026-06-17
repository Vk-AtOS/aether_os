"""
Deterministic backend code generators driven by Domain IR.

No LLM involved. Given a validated DomainIR, these functions generate:
  - models.py   (SQLAlchemy ORM models for all entities)
  - schemas.py  (Pydantic v2 Base/Create/Update/Response schemas)
  - crud.py     (paginated CRUD FastAPI routers for all entities)
  - seed.py     (deterministic realistic seed data — 20 rows per entity)
  - stats.py    (aggregated KPI endpoint: counts, success rate, cost totals)

The generated code is structurally correct by construction — not dependent on
any model's ability to write Python.

CRUD, seed, and stats generators live in ir_generator_helpers.py (split for size).
"""
from __future__ import annotations

import re as _re

from aether_os.core.domain_ir import AetherType, DomainIR, IREntity, IRField, SA_TYPE_MAP

# Re-export crud/seed/stats generators so callers can import from here unchanged.
from aether_os.phases.p04a_backend_codegen.ir_generator_helpers import (
    generate_crud_py,
    generate_seed_py,
    generate_stats_router,
    validate_seed_dependencies,
)

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

    # FIX 7: Add DB-level enum constraints
    if atype == AetherType.ENUM and field.enum_values:
        enum_list = ", ".join([f"'{v}'" for v in field.enum_values])
        parts.append(f"CheckConstraint(\"{field.name} IN ({enum_list})\", name='ck_{field.name}')")

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
    # FIX 6: Add FK relationship fields to models
    return f"    {field.ref_entity.lower()} = relationship('{field.ref_entity}', foreign_keys=[{field.name}], lazy='selectin')"


def _sql_check_constraints(entity_name: str, rules: list) -> list:
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

        # FIX 6: Add relationship fields
        for f in entity.fields:
            rel = _relationship_line(f)
            if rel:
                lines.append(rel)

        lines.append("    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))")
        lines.append("    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))")
        lines.append("")

    return "\n".join(lines)


def ir_to_models(ir: DomainIR) -> str:
    """Alias for generate_models_py to match v2 directive."""
    return generate_models_py(ir)


# ---------------------------------------------------------------------------
# schemas.py generator
# ---------------------------------------------------------------------------

_PYDANTIC_IMPORTS = """\
from __future__ import annotations
from datetime import date, datetime
from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr, field_validator
"""

_VALIDATOR_OP_MAP = {">": ">", ">=": ">=", "<": "<", "<=": "<=", "!=": "!=", "=": "=="}
_VALIDATOR_EXPR_RE = _re.compile(r'^(\w+)\s*(>=|<=|!=|>|<|=)\s*([0-9.]+)$')


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


def _pydantic_validators(entity_name: str, rules: list) -> list:
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

    # Generic paginated response
    lines.extend([
        "class PaginatedResponse(BaseModel):",
        "    items: List[Any]",
        "    total: int",
        "    page: int",
        "    limit: int",
        "",
    ])

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


def ir_to_schemas(ir: DomainIR) -> str:
    """Alias for generate_schemas_py to match v2 directive."""
    return generate_schemas_py(ir)
