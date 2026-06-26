"""Deterministic (no-LLM) CRUD router, seed data, and service layer generators.

Also provides LLM-assisted generation functions for CRUD routers, models/schemas,
and seed data when the IR fast-path is unavailable.
"""
from __future__ import annotations

import json
import logging
import re
import textwrap
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ── Multi-tenancy prompt snippet (injected when multi_tenancy=True) ───────────

_MULTI_TENANCY_PROMPT = """\
IMPORTANT — MULTI-TENANCY REQUIRED:
Every entity model MUST have this column:
    org_id = Column(String(36), nullable=False, index=True)

Every list endpoint MUST filter by org_id:
    .where(Model.org_id == current_user["org_id"])

Every create endpoint MUST set org_id from the current user:
    obj = Model(**data.model_dump(), org_id=current_user["org_id"])

The current_user dict has an "org_id" key. Use it. Never return records from other orgs.
"""

# ── LLM generation functions ───────────────────────────────────────────────────

async def _llm_models_and_schemas(
    llm, project_name: str, domain: str, entities: list, raw_input: str, arch_doc: dict,
    mem_hint: str = "", multi_tenancy: bool = False,
) -> Tuple[str, str]:
    """One LLM call → (models.py, schemas.py)."""
    entities_json = json.dumps(entities[:12], indent=2)

    # Inject golden few-shot examples for this domain
    golden_hint = ""
    try:
        from aether_os.core.learning.golden_retriever import get_golden_examples, format_golden_hint_p04
        examples = await get_golden_examples(domain, limit=2)
        golden_hint = format_golden_hint_p04(examples)
    except Exception as exc:
        logger.debug("p04a crud_generator: golden examples retrieval failed (non-fatal): %s", exc)

    # Conditionally inject multi-tenancy instructions
    tenancy_block = _MULTI_TENANCY_PROMPT if multi_tenancy else ""

    prompt = f"""\
You are a senior backend engineer. Generate SQLAlchemy async ORM models and Pydantic v2 schemas \
for a {domain} application called "{project_name}".
{golden_hint}
{tenancy_block}

Project requirements:
{raw_input[:3000]}
{mem_hint}
Entities to model:
{entities_json}

ABSOLUTE IMPORTS RULE (MANDATORY — Docker will fail otherwise):
- Use ABSOLUTE imports only. Do NOT use relative imports (no 'from .module import X').
- Import as: `from database import Base`, `from models import User`, `from schemas import UserCreate`, `from auth import get_current_user`
- NEVER write `from .database import Base` or `from .models import X` — these break inside Docker containers.

MODELS.PY requirements (file: src/models.py):
1. Imports: `from database import Base` (ABSOLUTE — no dot prefix), SQLAlchemy column types, relationship
2. ALWAYS include a User model:
   - id (Integer, primary_key, index)
   - email (String 255, unique, index, nullable=False)
   - password_hash (String 255, nullable=False)
   - role (String 50, default="user")  — values: "admin" or "user"
   - is_active (Boolean, default=True)
   - created_at, updated_at (DateTime timezone=True, with defaults)
3. For each entity: add domain-appropriate fields with proper SQLAlchemy types
4. Add ForeignKey relationships where logical (e.g. user_id references users.id)
   CRITICAL: ForeignKey string MUST match the actual __tablename__ of the referenced model exactly.
   Example: if Category.__tablename__ = 'categories', then use ForeignKey('categories.id') — never 'categorys.id' or 'category.id'.
5. Use `__tablename__` (snake_case plural) — derive using standard English pluralisation rules (category→categories, status→statuses, person→people)
6. DateTime fields use `datetime.now(timezone.utc)` as default

REQUIRED for every model (no exceptions):
- created_at: DateTime = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
- updated_at: DateTime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
- deleted_at: Optional[DateTime] = Column(DateTime(timezone=True), nullable=True)  # soft delete — never hard-delete rows
- Every ForeignKey column MUST have a corresponding Index: e.g. Index('ix_order_user_id', 'user_id')
- The User model MUST have: Index('ix_user_email', 'email', unique=True)

SCHEMAS.PY requirements (file: src/schemas.py):
1. Import: `from pydantic import BaseModel, EmailStr, Field, ConfigDict`
2. For each entity create ALL of:
   - `{{Entity}}Base` — shared editable fields with Field() validators
   - `{{Entity}}Create(EntityBase)` — for POST; mark required fields
   - `{{Entity}}Update(BaseModel)` — all Optional, for PUT/PATCH
   - `{{Entity}}Response(EntityBase)` — adds id, created_at, updated_at;
     must have `model_config = ConfigDict(from_attributes=True)`
3. EmailStr for email fields, use Field(min_length=..., max_length=...) for strings
4. Include `UserCreate`, `UserResponse` schemas

Return VALID JSON only (no markdown):
{{"models_py": "<complete models.py content>", "schemas_py": "<complete schemas.py content>"}}"""

    result = await llm.call(prompt, task_type="code_generation", max_tokens=6000)
    if not result:
        raise ValueError("Empty LLM response for models/schemas")

    # Strip markdown if present
    result = re.sub(r"^```(?:json)?\s*\n?", "", result.strip())
    result = re.sub(r"\n?```\s*$", "", result.strip())

    try:
        parsed = json.loads(result)
        models_py = parsed.get("models_py", "")
        schemas_py = parsed.get("schemas_py", "")
        if len(models_py) > 200 and len(schemas_py) > 200:
            return models_py, schemas_py
    except json.JSONDecodeError:
        # Try to extract Python blocks
        model_match = re.search(r'(?:"models_py"\s*:\s*")(.+?)(?="schemas_py")', result, re.DOTALL)
        schema_match = re.search(r'(?:"schemas_py"\s*:\s*")(.+?)(?="\}|$)', result, re.DOTALL)
        if model_match and schema_match:
            return (
                model_match.group(1).encode().decode("unicode_escape"),
                schema_match.group(1).encode().decode("unicode_escape"),
            )

    raise ValueError("Could not parse models/schemas from LLM response")


