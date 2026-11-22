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

from aether_os.phases.p04a_backend_codegen.rule_grammar import parse_rule
from aether_os.core.domain_ir import AetherType, DomainIR, IRField, SA_TYPE_MAP

# Re-export crud/seed/stats generators so callers can import from here unchanged.
from aether_os.phases.p04a_backend_codegen.ir_generator_helpers import (  # noqa: F401
    generate_crud_py,
    generate_seed_py,
    generate_stats_router,
    validate_seed_dependencies,
)

from aether_os.phases.p04a_backend_codegen.ir_client_fields import client_fields, is_user_entity

# ---------------------------------------------------------------------------
# models.py generator
# ---------------------------------------------------------------------------

_SA_IMPORTS = """\
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, JSON
from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import relationship
from database import Base
"""


def _with_decimal(imports: str) -> str:
    """Add `from decimal import Decimal` after the `from __future__` line: a __future__ import must be the
    first statement, so putting Decimal first made every money-domain models.py and schemas.py fail to
    compile (KAN-169)."""
    future = "from __future__ import annotations\n"
    return imports.replace(future, future + "from decimal import Decimal\n", 1)


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


def _sa_column(field: IRField, domain: str = "") -> str:
    """Return SQLAlchemy Column(...) definition for one IRField.

    domain: when set to a money domain (fintech/marketplace/erp), DECIMAL fields
    are typed as Numeric(12, 2) per PCI/domain-pack constraints, and money-named
    STRING fields are promoted to Numeric(12, 2) automatically.
    """
    from aether_os.phases.p04a_backend_codegen.schema_builder import (
        _is_money_domain,
        _is_healthcare,
        _MONEY_FIELDS,
        _PHI_FIELDS,
    )

    atype = field.type
    field_lower = field.name.lower()

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
        # Promote money-named STRING fields to Numeric in money domains so the
        # generated model matches PCI/FinTech domain-pack constraints.
        if _is_money_domain(domain) and field_lower in _MONEY_FIELDS:
            col_type = "Numeric(12, 2)"
        else:
            col_type = "String(255)"
    elif atype == AetherType.DECIMAL:
        # Precision: 12,2 for money domains; 14,2 generic otherwise.
        col_type = "Numeric(12, 2)" if _is_money_domain(domain) else "Numeric(14, 2)"
    else:
        col_type = SA_TYPE_MAP.get(atype, "String(255)")

    parts = [col_type]

    # FIX 7: Add DB-level enum constraints
    if atype == AetherType.ENUM and field.enum_values:
        enum_list = ", ".join(["'" + str(v).replace("'", "''") + "'" for v in field.enum_values])
        parts.append(f"CheckConstraint({field.name + ' IN (' + enum_list + ')'!r}, name='ck_{field.name}')")

    # FK columns always get an index for join performance
    if atype == AetherType.FK:
        parts.append("index=True")

    if not field.nullable:
        parts.append("nullable=False")
    if field.unique:
        parts.append("unique=True")
    if field.index and atype != AetherType.FK:
        # FK already added index=True above; avoid duplicates
        parts.append("index=True")
    if field.default is not None and atype == AetherType.BOOLEAN:
        parts.append(f"default={str(field.default).lower() in ('true', '1', 'yes')}")

    # Healthcare PHI comment so developers know these fields need special handling.
    phi_comment = (
        "  # PHI - handle per HIPAA"
        if _is_healthcare(domain) and field_lower in _PHI_FIELDS
        else ""
    )
    return f"    {field.name} = Column({', '.join(parts)}){phi_comment}"


def _relationship_line(field: IRField) -> str | None:
    """Return an ORM relationship() line for an FK field."""
    if field.type != AetherType.FK or not field.ref_entity:
        return None
    # FIX 6: Add FK relationship fields to models
    return f"    {field.ref_entity.lower()} = relationship('{field.ref_entity}', foreign_keys=[{field.name}], lazy='selectin')"


def _sql_check_constraints(entity_name: str, rules: list, columns: set | None = None) -> list:
    """
    Convert IRBusinessRule expressions to SQLAlchemy CheckConstraint strings.

    Only the grammar of rule_grammar.parse_rule is accepted; anything else is skipped and never pasted into
    the source: the expression is model-written text, and a quote in it used to become code and SQL (KAN-169).
    Every identifier must be a column of the entity, otherwise CREATE TABLE fails. The SQL is rebuilt from the
    parsed parts and emitted with repr(), the name is reduced to \\w.
    """
    constraints = []
    for rule in rules:
        if rule.entity != entity_name:
            continue
        terms = parse_rule(rule.expression)
        if not terms:
            continue
        if columns is not None and any(i not in columns for t in terms for i in t.identifiers()):
            continue
        expr = " AND ".join(t.sql() for t in terms)
        cname = _re.sub(r"\W", "_", f"ck_{entity_name.lower()}_{rule.name}")[:63]
        constraints.append(f"        CheckConstraint({expr!r}, name={cname!r})")
    return constraints


