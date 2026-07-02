"""Constraint engine — deterministic rule sets injected into every LLM prompt.

The engine compiles per-stack, per-domain constraint blocks so the LLM cannot
hallucinate import paths, invent ORM patterns, or use plaintext passwords.
All rules are hardcoded (no LLM, no external deps).
"""
from __future__ import annotations

from typing import List


class ConstraintEngine:
    """Return constraint lists for backend, seed, and frontend generation."""

    # ── Backend constraints ───────────────────────────────────────────────────

    def get_backend_constraints(self, stack: str = "fastapi") -> List[str]:
        """Return hard constraints for backend code generation."""
        common = [
            "Use absolute imports only — never 'from . import', 'from .. import', or 'from..module import'.",
            "Never use 'import *' — always name every symbol you import.",
            "All SQLAlchemy ORM models must inherit from Base (imported from database.py).",
            "Export 'all_routers: list' from routers/crud.py — main.py iterates it to mount routers.",
            "All passwords must be bcrypt-hashed before storage; never store plaintext.",
            "Every APIRouter must define a 'prefix' and 'tags' argument.",
            "Never redefine symbols that are already declared in the same file.",
            "Every endpoint that modifies data (POST/PUT/PATCH/DELETE) must require auth.",
            "Always include 'from __future__ import annotations' as the first import line.",
            "Return typed Pydantic response models from every endpoint, never raw dicts.",
        ]
        if stack == "fastapi":
            return common + [
                "Import Depends, HTTPException, status from fastapi — not from starlette.",
                "Use 'AsyncSession' from sqlalchemy.ext.asyncio, never the sync Session.",
                "Column definitions must not have duplicate keyword arguments (e.g. two 'default=' values).",
                "Pagination: every list endpoint must accept 'skip: int = 0' and 'limit: int = 100'.",
                "Auth dependency must be 'get_current_user' imported from auth.py (absolute import).",
                "Do not import from 'fastapi.security' directly in crud.py — use the auth.py wrapper.",
            ]
        return common

    # ── Seed constraints ──────────────────────────────────────────────────────

    def get_seed_constraints(self, entities: List[str]) -> List[str]:
        """Return constraints for seed data generation."""
        base = [
            "Generate exactly 20 records per entity — not 5, not 10, exactly 20.",
            "All fields declared unique=True in the model must have unique values across all 20 records.",
            "Email fields: use pattern {entity_lower}_{i}@example.com (e.g. product_1@example.com).",
            "Username fields: use pattern {entity_lower}_user_{i} (e.g. order_user_1).",
            "slug fields: use pattern {entity_lower}-{i} (e.g. product-1, product-2).",
            "file_path fields: use pattern /files/{entity_lower}-{i:03d}.pdf.",
            "Foreign keys must reference IDs that actually exist — generate parent records first.",
            "Never hard-code the same value for a unique field across multiple records.",
            "Passwords in seed data must be bcrypt-hashed using passlib.hash.bcrypt.",
            "Use 'await db.commit()' after every batch insert — do not leave transactions open.",
            "Wrap the entire seed function in try/except so a seed failure never crashes startup.",
        ]
        if entities:
            entity_list = ", ".join(entities)
            base.append(
                f"Generate seed records in dependency order: {entity_list} "
                "(create entities that others FK-reference before the ones that reference them)."
            )
        return base

    # ── Frontend constraints ──────────────────────────────────────────────────

    def get_frontend_constraints(self, stack: str = "react") -> List[str]:
        """Return constraints for frontend code generation."""
        common = [
            "Use absolute imports only — never relative paths like '../../../components/X'.",
            "All API calls must read the base URL from import.meta.env.VITE_API_URL.",
            "Every form must validate required fields before submitting (show inline errors).",
            "A 404 Not Found page must exist and be registered in the router.",
            "Never hard-code 'http://localhost:8000' or any port in source files.",
            "Display a loading state while any async request is in flight.",
            "Show a user-visible error message when an API request fails (not just console.error).",
        ]
        if stack == "react":
            return common + [
                "Use TanStack Router (not react-router-dom) for all routing.",
                "Use TanStack Query (useQuery / useMutation) for all server-state management.",
                "API client must set 'Authorization: Bearer <token>' header from localStorage.",
                "Export every page component as a default export.",
                "Do not import from 'react' directly for hooks — use named imports: import { useState } from 'react'.",
            ]
        return common

    # ── Prompt formatting ─────────────────────────────────────────────────────

    def format_for_prompt(self, constraints: List[str]) -> str:
        """Format a constraint list as a numbered block for LLM prompt injection."""
        if not constraints:
            return ""
        lines = ["HARD CONSTRAINTS (you must follow every rule below):"]
        for i, rule in enumerate(constraints, start=1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines)