async def _llm_crud_routers(
    llm, project_name: str, entities: list, models_code: str, schemas_code: str,
    mem_hint: str = "", multi_tenancy: bool = False,
) -> str:
    """One LLM call → routers/crud.py with all entity CRUD routers."""
    entity_names = [e.get("name", e.get("table", "")) for e in entities[:12]]
    entity_list = ", ".join(entity_names)

    # Build a compact entity→fields map so the LLM can produce correct column references
    entity_fields_summary = ""
    for e in entities[:12]:
        fields = e.get("fields", []) or []
        field_names = [f.get("name", f) if isinstance(f, dict) else str(f) for f in fields[:12]]
        entity_fields_summary += f"  {e.get('name','')}: {', '.join(field_names)}\n"

    # Pass full models + schemas so LLM sees exact class names, field names, and types
    # Cap at 5000 chars each to stay within context budget
    models_ctx = models_code[:5000] + ("\n# ... (truncated)" if len(models_code) > 5000 else "")
    schemas_ctx = schemas_code[:5000] + ("\n# ... (truncated)" if len(schemas_code) > 5000 else "")

    # Conditionally inject multi-tenancy filtering instructions into CRUD prompt
    tenancy_block = _MULTI_TENANCY_PROMPT if multi_tenancy else ""

    prompt = (
        f'Generate production-quality FastAPI async CRUD routers for "{project_name}".\n'
        + mem_hint + "\n"
        + tenancy_block + "\n"
        + """
REQUIRED pagination rules (no exceptions):
- Every GET list endpoint MUST accept query params: skip: int = 0, limit: int = Query(default=20, le=100)
- Return format: {"items": [...], "total": count, "skip": skip, "limit": limit}
- Never return unbounded lists — always apply .offset(skip).limit(limit)

Entities and their fields:
"""
        + entity_fields_summary
        + "Full src/models.py:\n```python\n"
        + models_ctx
        + "\n```\n\nFull src/schemas.py:\n```python\n"
        + schemas_ctx
        + """
```

FILE: src/routers/crud.py

ABSOLUTE IMPORTS RULE (MANDATORY — Docker will fail otherwise):
- Use ABSOLUTE imports only. Do NOT use relative imports (no 'from .module import X').
- Import as: `from database import get_db`, `from models import MyModel`, `from schemas import MyCreate`, `from auth import get_current_user`
- NEVER write `from .database import get_db` or `from ..models import X`.

STRICT REQUIREMENTS — every violation causes runtime errors:
1. Imports:
   - `from __future__ import annotations`
   - `from typing import List, Optional, Any`
   - `from fastapi import APIRouter, Depends, HTTPException, status, Query`
   - `from sqlalchemy.ext.asyncio import AsyncSession`
   - `from sqlalchemy import select, func`
   - `from database import get_db`
   - `from auth import get_current_user, require_admin`
   - Import EVERY model class from `models` that you reference
   - Import EVERY schema class from `schemas` that you reference

2. For EACH domain entity (NOT User — User is handled by auth router):
   Create `APIRouter(prefix="/{entity_plural}", tags=["{Entity Label}"])`:
   - `GET /` -> paginated list: `skip: int = Query(0, ge=0)`, `limit: int = Query(100, le=500)`
     Returns: `List[{Entity}Response]`
   - `POST /` -> create, `status_code=201`, returns `{Entity}Response`
   - `GET /{id}` -> single record or HTTP 404, returns `{Entity}Response`
   - `PUT /{id}` -> full update or HTTP 404, returns `{Entity}Response`
   - `PATCH /{id}` -> partial update, `data: {Entity}Update`, returns `{Entity}Response`
   - `DELETE /{id}` -> soft-delete or hard-delete, HTTP 204

   SECURITY: Never include `password_hash` or `password` fields in any response dict or model.
   If a model has a `password_hash` column, exclude it explicitly.

3. Query pattern (async SQLAlchemy):
   - List:   `result = await db.execute(select({Model}).offset(skip).limit(limit))`
             `items = list(result.scalars().all())`
   - Single: `result = await db.execute(select({Model}).where({Model}.id == id))`
             `obj = result.scalar_one_or_none()`
             `if obj is None: raise HTTPException(status_code=404, ...)`
   - Create: `obj = {Model}(**data.model_dump(exclude_unset=True))`
             `db.add(obj); await db.flush(); await db.refresh(obj)`
   - Update: fetch, then `for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)`
             `await db.flush(); await db.refresh(obj)`
   - Delete: fetch, `await db.delete(obj)` (or set `is_active=False` for soft-delete)

4. Auth: ALL routes require `current_user: dict = Depends(get_current_user)`.
   DELETE requires `Depends(require_admin)`.

5. LAST LINE must be: `all_routers = [{entity}_router, ...]` listing ALL entity routers.

Return ONLY the complete Python file. No markdown, no explanation."""
    )

    result = await llm.call(prompt, task_type="code_generation", max_tokens=6000)
    if not result or len(result.strip()) < 200:
        raise ValueError("Empty or too-short LLM response for CRUD routers")

    # Strip markdown fences if present
    code = re.sub(r"^```(?:python)?\s*\n?", "", result.strip())
    code = re.sub(r"\n?```\s*$", "", code.strip())

    # Fix relative imports that break when src/ is loaded as an absolute package
    # e.g. Bedrock Nova sometimes writes "from..schemas import" or "from ..models import"
    code = re.sub(r"from\s*\.+\s*(schemas|models|database|auth)\s+import", r"from \1 import", code)

    return code


