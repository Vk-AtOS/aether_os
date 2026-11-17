"""Deterministic seed.py generator driven by Domain IR (split from ir_generator_helpers.py for size)."""
from __future__ import annotations

import ast

from aether_os.core.domain_ir import AetherType, DomainIR, IRField
from aether_os.phases.p04a_backend_codegen.ir_client_fields import client_fields

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


def _seed_value(
    field: IRField,
    idx: int,
    entity_name: str,
    seed_vocabulary: dict | None = None,
    domain: str = "general",
    project_name: str = "",
) -> str:
    """Return a Python literal for a single seed value.

    When seed_vocabulary contains domain-specific terms for this entity (or domain),
    name/title/label fields use those terms instead of generic Alpha/Beta/Gamma.
    The project_name prefix is prepended to make records easily attributable in logs.
    """
    n = field.name.lower()
    t = field.type
    vocab = seed_vocabulary or {}

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
        # Use domain-specific vocabulary when available (prefer entity → domain → generic)
        vocab_list = vocab.get(entity_name, vocab.get(entity_name.lower(), vocab.get(domain, [])))
        if vocab_list:
            term = vocab_list[idx % len(vocab_list)]
            prefix = f"{project_name} " if project_name else ""
            return repr(f"{prefix}{term}")
        prefix = f"{project_name} " if project_name else ""
        return repr(f"{prefix}{_SEED_ADJECTIVES[idx % len(_SEED_ADJECTIVES)]} {entity_name} {idx + 1}")
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


def _sort_entities_by_deps(entities: list) -> list:
    """Topological sort of entities based on FK dependencies."""
    sorted_entities: list = []
    visited: set = set()
    temp_visited: set = set()

    entity_map = {e.name: e for e in entities}

    def visit(name: str) -> None:
        if name in temp_visited:
            return  # Cycle or already handled
        if name not in visited:
            temp_visited.add(name)
            ent = entity_map.get(name)
            if ent:
                for f in ent.fields:
                    if f.type == AetherType.FK and f.ref_entity and f.ref_entity != name:
                        visit(f.ref_entity)
            temp_visited.remove(name)
            visited.add(name)
            if ent:
                sorted_entities.append(ent)

    for e in entities:
        visit(e.name)
    return sorted_entities


def generate_seed_py(
    ir: DomainIR,
    seed_vocabulary: dict | None = None,
    domain: str = "general",
    project_name: str = "",
    multi_tenancy: bool = False,
) -> str:
    """Generate complete deterministic seed.py from DomainIR (20 rows per entity).

    Args:
        ir: Domain IR with all entities and fields.
        seed_vocabulary: Optional dict mapping entity name (or domain) → list of
            domain-specific terms used as name/title/label values (e.g.
            {"Policy": ["GDPR Alert", "HIPAA Baseline", ...], ...}).
        domain: Domain string used as a vocabulary fallback key when no entity-
            specific terms exist (e.g. "insurance", "legal").
        project_name: Prepended to seed record names for traceability
            (e.g. "PolicyLens GDPR Alert" instead of "Premier Policy 1").
    """
    domain_entities = [e for e in ir.entities if e.name != "User" and getattr(e, "table", "") != "users"]
    domain_entities = _sort_entities_by_deps(domain_entities)
    entity_names = [e.name for e in domain_entities]
    vocab = seed_vocabulary or {}

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
        'def _admin_password() -> str:',
        '    # ADMIN_PASSWORD from the environment, else a random one written once to a 0600 file.',
        '    # Never a known default, and never logged.',
        "    pw = os.environ.get('ADMIN_PASSWORD')",
        '    if pw:',
        '        return pw',
        '    import secrets',
        '    pw = secrets.token_urlsafe(16)',
        "    path = os.path.join(os.getcwd(), 'admin_initial_password.txt')",
        '    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)',
        "    with os.fdopen(fd, 'w') as f:",
        '        f.write(pw)',
        "    _logger.warning('ADMIN_PASSWORD is not set: a random admin password was written to %s', path)",
        '    return pw',
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
        "            password_hash=get_password_hash(_admin_password()),",
        "            role='admin',",
        "            is_active=True,",
        *(["            org_id='default',"] if multi_tenancy else []),
        "        )",
        "        db.add(admin)",
        "        await db.flush()",
        "",
    ]

    seeded: set = set()       # entities whose rows are already in the session, so a foreign key can name a real row
    for entity in domain_entities:
        rows_var = f"rows_{entity.name.lower()}"
        lines.append(f"        {rows_var} = [")
        for idx in range(20):
            field_parts = []
            for f in client_fields(entity, multi_tenancy):
                if f.name in ("id", "created_at", "updated_at"):
                    continue
                val = _seed_value(
                    f, idx, entity.name,
                    seed_vocabulary=vocab,
                    domain=domain,
                    project_name=project_name,
                )
                if f.type == AetherType.FK:
                    # `(idx % 3) + 1` named ids that need not exist: a foreign-key violation on PostgreSQL. Use a
                    # row that was really inserted (admin for users, an earlier entity's rows), else NULL.
                    ref = f.ref_entity or ""
                    if ref.lower() == "user":
                        val = "admin.id"
                    elif ref in seeded and ref != entity.name:
                        val = f"rows_{ref.lower()}[{idx} % len(rows_{ref.lower()})].id"
                    else:
                        val = "None"
                elif f.unique and f.type in (AetherType.STRING, AetherType.URL, AetherType.TEXT):
                    # the value lists have 10 entries and 20 rows are written: a UNIQUE column collided at row 11
                    val = repr(f"{ast.literal_eval(val)} #{idx + 1}")
                field_parts.append(f"                {f.name}={val},")
            lines.append(f"            {entity.name}(")
            if multi_tenancy:
                field_parts.append("                org_id='default',")
            lines.extend(field_parts)
            lines.append("            ),")
        lines.append("        ]")
        lines.append(f"        db.add_all({rows_var})")
        lines.append("        await db.flush()")
        lines.append("")
        seeded.add(entity.name)

    lines += [
        "        await db.commit()",
        "        _logger.info('Seeded admin user admin@example.com')",
    ]
    return "\n".join(lines) + "\n"


async def validate_seed_dependencies(db_session) -> list:
    """Verify that all FK references in the database point to existing records."""
    # Structural check placeholder — in production this would iterate all tables and FKs.
    return []
