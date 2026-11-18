"""PromptCompiler — assembles LLM prompts from structured context components.

Combines: constraints (ConstraintEngine) + decisions (accumulated_context) +
error prevention (ErrorRegistry) + few-shot examples + task description.

Enhanced with:
- Context Compression (core/llm/context_compressor.py) — per-phase key filtering
- Knowledge Retrieval Ranking (core/llm/retrieval_ranker.py) — ranked knowledge injection
"""
from __future__ import annotations

import json
import logging

from aether_os.core.llm.context_compressor import compress_context
from aether_os.core.llm.retrieval_ranker import retrieve_for_phase, format_for_prompt

logger = logging.getLogger(__name__)

# ── Human-readable descriptions for error registry categories ────────────────

_ERROR_CATEGORY_RULES = {
    "relative_import": (
        "NEVER use relative imports like `from .models import X` or `from..schemas import X`. "
        "Use absolute imports only: `from models import X`, `from schemas import Y`."
    ),
    "ast_parse_failure": (
        "Generated code must be valid Python. Never leave unclosed brackets, unterminated "
        "strings, or broken f-string expressions. Always test that braces match."
    ),
    "missing_all_routers": (
        "The last line of routers/crud.py MUST be: `all_routers = [router1, router2, ...]`. "
        "main.py iterates this list to mount all routers. Missing it causes a 404 on every endpoint."
    ),
    "seed_unique_violation": (
        "Every unique field (email, slug, file_path) MUST have a distinct value per record. "
        "Do NOT repeat `admin@example.com` across 20 seed records."
    ),
    "missing_router_reference": (
        "Every APIRouter you create must be added to the `all_routers` list. "
        "Routers not in that list are silently dropped and their endpoints become unreachable."
    ),
}