async def _llm_seed_data(
    llm, project_name: str, domain: str, entities: list, models_code: str
) -> str:
    """One LLM call → seed.py with realistic startup data."""
    entity_names = [e.get("name", e.get("table", "")) for e in entities[:10]]

    prompt = f"""\
Generate a `seed_database()` async function for "{project_name}" ({domain}).

Complete src/models.py (use EXACT class names from here):
```python
{models_code[:3000]}{"" if len(models_code) <= 3000 else chr(10) + "# ... (truncated)"}
```

FILE: src/seed.py

ABSOLUTE IMPORTS RULE: Use absolute imports only — NO relative imports.
Example: `from database import AsyncSessionLocal`, `from auth import get_password_hash`, `from models import User`
NEVER write `from .database import ...` or `from .models import ...`.

REQUIREMENTS:
1. Import: `from database import AsyncSessionLocal`, `from auth import get_password_hash`
2. Import all models from `models` (absolute: `from models import User, ...`)
3. `async def seed_database()` — called on every startup
4. Check if already seeded: `result = await db.execute(select(func.count()).select_from(User))`
   If count > 0, return early (idempotent)
5. Create admin user: email="admin@example.com", role="admin"
   Set `_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin1234!")`
   Use `password=get_password_hash(_ADMIN_PASSWORD)`.
   Add `import os` at top of file.
   Log: `_logger.info("Seeded admin: admin@example.com / %s", _ADMIN_PASSWORD)`
6. Create 15-20 realistic records for EACH entity:
   - Use real-world names, descriptions, values (NOT "test1", "item1", "string")
   - Values must be domain-appropriate for {domain}
   - For "{project_name}": use realistic {domain}-specific terminology
7. Use `db.add_all([...])` for bulk inserts
8. Add all in a single session: `async with AsyncSessionLocal() as db:`

Return ONLY the complete seed.py file. No markdown, no explanation."""

    result = await llm.call(prompt, task_type="code_generation", max_tokens=4000)
    if not result or len(result.strip()) < 200:
        raise ValueError("Empty LLM seed response")

    code = re.sub(r"^```(?:python)?\s*\n?", "", result.strip())
    code = re.sub(r"\n?```\s*$", "", code.strip())
    return code