# Columns generate_models_py writes for every entity itself.
_GENERATED_COLUMNS = {"id", "created_at", "updated_at"}


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


def generate_models_py(ir: DomainIR, domain: str = "", multi_tenancy: bool = False) -> str:
    """Generate complete models.py from DomainIR.

    domain: propagated to _sa_column so that domain-specific column types are
    applied (e.g. Numeric(12,2) for money fields in fintech/marketplace/erp,
    PHI comments in healthcare).
    """
    from aether_os.phases.p04a_backend_codegen.schema_builder import _is_money_domain

    # Money domains need Decimal import at module level.
    sa_imports = _SA_IMPORTS
    if _is_money_domain(domain):
        sa_imports = _with_decimal(sa_imports)

    lines = [sa_imports, ""]

    # Always emit User model first so auth router import works
    lines.append(_USER_MODEL)
    if multi_tenancy:
        # the user's tenant goes into the access token; every entity row carries it (KAN-169)
        lines.append("    org_id = Column(String(64), nullable=True, index=True)")

    for entity in ir.entities:
        # Skip User — always emitted above from _USER_MODEL to avoid duplicate table
        if is_user_entity(entity):
            continue
        constraints = _sql_check_constraints(
            entity.name, ir.business_rules, {f.name for f in entity.fields} | {'id', 'created_at', 'updated_at'})

        # Build performance indexes for commonly-queried field patterns
        perf_indexes = []
        table = entity.table
        # id / created_at / updated_at are always emitted below; an IR field of that name would
        # override the primary key or duplicate the column.
        fields = [f for f in client_fields(entity, multi_tenancy) if f.name.lower() not in _GENERATED_COLUMNS]
        field_names = {f.name for f in fields}
        # Column(..., index=True) already creates an index SQLAlchemy names ix_<table>_<column>. An explicit
        # Index of the same name on top of it made create_all fail with "index ix_tasks_status already exists".
        column_indexed = {f.name for f in fields if f.index or f.type == AetherType.FK}
        # created_at index — every time-range query benefits from this
        perf_indexes.append(
            f"        Index('ix_{table}_created_at', 'created_at')"
        )
        # status / state field index — filtering by status is the most common query pattern
        for fname in ("status", "state"):
            if fname in field_names and fname not in column_indexed:
                perf_indexes.append(
                    f"        Index('ix_{table}_{fname}', '{fname}')"
                )

        table_args_parts = constraints + perf_indexes
        lines.append(f"class {entity.name}(Base):")
        lines.append(f"    __tablename__ = '{entity.table}'")
        if table_args_parts:
            lines.append("    __table_args__ = (")
            for part in table_args_parts:
                lines.append(part + ",")
            lines.append("    )")
        lines.append("")
        lines.append("    id = Column(Integer, primary_key=True, index=True)")
        for f in fields:
            # Pass domain so column types respect domain pack constraints
            lines.append(_sa_column(f, domain=domain))

        # FIX 6: Add relationship fields
        for f in fields:
            rel = _relationship_line(f)
            if rel:
                lines.append(rel)

        if multi_tenancy:
            lines.append("    org_id = Column(String(64), nullable=False, index=True)")
        lines.append("    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))")
        lines.append("    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))")
        lines.append("")

    return "\n".join(lines)


def ir_to_models(ir: DomainIR, domain: str = "", multi_tenancy: bool = False) -> str:
    """Alias for generate_models_py to match v2 directive."""
    return generate_models_py(ir, domain=domain, multi_tenancy=multi_tenancy)


# ---------------------------------------------------------------------------
# schemas.py generator
# ---------------------------------------------------------------------------

_PYDANTIC_IMPORTS = """\
from __future__ import annotations
from datetime import date, datetime
from typing import Optional, List, Any
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
"""