class PromptCompiler:
    """Assembles structured LLM prompts from all available context.

    Section order: CONSTRAINTS → DECISIONS → DO NOT → EXAMPLE → TASK → ENTITIES.
    """

    # ── Public compile methods ─────────────────────────────────────────────────

    def compile_backend_prompt(
        self,
        task_description: str,
        accumulated_context: dict,
        entities: list[dict],
        stack: str = "fastapi",
        phase_name: str = "p04a_backend_codegen",
    ) -> str:
        """Assemble a backend codegen prompt from all available context.

        Returns a complete, structured prompt ready to send to the LLM.
        """
        # Compress context to only what this phase reads before any extraction
        domain = accumulated_context.get("domain", "")
        compressed_ctx = compress_context(phase_name, accumulated_context)

        sections: list[str] = []

        # 1. Hard constraints from ConstraintEngine
        constraints = self._get_backend_constraints(stack)
        if constraints:
            sections.append(self._format_constraints(constraints))

        # 2. Architectural decisions already recorded by upstream phases
        decisions = self._extract_decisions(compressed_ctx)
        if decisions:
            sections.append(self._format_decisions(decisions))

        # 3. Error prevention rules from the live ErrorRegistry
        error_block = self._build_error_prevention_block()
        if error_block:
            sections.append(error_block)

        # 4. Ranked knowledge: domain rules + KG fix patterns + past run warnings
        ranked_knowledge = retrieve_for_phase(phase_name, domain, compressed_ctx)
        knowledge_block = format_for_prompt(ranked_knowledge)
        if knowledge_block:
            sections.append(knowledge_block)

        # 5. Positive few-shot example
        sections.append(self._get_backend_few_shot())

        # 6. Negative examples — what NOT to do
        sections.append(self._get_backend_negative_examples())

        # 7. Task description
        sections.append(f"## YOUR TASK:\n{task_description}")

        # 8. Entities to implement
        sections.append(self._format_entities(entities))

        return "\n\n".join(sections)

    def compile_frontend_prompt(
        self,
        task_description: str,
        accumulated_context: dict,
        entities: list[dict],
        stack: str = "react",
        phase_name: str = "p05_frontend",
    ) -> str:
        """Assemble a frontend codegen prompt from all available context."""
        domain = accumulated_context.get("domain", "")
        compressed_ctx = compress_context(phase_name, accumulated_context)

        sections: list[str] = []

        constraints = self._get_frontend_constraints(stack)
        if constraints:
            sections.append(self._format_constraints(constraints))

        decisions = self._extract_decisions(compressed_ctx)
        if decisions:
            sections.append(self._format_decisions(decisions))

        error_block = self._build_error_prevention_block()
        if error_block:
            sections.append(error_block)

        ranked_knowledge = retrieve_for_phase(phase_name, domain, compressed_ctx)
        knowledge_block = format_for_prompt(ranked_knowledge)
        if knowledge_block:
            sections.append(knowledge_block)

        sections.append(self._get_frontend_few_shot())
        sections.append(f"## YOUR TASK:\n{task_description}")
        sections.append(self._format_entities(entities))

        return "\n\n".join(sections)

    def compile_seed_prompt(
        self,
        task_description: str,
        accumulated_context: dict,
        entities: list[dict],
        phase_name: str = "p04a_backend_codegen",
    ) -> str:
        """Assemble a seed data generation prompt with unique-value constraints."""
        domain = accumulated_context.get("domain", "")
        compressed_ctx = compress_context(phase_name, accumulated_context)

        sections: list[str] = []

        entity_names = [e.get("name", "") for e in entities if e.get("name")]
        constraints = self._get_seed_constraints(entity_names)
        if constraints:
            sections.append(self._format_constraints(constraints))

        decisions = self._extract_decisions(compressed_ctx)
        if decisions:
            sections.append(self._format_decisions(decisions))

        # Always include seed error prevention — uniqueness violations are very common
        sections.append(self._get_seed_negative_examples())

        # Seed-specific knowledge: uniqueness fixes have highest relevance here
        ranked_knowledge = retrieve_for_phase(phase_name, domain, compressed_ctx)
        knowledge_block = format_for_prompt(ranked_knowledge, max_items=3)
        if knowledge_block:
            sections.append(knowledge_block)

        sections.append(self._get_seed_few_shot())
        sections.append(f"## YOUR TASK:\n{task_description}")
        sections.append(self._format_entities(entities))

        return "\n\n".join(sections)

    # ── Formatting helpers ─────────────────────────────────────────────────────

    def _format_constraints(self, constraints: list[str]) -> str:
        """Format constraints as a numbered list with MUST prefix."""
        if not constraints:
            return ""
        lines = ["## CONSTRAINTS (MUST follow all):"]
        for i, rule in enumerate(constraints, start=1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines)

    def _format_decisions(self, decisions: list[dict]) -> str:
        """Format past decisions as a context block."""
        if not decisions:
            return ""
        lines = ["## ARCHITECTURAL DECISIONS (already made — do not change):"]
        for d in decisions:
            key = d.get("key", "?")
            value = d.get("value", "?")
            reason = d.get("reason", "")
            if reason:
                lines.append(f"- {key}: {value}  (reason: {reason})")
            else:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _format_error_prevention(self, error_registry_summary: dict) -> str:
        """Format known error patterns from the registry as DO NOT rules."""
        by_cat = error_registry_summary.get("by_category", {})
        if not by_cat:
            return ""
        lines = ["## DO NOT REPEAT THESE PAST ERRORS:"]
        for cat, info in by_cat.items():
            rule = _ERROR_CATEGORY_RULES.get(cat)
            if rule:
                count = info.get("count", 0)
                lines.append(f"- [{cat} × {count}] {rule}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_entities(self, entities: list[dict]) -> str:
        """Format entity list for LLM consumption."""
        if not entities:
            return "## ENTITIES:\n(none specified)"
        try:
            entity_json = json.dumps(entities[:12], indent=2)
        except Exception as exc:
            logger.warning("prompt_compiler: entity JSON serialisation failed: %s", exc)
            entity_json = str(entities[:12])
        return f"## ENTITIES TO IMPLEMENT:\n```json\n{entity_json}\n```"

    # ── Few-shot examples ──────────────────────────────────────────────────────

    def _get_backend_few_shot(self) -> str:
        """Return a short example of correct CRUD router structure."""
        return """\
## GOOD EXAMPLE — follow this pattern:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db          # ABSOLUTE import — no dot prefix
from models import Product           # ABSOLUTE import
from auth import get_current_user

products_router = APIRouter(prefix="/products", tags=["Products"])

@products_router.get("/", response_model=dict)
async def list_products(
    skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).select_from(Product))).scalar_one()
    items = list((await db.execute(select(Product).offset(skip).limit(limit))).scalars().all())
    return {"items": items, "total": total, "skip": skip, "limit": limit}

all_routers = [products_router]   # LAST LINE — main.py iterates this to mount routers
```"""

    def _get_backend_negative_examples(self) -> str:
        """Return explicit WRONG patterns for backend codegen."""
        return """\
## WRONG PATTERNS — NEVER write any of these:
```python
from .schemas import ProductCreate    # WRONG — relative import (breaks in Docker)
from ..models import Product          # WRONG — relative import
from..database import get_db         # WRONG — relative import

all_router = products_router          # WRONG — must be all_routers = [products_router]
result = await db.execute(select(Product))  # WRONG — no .offset().limit()
return {"password_hash": user.password_hash}  # WRONG — never return password fields
try: ...
except: pass                          # WRONG — bare except swallows errors
```"""

    def _get_frontend_few_shot(self) -> str:
        """Return a short example of correct React component structure."""
        return """\
## GOOD EXAMPLE — follow this pattern:
```tsx
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'  // reads VITE_API_URL — never hard-code localhost
export default function ProductsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['products'],
    queryFn: () => apiClient.get('/products').then(r => r.data),
  })
  if (isLoading) return <div className="animate-pulse">Loading...</div>
  if (error) return <div className="text-red-600">Failed to load products</div>
  return <ul>{data?.items?.map(p => <li key={p.id}>{p.name}</li>)}</ul>
}
```"""

    def _get_seed_few_shot(self) -> str:
        """Return an example of correct seed data with unique values."""
        return """\
## GOOD EXAMPLE — correct seed pattern (unique values per record):
```python
import os
from database import AsyncSessionLocal
from auth import get_password_hash
from models import User, Product
async def seed_database():
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(func.count()).select_from(User))).scalar_one() > 0:
            return
        db.add_all([
            User(email="user1@example.com", password_hash=get_password_hash(os.environ["ADMIN_PASSWORD"]), role="admin"),
            User(email="user2@example.com", password_hash=get_password_hash(os.environ["DEMO_USER_PASSWORD"]), role="user"),
        ])
        db.add_all([
            Product(name="Widget Alpha", slug="product-1", file_path="/files/product-001.pdf"),
            Product(name="Widget Beta",  slug="product-2", file_path="/files/product-002.pdf"),
        ])
        await db.commit()
```"""

    def _get_seed_negative_examples(self) -> str:
        """Return explicit WRONG patterns for seed data generation."""
        return """\
## DO NOT WRITE THESE SEED PATTERNS:
```python
# WRONG — repeating the same email causes DB UNIQUE constraint violation on startup
users = [User(email="admin@example.com") for i in range(20)]
# CORRECT: [User(email=f"user{i}@example.com") for i in range(20)]

# WRONG — same file_path on every document (UNIQUE violation)
docs = [Document(file_path="/file.pdf") for i in range(20)]
# CORRECT: [Document(file_path=f"/files/doc-{i:03d}.pdf") for i in range(20)]

# WRONG — same slug or username
items = [Item(slug="item", username="user") for i in range(20)]
# CORRECT: [Item(slug=f"item-{i}", username=f"user_{i}") for i in range(20)]
```"""

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _extract_decisions(self, accumulated_context: dict) -> list[dict]:
        """Pull the decisions list out of accumulated_context safely."""
        try:
            decisions = accumulated_context.get("decisions", [])
            if isinstance(decisions, list):
                return [d for d in decisions if isinstance(d, dict)]
        except Exception as exc:
            logger.warning("prompt_compiler: could not extract decisions: %s", exc)
        return []

    def _build_error_prevention_block(self) -> str:
        """Load the live ErrorRegistry summary and format it as a DO NOT block."""
        try:
            from aether_os.core.error_registry import get_registry
            summary = get_registry().get_summary()
            return self._format_error_prevention(summary)
        except Exception as exc:
            logger.debug("prompt_compiler: error registry unavailable (non-fatal): %s", exc)
            return ""

    def _get_backend_constraints(self, stack: str) -> list[str]:
        """Fetch constraints from ConstraintEngine with graceful fallback."""
        try:
            from aether_os.core.constraint_engine import ConstraintEngine
            return ConstraintEngine().get_backend_constraints(stack)
        except Exception as exc:
            logger.warning("prompt_compiler: ConstraintEngine unavailable: %s", exc)
            return [
                "Use absolute imports only — never 'from . import' or 'from .. import'.",
                "Export 'all_routers: list' from routers/crud.py.",
                "All email fields must be unique — use user1@example.com pattern.",
                "Every list endpoint must accept skip and limit query params.",
                "All passwords must be bcrypt-hashed, never stored as plaintext.",
            ]

    def _get_seed_constraints(self, entity_names: list[str]) -> list[str]:
        """Fetch seed constraints from ConstraintEngine with graceful fallback."""
        try:
            from aether_os.core.constraint_engine import ConstraintEngine
            return ConstraintEngine().get_seed_constraints(entity_names)
        except Exception as exc:
            logger.warning("prompt_compiler: ConstraintEngine seed unavailable: %s", exc)
            return [
                "Generate exactly 20 records per entity.",
                "All unique fields must have distinct values across all 20 records.",
                "Email fields: use pattern user_{i}@example.com.",
                "file_path fields: use pattern /files/{entity}-{i:03d}.pdf.",
                "Foreign keys must reference IDs that actually exist.",
            ]

    def _get_frontend_constraints(self, stack: str) -> list[str]:
        """Fetch frontend constraints from ConstraintEngine with graceful fallback."""
        try:
            from aether_os.core.constraint_engine import ConstraintEngine
            return ConstraintEngine().get_frontend_constraints(stack)
        except Exception as exc:
            logger.warning("prompt_compiler: ConstraintEngine frontend unavailable: %s", exc)
            return [
                "All API calls must read the base URL from import.meta.env.VITE_API_URL.",
                "Never hard-code 'http://localhost:8000' or any port in source files.",
                "Every form must validate required fields before submitting.",
                "Display a loading state while any async request is in flight.",
                "Show a user-visible error message when an API request fails.",
            ]


# ── Module-level singleton ─────────────────────────────────────────────────────

_compiler: PromptCompiler | None = None


def get_compiler() -> PromptCompiler:
    """Return the module-level singleton PromptCompiler."""
    global _compiler
    if _compiler is None:
        _compiler = PromptCompiler()
    return _compiler