async def _llm_service_layer(
    llm, project_name: str, entities: list, models_code: str, schemas_code: str,
    mem_hint: str = "",
) -> str:
    """One LLM call → services/entity_services.py with one service class per entity."""
    prompt = f"""
Generate src/services/__init__.py for "{project_name}".
{mem_hint}
Create one service class per entity: class EntityService with async staticmethods:
  - get_all(db, skip, limit) -> list
  - get_by_id(db, id) -> model | None
  - create(db, data) -> model
  - update(db, id, data) -> model | None
  - delete(db, id) -> bool
Each method uses SQLAlchemy async session (AsyncSession).
Import models from ..models, return ORM objects.
The CRUD routers will call these service methods instead of querying the DB directly.
Return ONLY the complete Python file. No markdown.
"""
    result = await llm.call(prompt, task_type="code_generation", max_tokens=4000)
    if not result or len(result.strip()) < 100:
        raise ValueError("Empty LLM response for service layer")
    code = re.sub(r"^```(?:python)?\s*\n?", "", result.strip())
    code = re.sub(r"\n?```\s*$", "", code.strip())
    return code


# ── Fallback generators (no LLM) ──────────────────────────────────────────────

def _fallback_crud_routers(entities: list, multi_tenancy: bool = False) -> str:
    """Fallback CRUD using ORM (no raw SQL — no injection vectors).

    When multi_tenancy=True, every list query filters by org_id and every create
    endpoint stamps org_id from the calling user's JWT claims.
    """
    # Ensure we always have at least one entity so the schemas import line
    # is never produced with an empty trailing module list (SyntaxError).
    safe_entities = entities[:8] if entities else [{"name": "Item", "table": "items"}]
    schemas_imports = ", ".join(
        f"{e.get('name', 'Item')}Create, {e.get('name', 'Item')}Update"
        for e in safe_entities
    )
    lines = [
        "from __future__ import annotations",
        "from typing import Any, Dict, List, Optional",
        "from fastapi import APIRouter, Depends, HTTPException, Query, status",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select, func",
        "from database import get_db",
        "from auth import get_current_user, require_admin",
        "import models",
        f"from schemas import {schemas_imports}",
        "",
    ]
    router_vars = []
    for ent in safe_entities:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        var = f"{table}_router"
        router_vars.append(var)

        # Multi-tenancy filter clause (injected into list and get queries)
        mt_list_filter = (
            f".where(models.{name}.org_id == current_user['org_id'])"
            if multi_tenancy else ""
        )
        mt_create_kwarg = (
            f", org_id=current_user['org_id']"
            if multi_tenancy else ""
        )

        lines += [
            f"{var} = APIRouter(prefix='/{table}', tags=['{name}'])",
            "",
            f"@{var}.get('/', response_model=dict)",
            f"async def list_{table}(",
            f"    page: int = Query(1, ge=1),",
            f"    limit: int = Query(20, ge=1, le=200),",
            f"    db: AsyncSession = Depends(get_db),",
            f"    current_user: dict = Depends(get_current_user),",
            f"):",
            f"    offset = (page - 1) * limit",
            f"    total_q = await db.execute(select(func.count()).select_from(models.{name}){mt_list_filter})",
            f"    total = total_q.scalar_one()",
            f"    result = await db.execute(select(models.{name}){mt_list_filter}.offset(offset).limit(limit))",
            f"    items = result.scalars().all()",
            f"    return {{'items': [{{c.name: getattr(i, c.name) for c in models.{name}.__table__.columns if c.name not in ('password_hash', 'password')}} for i in items], 'total': total, 'page': page, 'limit': limit}}",
            "",
            f"@{var}.post('/', status_code=201, response_model=dict)",
            f"async def create_{table}(data: {name}Create, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
            f"    obj = models.{name}(**data.model_dump(exclude_unset=True){mt_create_kwarg})",
            f"    db.add(obj)",
            f"    await db.flush()",
            f"    await db.refresh(obj)",
            f"    return {{c.name: getattr(obj, c.name) for c in models.{name}.__table__.columns if c.name not in ('password_hash', 'password')}}",
            "",
            f"@{var}.get('/{{item_id}}', response_model=dict)",
            f"async def get_{table}(item_id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id{', models.' + name + '.org_id == current_user[\"org_id\"]' if multi_tenancy else ''}))",
            f"    obj = result.scalar_one_or_none()",
            f"    if not obj:",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    return {{c.name: getattr(obj, c.name) for c in models.{name}.__table__.columns if c.name not in ('password_hash', 'password')}}",
            "",
            f"@{var}.patch('/{{item_id}}', response_model=dict)",
            f"async def update_{table}(item_id: int, data: {name}Update, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id{', models.' + name + '.org_id == current_user[\"org_id\"]' if multi_tenancy else ''}))",
            f"    obj = result.scalar_one_or_none()",
            f"    if not obj:",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    for k, v in data.model_dump(exclude_unset=True).items():",
            f"        setattr(obj, k, v)",
            f"    await db.flush()",
            f"    await db.refresh(obj)",
            f"    return {{c.name: getattr(obj, c.name) for c in models.{name}.__table__.columns if c.name not in ('password_hash', 'password')}}",
            "",
            f"@{var}.put('/{{item_id}}', response_model=dict, include_in_schema=False)",
            f"async def update_{table}_put(item_id: int, data: {name}Update, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):",
            f"    return await update_{table}(item_id, data, db, current_user)",
            "",
            f"@{var}.delete('/{{item_id}}', status_code=204)",
            f"async def delete_{table}(item_id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_admin)):",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id))",
            f"    obj = result.scalar_one_or_none()",
            f"    if not obj:",
            f"        raise HTTPException(status_code=404, detail='{name} not found')",
            f"    await db.delete(obj)",
            "",
        ]
    lines.append(f"all_routers = [{', '.join(router_vars)}]")
    return "\n".join(lines)


