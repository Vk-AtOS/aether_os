"""Fallback seed generator — split from crud_generator.py to keep it under 600 lines.

Provides _fallback_seed() which produces a minimal seed.py for the generated app.
Also provides generate_llm_seed() for LLM-powered domain-plausible seed data
and get_seed_py() which uses LLM-first with _fallback_seed() as fallback.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import textwrap
from typing import Dict, List

logger = logging.getLogger(__name__)


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

    Uniqueness enforcement: any field marked unique=True in the entity definition
    (or implicitly unique by name: email, username, slug, phone, file_path) is seeded
    using an indexed pattern (e.g. "user_1@example.com", "user_2@example.com") so that
    multiple seed records never collide on UNIQUE DB constraints.
    """
    vocab = seed_vocabulary or {}
    prefix = project_name  # used to prefix seed record titles for traceability

    # Fields that are implicitly unique even when not explicitly declared
    _IMPLICIT_UNIQUE_FIELDS = frozenset({"email", "username", "slug", "phone", "file_path"})

    def _is_unique_field(field_def: dict) -> bool:
        """Return True if the field requires unique values in seed data."""
        fname = (field_def.get("name") or "").lower()
        if fname in _IMPLICIT_UNIQUE_FIELDS:
            return True
        return bool(
            field_def.get("unique")
            or "unique" in str(field_def.get("type", "")).lower()
            or "unique" in str(field_def.get("constraints", "")).lower()
        )

    def _seed_value_for_field(field_def: dict, index: int, entity_name: str) -> str:
        """Return a repr()-ready seed value for a field, ensuring uniqueness when needed."""
        fname = (field_def.get("name") if isinstance(field_def, dict) else str(field_def)) or "value"
        fname_lower = fname.lower()
        if fname_lower == "email" or fname_lower.endswith("_email"):
            slug = entity_name.lower().replace(" ", "_")
            return repr(f"{slug}_{index + 1}@example.com")
        if fname_lower in ("username", "login", "handle"):
            slug = entity_name.lower().replace(" ", "_")
            return repr(f"{slug}_{index + 1}")
        if fname_lower == "slug":
            slug = entity_name.lower().replace(" ", "-")
            return repr(f"{slug}-{index + 1}")
        if fname_lower == "phone" or fname_lower.endswith("_phone"):
            return repr(f"+1555000{index + 1:04d}")
        if fname_lower == "file_path":
            return repr(f"/uploads/{entity_name.lower()}_{index + 1}.bin")
        # Generic unique field: append index
        return repr(f"{entity_name} {fname} {index + 1}")

    # Build a small sample of domain-specific records for each entity when vocabulary exists
    entity_blocks = []
    safe_entities = entities[:8] if entities else []
    for ent in safe_entities:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        fields = ent.get("fields", []) or []

        # Identify unique fields so we can enforce uniqueness in seed rows
        unique_field_names = {
            (f.get("name") if isinstance(f, dict) else str(f))
            for f in fields
            if isinstance(f, dict) and _is_unique_field(f)
        }

        # Use vocab list for this entity if available, else generic names
        vocab_list = vocab.get(name, vocab.get(name.lower(), vocab.get(domain, [])))
        if vocab_list:
            sample_names = [repr(f"{prefix} {v}") for v in vocab_list[:5]]
        else:
            sample_names = [repr(f"{prefix} {name} {i + 1}") for i in range(5)]

        # Emit a simple name-field seed if entity has a 'name' field
        has_name_field = any(
            (f.get("name") if isinstance(f, dict) else f) == "name" for f in fields
        )
        if has_name_field and sample_names:
            rows_parts = []
            for i, n in enumerate(sample_names):
                # Build keyword args: name=..., plus unique fields with indexed values
                kwargs = [f"name={n}"]
                for field_def in fields:
                    if not isinstance(field_def, dict):
                        continue
                    fn = field_def.get("name", "")
                    if fn in unique_field_names and fn != "name":
                        kwargs.append(f"{fn}={_seed_value_for_field(field_def, i, name)}")
                rows_parts.append(f"            {name}({', '.join(kwargs)}),")
            rows = "\n".join(rows_parts)
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


async def generate_llm_seed(
    project_name: str,
    entities: list,
    domain: str = "general",
) -> str | None:
    """Ask the LLM to produce a realistic seed.py for the generated app.

    Returns the generated code string if it parses as valid Python, else None.
    Callers should fall back to _fallback_seed() on None.
    """
    from aether_os.core.llm.client import get_llm_client

    entity_summaries = []
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        fields = [
            f.get("name", str(f)) if isinstance(f, dict) else str(f)
            for f in (ent.get("fields") or [])[:10]
        ]
        entity_summaries.append(f"  - {name}: fields={fields}")
    entities_block = "\n".join(entity_summaries) or "  (none)"

    prompt = (
        f'Generate a Python seed.py file for a {domain} application called "{project_name}".\n\n'
        f"Entities:\n{entities_block}\n\n"
        "Requirements:\n"
        "- Import everything from models and database as the generated app does.\n"
        "- Define async def seed_database() -> None: that uses AsyncSessionLocal.\n"
        "- Create exactly 5 realistic, domain-plausible records per entity "
        f"(real names, realistic prices, real dates appropriate for the {domain} domain).\n"
        "- Also create one admin User (email='admin@example.com', role='admin').\n"
        "- Guard with: if (await db.execute(select(func.count()).select_from(User))).scalar_one() > 0: return\n"
        "- Wrap each entity block in try/except Exception as _e: _logger.warning(..., _e)\n"
        "- Return ONLY valid Python code — no markdown fences, no explanation.\n"
    )

    client = get_llm_client()
    try:
        result = await asyncio.wait_for(
            client.call(prompt, task_type="code_generation", max_tokens=4096),
            timeout=90.0,
        )
    except Exception as exc:
        logger.warning("p04a: generate_llm_seed LLM call failed: %s", exc)
        return None

    if not result:
        return None

    # Strip accidental markdown fences
    code = result.strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[-1]
    if code.endswith("```"):
        code = code.rsplit("```", 1)[0]
    code = code.strip()

    try:
        ast.parse(code)
    except SyntaxError as exc:
        logger.warning("p04a: generate_llm_seed produced invalid Python: %s", exc)
        return None

    return code


async def get_seed_py(
    project_name: str,
    entities: list,
    domain: str = "general",
) -> str:
    """LLM-first seed generation with _fallback_seed() fallback."""
    try:
        result = await generate_llm_seed(project_name, entities, domain)
        if result:
            return result
    except Exception as exc:
        logger.warning("p04a: LLM seed failed, using fallback: %s", exc)
    return _fallback_seed(project_name, entities, domain=domain)
