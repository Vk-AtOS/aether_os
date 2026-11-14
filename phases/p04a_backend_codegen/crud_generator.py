"""Deterministic (no-LLM) CRUD router, seed data, and service layer generators.

Also provides LLM-assisted generation functions for CRUD routers, models/schemas,
and seed data when the IR fast-path is unavailable.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Tuple

from phases.p04a_backend_codegen.helpers import _fallback_auth_flow_code, _AUTH_FLOWS_PROMPT
from phases.p04a_backend_codegen.prompts import build_crud_prompt, build_seed_prompt

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
    entities_json = json.dumps(entities, indent=2)

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
   - `{{Entity}}Base` — shared editable fields with Field() validators;
     must have `model_config = ConfigDict(extra='ignore')`
   - `{{Entity}}Create(EntityBase)` — for POST; mark required fields
   - `{{Entity}}Update(BaseModel)` — all Optional, for PUT/PATCH;
     must have `model_config = ConfigDict(extra='ignore')`
   - `{{Entity}}Response(EntityBase)` — adds id, created_at, updated_at;
     must have `model_config = ConfigDict(from_attributes=True, extra='ignore')`
3. EmailStr for email fields, use Field(min_length=..., max_length=...) for strings
4. Include `UserCreate`, `UserResponse` schemas with the same model_config rules

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


def _check_and_fix_sql_injection(code: str) -> str:
    """Post-processing: detect and neutralise f-string raw SQL patterns in generated crud.py.

    LLMs occasionally emit raw SQL f-strings (SQL injection vectors).
    This pass replaces any f-string SQL with a warning comment + safe ORM placeholder.
    Pattern: f"SELECT ...", f'UPDATE ...', f"DELETE ...", f"INSERT ..."
    """
    _SQL_FSTRING_RE = re.compile(
        r'f["\'].*?(SELECT|UPDATE|DELETE|INSERT).*?["\']',
        re.IGNORECASE | re.DOTALL,
    )
    if not _SQL_FSTRING_RE.search(code):
        return code

    def _replace_sql(m: re.Match) -> str:
        original = m.group(0)
        logger.warning(
            "p04a sql_injection_check: replaced raw SQL f-string with ORM placeholder: %.100s",
            original,
        )
        return (
            '# [AetherOS] Raw SQL f-string removed (SQL injection risk). '
            'Use SQLAlchemy ORM select() instead.\n'
            '        None  # TODO: replace with ORM query'
        )

    return _SQL_FSTRING_RE.sub(_replace_sql, code)


def _scrub_password_fields_from_response(code: str) -> str:
    """Post-processing pass: remove password_hash/password/hashed_password from response schemas.

    LLM-generated crud.py sometimes leaks password fields into response dicts.
    This scrub ensures they never appear in any dict comprehension or Pydantic model.
    Only modifies lines that explicitly include these fields as dict keys in responses.
    """
    _BANNED = ("password_hash", "password", "hashed_password")
    out_lines = []
    for line in code.splitlines():
        # Remove banned fields from inline dict comprehensions that filter columns by name
        # e.g. {c.name: ... if c.name not in ('password_hash',)} patterns are already safe;
        # target: literal key assignments like '"password_hash": obj.password_hash'
        for field in _BANNED:
            # Drop lines that are bare key-value pairs for password fields in response dicts
            if (
                f'"{field}"' in line or f"'{field}'" in line
            ) and "not in" not in line and "exclude" not in line:
                stripped = line.strip()
                # Only drop if the line IS the key-value pair (not a comment or import)
                if stripped.startswith(f'"{field}"') or stripped.startswith(f"'{field}'"):
                    logger.debug("p04a scrub: removed password field line: %s", stripped)
                    break
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


async def _llm_crud_routers(
    llm, project_name: str, entities: list, models_code: str, schemas_code: str,
    mem_hint: str = "", multi_tenancy: bool = False,
) -> str:
    """One LLM call → routers/crud.py with all entity CRUD routers."""
    entity_names = [e.get("name", e.get("table", "")) for e in entities]
    entity_list = ", ".join(entity_names)

    # Build a compact entity→fields map so the LLM can produce correct column references
    entity_fields_summary = ""
    for e in entities:
        fields = e.get("fields", []) or []
        field_names = [f.get("name", f) if isinstance(f, dict) else str(f) for f in fields]
        entity_fields_summary += f"  {e.get('name','')}: {', '.join(field_names)}\n"

    # Pass full models + schemas so LLM sees exact class names, field names, and types
    # Cap at 5000 chars each to stay within context budget
    models_ctx = models_code[:5000] + ("\n# ... (truncated)" if len(models_code) > 5000 else "")
    schemas_ctx = schemas_code[:5000] + ("\n# ... (truncated)" if len(schemas_code) > 5000 else "")

    # Conditionally inject multi-tenancy filtering instructions into CRUD prompt
    tenancy_block = _MULTI_TENANCY_PROMPT if multi_tenancy else ""

    prompt = build_crud_prompt(
        project_name=project_name,
        entity_fields_summary=entity_fields_summary,
        models_ctx=models_ctx,
        schemas_ctx=schemas_ctx,
        mem_hint=mem_hint,
        multi_tenancy_block=tenancy_block,
        auth_flows_prompt=_AUTH_FLOWS_PROMPT,
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

    # Post-process: remove any password fields that leaked into response dicts
    code = _scrub_password_fields_from_response(code)

    # Post-process: neutralise raw SQL f-strings (SQL injection risk)
    code = _check_and_fix_sql_injection(code)

    return code


async def _llm_seed_data(
    llm, project_name: str, domain: str, entities: list, models_code: str
) -> str:
    """One LLM call → seed.py with realistic startup data."""
    models_ctx = models_code[:3000] + (
        "\n# ... (truncated)" if len(models_code) > 3000 else ""
    )
    prompt = build_seed_prompt(
        project_name=project_name,
        domain=domain,
        models_ctx=models_ctx,
    )

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

_BANNED_FIELDS = frozenset(("password_hash", "password", "hashed_password"))


def _entity_serialize_dict(name: str, fields: list, obj_var: str = "obj") -> str:
    """Build a static serialization dict literal from entity field list.

    Uses the IR field names at code-generation time instead of __table__.columns
    introspection at runtime — produces cleaner, fully typed generated code.
    Skips password-related fields so they never leak into API responses.
    Always includes 'id', 'created_at', 'updated_at' even if absent from IR fields.
    """
    base_fields = ["id", "created_at", "updated_at"]
    field_names = [
        (f.get("name") if isinstance(f, dict) else str(f))
        for f in (fields or [])
        if (f.get("name") if isinstance(f, dict) else str(f)) not in _BANNED_FIELDS
    ]
    # Merge: base fields first, then entity-specific, deduplicated, preserving order
    seen: set = set()
    ordered: list = []
    for fn in base_fields + field_names:
        if fn and fn not in seen and fn not in _BANNED_FIELDS:
            seen.add(fn)
            ordered.append(fn)
    pairs = ", ".join(f'"{fn}": getattr({obj_var}, "{fn}", None)' for fn in ordered)
    return "{" + pairs + "}"


def _get_roles_for_action(entity_name: str, action: str, perm_model: dict | None) -> list | None:
    """Return list of allowed roles for the given entity + action, or None (any authenticated user).

    Reads the p02c permission_model structure:
      permissions: {RoleName: {ResourceName: ["read", "create", "update", "delete"]}}

    Returns a sorted, deduplicated list of role names that have the action permitted,
    or None when no permission model is present so callers fall back to get_current_user.
    """
    if not perm_model:
        return None
    permissions: dict = perm_model.get("permissions", {})
    if not permissions:
        return None
    allowed: list = []
    for role_name, resources in permissions.items():
        if not isinstance(resources, dict):
            continue
        # Wildcard resource ("*") grants all actions to this role
        wildcard = resources.get("*", [])
        if "*" in wildcard or action in wildcard:
            allowed.append(role_name)
            continue
        # Look up this specific entity first, then try case-insensitive match
        actions_for_entity = resources.get(entity_name)
        if actions_for_entity is None:
            # Try case-insensitive fallback
            for res_key, res_actions in resources.items():
                if res_key.lower() == entity_name.lower():
                    actions_for_entity = res_actions
                    break
        if actions_for_entity and ("*" in actions_for_entity or action in actions_for_entity):
            allowed.append(role_name)
    # SuperAdmin always has all permissions — ensure it is present in every allowed list
    # to avoid accidentally locking out the top-level admin role
    super_admin_name = next(
        (r for r in permissions if r.lower() in ("superadmin", "super_admin")), None
    )
    if super_admin_name and super_admin_name not in allowed:
        allowed.append(super_admin_name)
    # Deny by default (KAN-169): once a permission model exists, an action no role covers is admin-only.
    # It used to return None, which meant "any signed-in user", so an entity or action without a grant
    # was open to everyone.
    if not any(r.lower() == "admin" for r in allowed):
        allowed.append("admin")
    return allowed


def _fallback_crud_routers(
    entities: list,
    multi_tenancy: bool = False,
    permission_model: dict | None = None,
) -> str:
    """Fallback CRUD using ORM (no raw SQL — no injection vectors).

    Generates complete typed CRUD with paginated list, get-by-id, create (201),
    patch update, put alias, and delete. Serialization uses entity['fields'] from
    the IR at code-generation time — no __table__.columns runtime introspection.

    When multi_tenancy=True, every list query filters by org_id and every create
    endpoint stamps org_id from the calling user's JWT claims.

    When permission_model is provided (from p02c), each CRUD endpoint uses
    require_role(*roles) instead of get_current_user so that ABAC is enforced
    from the first generated request. Falls back gracefully to get_current_user
    when no model is available.
    """
    # Ensure we always have at least one entity so the schemas import line
    # is never produced with an empty trailing module list (SyntaxError).
    safe_entities = entities if entities else [{"name": "Item", "table": "items"}]
    schemas_imports = ", ".join(
        f"{e.get('name', 'Item')}Create, {e.get('name', 'Item')}Update"
        for e in safe_entities
    )
    lines = [
        "from __future__ import annotations",
        "import logging",
        "from typing import Any, Dict, List, Optional",
        "from fastapi import APIRouter, Depends, HTTPException, Query, status",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select, func",
        "from database import get_db",
        "from auth import get_current_user, require_admin, require_role",
        "import models",
        f"from schemas import {schemas_imports}",
        "try:",
        "    from services.audit_service import log_action as _log_action",
        "except ImportError:",
        "    async def _log_action(*a, **kw): pass",
        # Cache helpers — no-op when Redis is unavailable (REDIS_URL unset)
        "try:",
        "    from cache import cache_get as _cache_get, cache_set as _cache_set, cache_delete as _cache_delete, cache_delete_pattern as _cache_delete_pattern",
        "except ImportError:",
        "    async def _cache_get(k): return None",
        "    async def _cache_set(k, v, ttl=30): pass",
        "    async def _cache_delete(k): pass",
        "    async def _cache_delete_pattern(p): pass",
        "",
        "logger = logging.getLogger(__name__)",
        "",
    ]
    router_vars = []
    for ent in safe_entities:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        var = f"{table}_router"
        router_vars.append(var)
        fields = ent.get("fields", []) or []

        # Pre-build static serialization dicts from entity IR fields
        ser_dict = _entity_serialize_dict(name, fields, obj_var="i")
        ser_dict_obj = _entity_serialize_dict(name, fields, obj_var="obj")

        # Multi-tenancy filter clause (injected into list and get queries)
        mt_list_filter = (
            f".where(models.{name}.org_id == current_user['org_id'])"
            if multi_tenancy else ""
        )
        mt_get_filter = (
            f", models.{name}.org_id == current_user['org_id']"
            if multi_tenancy else ""
        )
        mt_create_kwarg = (
            f", org_id=current_user['org_id']"
            if multi_tenancy else ""
        )

        # Cache key helpers — list key includes org_id when multi-tenancy is on
        list_cache_key = (
            f"f\"{name}:list:{{current_user.get('org_id', '')}}:{{page}}:{{page_size}}\""
            if multi_tenancy
            else f"f\"{name}:list:{{page}}:{{page_size}}\""
        )

        # the single-item cache entry must be per tenant too, or tenant B reads tenant A's row from the cache
        item_cache_key = (
            f"f\"{name}:{{current_user.get('org_id', '')}}:{{item_id}}\""
            if multi_tenancy
            else f"f\"{name}:{{item_id}}\""
        )

        # ── ABAC role guards ─────────────────────────────────────────────────────
        # Resolve allowed roles from the permission model for each action.
        # Falls back to bare get_current_user / require_admin when not available.
        def _dep(action: str, fallback: str = "get_current_user") -> str:
            """Return the Depends() string for the given CRUD action."""
            roles = _get_roles_for_action(name, action, permission_model)
            if roles:
                # Emit require_role("Role1", "Role2", ...) — quoted role names
                quoted = ", ".join(f'"{r}"' for r in roles)
                return f"require_role({quoted})"
            return fallback

        read_dep = _dep("read")
        create_dep = _dep("create")
        update_dep = _dep("update")
        # delete falls back to require_admin (not get_current_user) for safety
        delete_dep = _dep("delete", fallback="require_admin")

        lines += [
            f"{var} = APIRouter(prefix='/{table}', tags=['{name}'])",
            "",
            f"@{var}.get('/', response_model=dict)",
            f"async def list_{table}(",
            f"    page: int = Query(1, ge=1),",
            f"    page_size: int = Query(20, ge=1, le=200),",
            f"    db: AsyncSession = Depends(get_db),",
            f"    current_user: dict = Depends({read_dep}),",
            f"):",
            f"    _ck = {list_cache_key}",
            f"    _cached = await _cache_get(_ck)",
            f"    if _cached is not None:",
            f"        return _cached",
            f"    offset = (page - 1) * page_size",
            f"    total_q = await db.execute(select(func.count()).select_from(models.{name}){mt_list_filter})",
            f"    total = total_q.scalar_one()",
            f"    result = await db.execute(select(models.{name}){mt_list_filter}.offset(offset).limit(page_size))",
            f"    items = result.scalars().all()",
            f"    _resp = {{'items': [{ser_dict} for i in items], 'total': total, 'page': page, 'page_size': page_size}}",
            f"    await _cache_set(_ck, _resp)",
            f"    return _resp",
            "",
            f"@{var}.get('/{{item_id}}', response_model=dict)",
            f"async def get_{table}(item_id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends({read_dep})):",
            f"    _ck = {item_cache_key}",
            f"    _cached = await _cache_get(_ck)",
            f"    if _cached is not None:",
            f"        return _cached",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id{mt_get_filter}))",
            f"    obj = result.scalar_one_or_none()",
            f"    if obj is None:",
            f"        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='{name} not found')",
            f"    _resp = {ser_dict_obj}",
            f"    await _cache_set(_ck, _resp)",
            f"    return _resp",
            "",
            f"@{var}.post('/', status_code=status.HTTP_201_CREATED, response_model=dict)",
            f"async def create_{table}(data: {name}Create, db: AsyncSession = Depends(get_db), current_user: dict = Depends({create_dep})):",
            f"    obj = models.{name}(**data.model_dump(exclude_unset=True){mt_create_kwarg})",
            f"    db.add(obj)",
            f"    await db.flush()",
            f"    await _log_action(db, str(current_user.get('id', '')), 'CREATE', '{name}', str(getattr(obj, 'id', '')))",
            f"    await db.refresh(obj)",
            f"    await _cache_delete_pattern(f\"{name}:list:*\")",
            f"    return {ser_dict_obj}",
            "",
            f"@{var}.patch('/{{item_id}}', response_model=dict)",
            f"async def update_{table}(item_id: int, data: {name}Update, db: AsyncSession = Depends(get_db), current_user: dict = Depends({update_dep})):",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id{mt_get_filter}))",
            f"    obj = result.scalar_one_or_none()",
            f"    if obj is None:",
            f"        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='{name} not found')",
            f"    for k, v in data.model_dump(exclude_unset=True).items():",
            f"        setattr(obj, k, v)",
            f"    await db.flush()",
            f"    await _log_action(db, str(current_user.get('id', '')), 'UPDATE', '{name}', str(item_id))",
            f"    await db.refresh(obj)",
            f"    await _cache_delete({item_cache_key})",
            f"    await _cache_delete_pattern(f\"{name}:list:*\")",
            f"    return {ser_dict_obj}",
            "",
            f"@{var}.put('/{{item_id}}', response_model=dict, include_in_schema=False)",
            f"async def update_{table}_put(item_id: int, data: {name}Update, db: AsyncSession = Depends(get_db), current_user: dict = Depends({update_dep})):",
            f"    return await update_{table}(item_id, data, db, current_user)",
            "",
            f"@{var}.delete('/{{item_id}}', status_code=status.HTTP_204_NO_CONTENT)",
            f"async def delete_{table}(item_id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends({delete_dep})):",
            f"    result = await db.execute(select(models.{name}).where(models.{name}.id == item_id{mt_get_filter}))",
            f"    obj = result.scalar_one_or_none()",
            f"    if obj is None:",
            f"        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='{name} not found')",
            f"    await _log_action(db, str(current_user.get('id', '')), 'DELETE', '{name}', str(item_id))",
            f"    await db.delete(obj)",
            f"    await _cache_delete({item_cache_key})",
            f"    await _cache_delete_pattern(f\"{name}:list:*\")",
            "",
        ]
    # Append auth flow endpoints (forgot-password / reset-password / verify-email)
    auth_flow = _fallback_auth_flow_code()
    lines.append(auth_flow)
    all_router_names = router_vars + ["_auth_flow_router"]
    lines.append(f"all_routers = [{', '.join(all_router_names)}]")
    return "\n".join(lines)


# Re-exports from split modules (file-size limit compliance)
from phases.p04a_backend_codegen.crud_generator_service import _fallback_service_layer  # noqa: F401
from phases.p04a_backend_codegen.crud_generator_seed import _fallback_seed  # noqa: F401
