"""
Deterministic backend code generators driven by Domain IR.

No LLM involved. Given a validated DomainIR, these functions generate:
  - models.py   (SQLAlchemy ORM models for all entities)
  - schemas.py  (Pydantic v2 Base/Create/Update/Response schemas)
  - crud.py     (paginated CRUD FastAPI routers for all entities)

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
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON
from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import relationship
from .database import Base
"""


def _sa_column(field: IRField) -> str:
    """Return SQLAlchemy Column(...) definition for one IRField."""
    atype = field.type

    # Build column type string
    if atype == AetherType.FK:
        ref = field.ref_entity or "users"
        table_name = "".join(
            ["_" + c.lower() if c.isupper() else c for c in ref]
        ).lstrip("_") + "s"
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


def generate_models_py(ir: DomainIR) -> str:
    """Generate complete models.py from DomainIR."""
    lines = [_SA_IMPORTS, ""]

    for entity in ir.entities:
        lines.append(f"class {entity.name}(Base):")
        lines.append(f"    __tablename__ = '{entity.table}'")
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
from typing import Optional, List
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
        AetherType.JSON:     "dict",
    }
    base = type_map.get(atype, "str")
    if field.nullable:
        return f"Optional[{base}]"
    return base


def generate_schemas_py(ir: DomainIR) -> str:
    """Generate complete schemas.py from DomainIR."""
    lines = [_PYDANTIC_IMPORTS, ""]

    for entity in ir.entities:
        name = entity.name
        fields_block_base = []
        fields_block_create = []
        fields_block_update = []
        fields_block_response = []

        for f in entity.fields:
            ptype = _pydantic_type(f)
            default = " = None" if f.nullable else ""
            optional_ptype = f"Optional[{ptype.replace('Optional[', '').rstrip(']')}]"
            fields_block_base.append(f"    {f.name}: {ptype}{default}")
            fields_block_create.append(f"    {f.name}: {ptype}{default}")
            fields_block_update.append(f"    {f.name}: {optional_ptype} = None")
            fields_block_response.append(f"    {f.name}: {ptype}{default}")

        # Base
        lines.append(f"class {name}Base(BaseModel):")
        if fields_block_base:
            lines.extend(fields_block_base)
        else:
            lines.append("    pass")
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
from ..database import get_db
from ..auth import get_current_user
from .. import models, schemas
"""


def _entity_router(entity: IREntity) -> list[str]:
    """Generate CRUD router function definitions for one entity."""
    n = entity.name
    t = entity.table
    var = n.lower()
    router_var = f"{t}_router"

    lines = [
        f"{router_var} = APIRouter(prefix='/{t}', tags=['{n}'])",
        "",
        f"@{router_var}.get('/', response_model=dict)",
        f"async def list_{t}(",
        f"    page: int = Query(1, ge=1),",
        f"    limit: int = Query(20, ge=1, le=100),",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user=Depends(get_current_user),",
        f"):",
        f"    offset = (page - 1) * limit",
        f"    total_q = await db.execute(select(func.count()).select_from(models.{n}))",
        f"    total = total_q.scalar_one()",
        f"    result = await db.execute(select(models.{n}).offset(offset).limit(limit))",
        f"    items = result.scalars().all()",
        f"    return {{'items': [schemas.{n}Response.model_validate(i) for i in items], 'total': total, 'page': page, 'limit': limit}}",
        "",
        f"@{router_var}.post('/', response_model=schemas.{n}Response, status_code=201)",
        f"async def create_{var}(",
        f"    payload: schemas.{n}Create,",
        f"    db: AsyncSession = Depends(get_db),",
        f"    current_user=Depends(get_current_user),",
        f"):",
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
        lines.extend(_entity_router(entity))

    # all_routers list — every entity gets included
    router_vars = [f"{e.table}_router" for e in ir.entities]
    lines.append(f"all_routers = [{', '.join(router_vars)}]")
    lines.append("")

    return "\n".join(lines)