def _pydantic_type(field: IRField, domain: str = "") -> str:
    """Return the Python/Pydantic type annotation for an IRField.

    domain: when set to a money domain, DECIMAL fields and money-named STRING
    fields use Decimal instead of float/str so generated schemas satisfy
    PCI/FinTech domain-pack constraints.
    """
    from aether_os.phases.p04a_backend_codegen.schema_builder import (
        _is_money_domain,
        _MONEY_FIELDS,
    )

    atype = field.type
    field_lower = field.name.lower()

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

    # Money domains: DECIMAL fields and money-named STRING fields use Decimal.
    if _is_money_domain(domain) and (
        atype == AetherType.DECIMAL
        or (atype == AetherType.STRING and field_lower in _MONEY_FIELDS)
    ):
        base = "Decimal"
    else:
        base = type_map.get(atype, "str")

    if field.nullable:
        return f"Optional[{base}]"
    return base


def _pydantic_validators(entity_name: str, rules: list) -> list:
    """
    Generate @field_validator methods for the single-field terms of a rule ('salary > 0',
    'age >= 18 and age <= 65', "status in ('open','closed')"). Field-vs-field terms
    ('end_date > start_date') are enforced by the database CheckConstraint only.
    """
    validators = []
    for rule in rules:
        if rule.entity != entity_name:
            continue
        terms = parse_rule(rule.expression)
        for n, term in enumerate(terms or []):
            check = term.python_check("v")
            if check is None:
                continue
            msg = rule.error_message or f"{term.column} violates rule {rule.name}: {term.sql()}"
            vname = "check_" + _re.sub(r"\W", "_", str(rule.name)) + f"_{n}"
            validators += [
                f"    @field_validator({term.column!r}, mode='before', check_fields=False)",
                "    @classmethod",
                f"    def {vname}(cls, v):",
                f"        if v is not None and not ({check}):",
                f"            raise ValueError({msg!r})",
                "        return v",
                "",
            ]
    return validators


def generate_schemas_py(ir: DomainIR, domain: str = "", multi_tenancy: bool = False) -> str:
    """Generate complete schemas.py from DomainIR.

    domain: when set to a money domain (fintech/marketplace/erp), DECIMAL and
    money-named fields use Decimal type and the Decimal import is injected.
    Healthcare domain adds PHI comments on sensitive fields.
    """
    from aether_os.phases.p04a_backend_codegen.schema_builder import (
        _is_money_domain,
        _is_healthcare,
        _PHI_FIELDS,
    )

    # Inject Decimal import for money domains so generated schemas compile.
    pydantic_imports = _PYDANTIC_IMPORTS
    if _is_money_domain(domain):
        pydantic_imports = _with_decimal(pydantic_imports)

    lines = [pydantic_imports, ""]

    # Generic paginated response
    lines.extend([
        "class PaginatedResponse(BaseModel):",
        "    items: List[Any]",
        "    total: int",
        "    page: int",
        "    page_size: int",
        "    limit: int",
        "",
    ])

    for entity in ir.entities:
        if is_user_entity(entity):      # accounts are created by /auth/register only (role, password_hash)
            continue
        name = entity.name

        fields_block_base = []
        fields_block_update = []

        # id/created_at/updated_at are server-set (the Response adds them). Run 23's spec listed the timestamps as
        # ordinary fields, so ProjectCreate required them and every create from the UI failed with 422.
        for f in (f for f in client_fields(entity, multi_tenancy) if f.name.lower() not in _GENERATED_COLUMNS):
            ptype = _pydantic_type(f, domain=domain)
            if f.nullable:
                default = " = None"
            elif f.default is not None and f.type == AetherType.BOOLEAN:
                default = f" = {str(f.default).capitalize()}"
            else:
                default = ""
            optional_ptype = f"Optional[{ptype.replace('Optional[', '').rstrip(']')}]"

            # PHI comment for healthcare-domain sensitive fields
            phi_comment = (
                "  # PHI - handle per HIPAA"
                if _is_healthcare(domain) and f.name.lower() in _PHI_FIELDS
                else ""
            )
            fields_block_base.append(f"    {f.name}: {ptype}{default}{phi_comment}")
            fields_block_update.append(f"    {f.name}: {optional_ptype} = None{phi_comment}")

        validators = _pydantic_validators(name, ir.business_rules)

        # Base
        lines.append(f"class {name}Base(BaseModel):")
        lines.append("    model_config = ConfigDict(extra='ignore')")
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
        lines.append("    model_config = ConfigDict(extra='ignore')")
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
        lines.append("    model_config = ConfigDict(from_attributes=True, extra='ignore')")
        lines.append("")

    return "\n".join(lines)


def ir_to_schemas(ir: DomainIR, domain: str = "", multi_tenancy: bool = False) -> str:
    """Alias for generate_schemas_py to match v2 directive."""
    return generate_schemas_py(ir, domain=domain, multi_tenancy=multi_tenancy)
