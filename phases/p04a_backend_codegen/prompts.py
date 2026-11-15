"""P04a Backend Codegen — prompt strings, few-shot examples, and PromptCompiler integration.

All LLM prompt text for CRUD router and model/schema generation lives here.
The compile_* helpers wrap PromptCompiler when available and fall back to the
raw string templates when the compiler is unavailable.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Phase-level LLM temperature ───────────────────────────────────────────────
# Code generation requires precision: low temperature reduces hallucinations
# and keeps generated code syntactically consistent. Callers should pass this
# when invoking llm.call() for CRUD/seed generation.
CODEGEN_TEMPERATURE: float = 0.2
SEED_TEMPERATURE: float = 0.2

# ── Positive few-shot example ─────────────────────────────────────────────────

CRUD_POSITIVE_EXAMPLE = '''\
## GOOD EXAMPLE — follow this pattern exactly:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db          # ABSOLUTE import — no dot prefix
from models import Product           # ABSOLUTE import
from schemas import ProductCreate, ProductUpdate
from auth import get_current_user, require_admin

products_router = APIRouter(prefix="/products", tags=["Products"])

@products_router.get("/", response_model=dict)
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).select_from(Product))).scalar_one()
    items = list((await db.execute(select(Product).offset(skip).limit(limit))).scalars().all())
    return {"items": items, "total": total, "skip": skip, "limit": limit}

@products_router.post("/", status_code=201, response_model=dict)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    obj = Product(**data.model_dump(exclude_unset=True))
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return {c.name: getattr(obj, c.name) for c in Product.__table__.columns
            if c.name not in ("password_hash", "password")}

# ... GET /{id}, PATCH /{id}, DELETE /{id} follow same pattern ...

all_routers = [products_router]   # LAST LINE — main.py iterates this list
```
'''

# ── Negative examples ─────────────────────────────────────────────────────────

CRUD_NEGATIVE_EXAMPLES = '''\
## WRONG PATTERNS — any of these will cause a runtime failure:
```python
# WRONG — relative imports break inside Docker containers
from .schemas import ProductCreate        # WRONG
from ..models import Product              # WRONG
from..database import get_db             # WRONG

# WRONG — variable name typo: must be all_routers (plural list), not all_router
all_router = products_router              # WRONG — main.py cannot find routers
all_routers = products_router            # WRONG — must be a list, not a single router

# WRONG — unbounded list query (no pagination causes OOM on large datasets)
result = await db.execute(select(Product))   # WRONG — missing .offset().limit()

# WRONG — returning the password hash in a response (security breach)
return {"id": user.id, "password_hash": user.password_hash}  # WRONG

# WRONG — bare except swallows all errors and hides bugs
try:
    obj = await db.execute(...)
except:                                   # WRONG — always log
    pass
```
'''

# ── Seed negative examples ────────────────────────────────────────────────────

SEED_NEGATIVE_EXAMPLES = '''\
## DO NOT WRITE THESE SEED PATTERNS (they cause DB UNIQUE constraint violations on startup):
```python
# WRONG — same email repeated for all records
users = [User(email="admin@example.com") for i in range(20)]
# CORRECT: [User(email=f"user{i}@example.com") for i in range(20)]

# WRONG — same file_path on every document
docs = [Document(file_path="/file.pdf") for i in range(20)]
# CORRECT: [Document(file_path=f"/files/doc-{i:03d}.pdf") for i in range(20)]

# WRONG — same slug across all records
items = [Item(slug="item") for i in range(20)]
# CORRECT: [Item(slug=f"item-{i}") for i in range(20)]
```
'''


# ── Compiled prompt builders ──────────────────────────────────────────────────

def build_crud_prompt(
    project_name: str,
    entity_fields_summary: str,
    models_ctx: str,
    schemas_ctx: str,
    mem_hint: str = "",
    multi_tenancy_block: str = "",
    auth_flows_prompt: str = "",
    accumulated_context: dict | None = None,
) -> str:
    """Assemble the full CRUD router generation prompt.

    Uses PromptCompiler when available to prepend constraint + decision context.
    Falls back to the raw template string when the compiler is unavailable.
    """
    # Try PromptCompiler for the structured preamble
    compiler_preamble = ""
    try:
        from aether_os.core.prompt_compiler import get_compiler
        compiler = get_compiler()
        ctx = accumulated_context or {}
        constraints = compiler._get_backend_constraints("fastapi")
        decisions = compiler._extract_decisions(ctx)
        error_block = compiler._build_error_prevention_block()
        parts = []
        if constraints:
            parts.append(compiler._format_constraints(constraints))
        if decisions:
            parts.append(compiler._format_decisions(decisions))
        if error_block:
            parts.append(error_block)
        if parts:
            compiler_preamble = "\n\n".join(parts) + "\n\n"
    except Exception as exc:
        logger.debug("p04a prompts: PromptCompiler unavailable (non-fatal): %s", exc)

    return (
        f'Generate production-quality FastAPI async CRUD routers for "{project_name}".\n'
        + compiler_preamble
        + mem_hint + "\n"
        + multi_tenancy_block + "\n"
        + CRUD_POSITIVE_EXAMPLE + "\n"
        + CRUD_NEGATIVE_EXAMPLES + "\n"
        + """