def _fallback_seed(
    project_name: str,
    entities: list,
    seed_vocabulary: Dict[str, List[str]] | None = None,
    domain: str = "general",
) -> str:
    """Generate a minimal seed.py that creates an admin user.

    When seed_vocabulary contains domain-specific terms and entities has records,
    those terms are used to produce more realistic seed record names rather than the
    generic 'Alpha/Beta/Gamma' fallbacks.
    """
    vocab = seed_vocabulary or {}
    prefix = project_name  # used to prefix seed record titles for traceability

    # Build a small sample of domain-specific records for each entity when vocabulary exists
    entity_blocks = []
    safe_entities = entities[:8] if entities else []
    for ent in safe_entities:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        # Use vocab list for this entity if available, else generic names
        vocab_list = vocab.get(name, vocab.get(name.lower(), vocab.get(domain, [])))
        if vocab_list:
            sample_names = [repr(f"{prefix} {v}") for v in vocab_list[:5]]
        else:
            sample_names = [repr(f"{prefix} {name} {i + 1}") for i in range(5)]
        # Emit a simple name-field seed if entity has a 'name' field
        fields = ent.get("fields", []) or []
        has_name_field = any(
            (f.get("name") if isinstance(f, dict) else f) == "name" for f in fields
        )
        if has_name_field and sample_names:
            rows = "\n".join(
                f"            {name}(name={n})," for n in sample_names
            )
            entity_blocks.append(
                f"        try:\n"
                f"            from models import {name}\n"
                f"            db.add_all([\n{rows}\n            ])\n"
                f"        except Exception as _e:\n"
                f"            _logger.warning('Seed {name} failed (non-fatal): %s', _e)\n"
            )

    entity_seed_code = "\n".join(entity_blocks) if entity_blocks else "        pass  # no entity seed data"

    return textwrap.dedent(f"""\
        from __future__ import annotations
        import os, logging
        from sqlalchemy import select, func
        from database import AsyncSessionLocal
        from auth import get_password_hash
        from models import User

        _logger = logging.getLogger(__name__)
        _ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin1234!")

        async def seed_database() -> None:
            async with AsyncSessionLocal() as db:
                count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
                if count > 0:
                    return
                admin = User(
                    email="admin@example.com",
                    password_hash=get_password_hash(_ADMIN_PASSWORD),
                    role="admin",
                    is_active=True,
                )
                db.add(admin)
                await db.flush()
        {entity_seed_code}
                await db.commit()
                _logger.info("Seeded admin user: admin@example.com / %s", _ADMIN_PASSWORD)
    """)