REQUIRED pagination rules (no exceptions):
- Every GET list endpoint MUST accept: skip: int = 0, limit: int = Query(default=20, le=100)
- Return format: {"items": [...], "total": count, "skip": skip, "limit": limit}
- Never return unbounded lists — always apply .offset(skip).limit(limit)
"""
        + auth_flows_prompt
        + """
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
- Use ABSOLUTE imports only. Do NOT use relative imports.
- Import as: `from database import get_db`, `from models import MyModel`, `from auth import get_current_user`

STRICT REQUIREMENTS — every violation causes runtime errors:
1. `from __future__ import annotations` must be the FIRST line.
2. For EACH domain entity (NOT User): create an APIRouter with prefix and tags.
3. LAST LINE must be: `all_routers = [entity1_router, ...]` listing ALL entity routers.
4. ALL routes require `current_user: dict = Depends(get_current_user)`.
5. DELETE requires `Depends(require_admin)`.
6. SECURITY: Never include `password_hash` or `password` in any response.

Return ONLY the complete Python file. No markdown, no explanation."""
    )


def build_seed_prompt(
    project_name: str,
    domain: str,
    models_ctx: str,
    accumulated_context: dict | None = None,
) -> str:
    """Assemble the seed data generation prompt with unique-value constraints.

    Uses PromptCompiler when available to prepend seed constraints.
    """
    # Try PromptCompiler for constraint preamble
    compiler_preamble = ""
    try:
        from aether_os.core.prompt_compiler import get_compiler
        compiler = get_compiler()
        ctx = accumulated_context or {}
        constraints = compiler._get_seed_constraints([])
        parts = [compiler._format_constraints(constraints)]
        decisions = compiler._extract_decisions(ctx)
        if decisions:
            parts.append(compiler._format_decisions(decisions))
        compiler_preamble = "\n\n".join(parts) + "\n\n"
    except Exception as exc:
        logger.debug("p04a prompts: PromptCompiler seed unavailable (non-fatal): %s", exc)

    return f"""\
Generate a `seed_database()` async function for "{project_name}" ({domain}).

{compiler_preamble}{SEED_NEGATIVE_EXAMPLES}

Complete src/models.py (use EXACT class names from here):
```python
{models_ctx}
```

FILE: src/seed.py

ABSOLUTE IMPORTS RULE: Use absolute imports only — NO relative imports.
Example: `from database import AsyncSessionLocal`, `from auth import get_password_hash`, `from models import User`

REQUIREMENTS:
1. Import: `from database import AsyncSessionLocal`, `from auth import get_password_hash`
2. Import all models from `models` (absolute: `from models import User, ...`)
3. `async def seed_database()` — called on every startup
4. Check if already seeded via count > 0 and return early (idempotent)
5. Create admin user: email="admin@example.com", role="admin"
   Read the admin password from `os.environ.get("ADMIN_PASSWORD")`; if it is not set, generate a random one
   with `secrets.token_urlsafe(16)` and write it to a mode 0600 file. NEVER use a fixed default password
   and NEVER log the password.
6. Create 15-20 realistic records for EACH entity with domain-appropriate values
7. Use `db.add_all([...])` for bulk inserts

Return ONLY the complete seed.py file. No markdown, no explanation."""