def _fallback_service_layer(entities: list) -> str:
    """Generate bare service stubs for each entity using SQLAlchemy select/add/delete."""
    lines = [
        "from __future__ import annotations",
        "from typing import Any, Dict, List, Optional",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select",
        "",
    ]
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        lines += [
            f"class {name}Service:",
            f"    @staticmethod",
            f"    async def get_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).offset(skip).limit(limit))",
            f"            return list(result.scalars().all())",
            f"        except Exception:",
            f"            return []",
            "",
            f"    @staticmethod",
            f"    async def get_by_id(db: AsyncSession, id: int) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            return result.scalar_one_or_none()",
            f"        except Exception:",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def create(db: AsyncSession, data: Dict[str, Any]) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            obj = {name}(**data)",
            f"            db.add(obj)",
            f"            await db.flush()",
            f"            await db.refresh(obj)",
            f"            return obj",
            f"        except Exception:",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def update(db: AsyncSession, id: int, data: Dict[str, Any]) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            obj = result.scalar_one_or_none()",
            f"            if obj is None:",
            f"                return None",
            f"            for k, v in data.items():",
            f"                setattr(obj, k, v)",
            f"            await db.flush()",
            f"            await db.refresh(obj)",
            f"            return obj",
            f"        except Exception:",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def delete(db: AsyncSession, id: int) -> bool:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            obj = result.scalar_one_or_none()",
            f"            if obj is None:",
            f"                return False",
            f"            await db.delete(obj)",
            f"            return True",
            f"        except Exception:",
            f"            return False",
            "",
        ]
    return "\n".join(lines)
