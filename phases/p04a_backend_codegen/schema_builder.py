"""Deterministic (no-LLM) SQLAlchemy model and Pydantic schema builders.

These fallback generators produce syntactically correct code purely from the
entity list when the IR fast-path or LLM codegen is unavailable.
Also provides post-processing helpers to fix common LLM codegen mistakes.
"""
from __future__ import annotations

import re


# ── Type inference ─────────────────────────────────────────────────────────────

def _col_to_sa_type(col_name: str) -> str:
    """Infer SQLAlchemy column type from field name."""
    lower = col_name.lower()
    if lower.endswith("_id"):
        return "Integer, ForeignKey('users.id')" if "user" in lower else "Integer"
    if lower == "email" or lower.endswith("_email"):
        return "String(320), unique=True, index=True"
    if lower in ("phone", "mobile", "tel") or lower.endswith("_phone"):
        return "String(50)"
    if lower in ("price", "amount", "cost", "salary", "rate", "total", "revenue", "balance", "fee"):
        return "Numeric(14, 2)"
    if lower in ("count", "quantity", "qty", "age", "year", "rank", "position", "score") or lower.startswith("num_"):
        return "Integer"
    if lower.startswith("is_") or lower.startswith("has_") or lower.startswith("can_") or lower in ("active", "enabled", "verified", "completed", "archived", "published"):
        return "Boolean, default=True"
    if "date" in lower and lower not in ("updated_at", "created_at"):
        return "DateTime(timezone=True)"
    if lower in ("description", "notes", "body", "content", "bio", "address", "summary", "details", "remarks"):
        return "Text"
    if "url" in lower or "link" in lower or "image" in lower or "photo" in lower:
        return "String(2048)"
    if lower in ("status", "type", "role", "category", "stage", "priority", "gender"):
        return "String(50)"
    return "String(255)"


# ── Fallback model generator ───────────────────────────────────────────────────

def _fallback_models(project_name: str, entities: list) -> str:
    entity_classes = []
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        fields = ent.get("fields", []) or [{"name": "name"}, {"name": "description"}]
        cols = ["    id = Column(Integer, primary_key=True, index=True)"]
        rels = []
        for f in fields[:10]:
            fn = f.get("name", f) if isinstance(f, dict) else str(f)
            if fn in ("id", "created_at", "updated_at"):
                continue
            sa_type = _col_to_sa_type(fn)

            if fn in ("status", "type", "stage", "priority"):
                sa_type += f", CheckConstraint(\"{fn} IN ('active', 'inactive', 'pending', 'open', 'closed', 'new')\", name='ck_{table}_{fn}')"

            nullable = "False" if any(req in fn.lower() for req in ("name", "email", "title", "status")) else "True"
            cols.append(f"    {fn} = Column({sa_type}, nullable={nullable})")

            if fn.endswith("_id") and "user" not in fn:
                ref_name = fn[:-3].capitalize()
                rels.append(f"    {fn[:-3]} = relationship('{ref_name}', foreign_keys=[{fn}], lazy='selectin')")

        cols += rels
        cols += [
            "    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)",
            "    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)",
            "    deleted_at = Column(DateTime(timezone=True), nullable=True)",
        ]
        entity_classes.append(
            f"class {name}(Base):\n    __tablename__ = '{table}'\n" + "\n".join(cols)
        )

    # Build as a plain string to avoid textwrap.dedent misaligning dynamic class bodies.
    # Entity class bodies use 4-space indent; f-string+dedent pattern is unsafe here.
    entity_block = "\n\n\n".join(entity_classes)
    return (
        "from __future__ import annotations\n"
        "from datetime import datetime, timezone\n"
        "from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, Float, ForeignKey, CheckConstraint, func\n"
        "from sqlalchemy.orm import relationship\n"
        "from database import Base\n"
        "\n"
        "\n"
        "class User(Base):\n"
        "    __tablename__ = \"users\"\n"
        "    id = Column(Integer, primary_key=True, index=True)\n"
        "    email = Column(String(255), unique=True, index=True, nullable=False)\n"
        "    password_hash = Column(String(255), nullable=False)\n"
        "    role = Column(String(50), nullable=False, default=\"user\")\n"
        "    is_active = Column(Boolean, nullable=False, default=True)\n"
        "    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)\n"
        "    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)\n"
        + ("\n\n\n" + entity_block + "\n" if entity_block else "\n")
    )


# ── Fallback schema generator ──────────────────────────────────────────────────

def _fallback_schemas(entities: list) -> str:
    blocks = ["from __future__ import annotations", "from pydantic import BaseModel, ConfigDict, Field", "from typing import Optional", "from datetime import datetime", ""]
    blocks += [
        "class UserCreate(BaseModel):",
        "    email: str",
        "    password: str",
        "",
        "class UserResponse(BaseModel):",
        "    model_config = ConfigDict(from_attributes=True)",
        "    id: int",
        "    email: str",
        "    role: str",
        "    is_active: bool",
        "",
    ]
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        fields = ent.get("fields", []) or [{"name": "name"}, {"name": "description"}]
        field_lines = []
        for f in fields[:10]:
            fn = f.get("name", f) if isinstance(f, dict) else str(f)
            if fn in ("id", "created_at", "updated_at"):
                continue
            field_lines.append(f"    {fn}: Optional[str] = None")

        base_fields = field_lines if field_lines else ["    name: Optional[str] = None"]
        update_fields = [f"    {ln.strip().split(':')[0]}: Optional[str] = None" for ln in field_lines] if field_lines else ["    name: Optional[str] = None"]
        blocks += [
            f"class {name}Base(BaseModel):",
        ] + base_fields + [
            "",
            f"class {name}Create({name}Base):",
            "    pass",
            "",
            f"class {name}Update(BaseModel):",
        ] + update_fields + [
            "",
            f"class {name}Response({name}Base):",
            "    model_config = ConfigDict(from_attributes=True)",
            "    id: int",
            "    created_at: Optional[datetime] = None",
            "",
        ]
    return "\n".join(blocks)


# ── Post-processing ────────────────────────────────────────────────────────────

def _fix_common_issues(code: str) -> str:
    """Fix frequent LLM codegen mistakes."""
    # Fix typing.AsyncSession
    code = code.replace("class_=typing.AsyncSession", "class_=AsyncSession")

    # Ensure SQLAlchemy column types used in code are imported
    if "from sqlalchemy import" in code:
        m = re.search(r'^from sqlalchemy import ([^\n]+)', code, re.MULTILINE)
        if m:
            existing = m.group(1)
            needed = ["Float", "JSON", "BigInteger", "Numeric", "Text", "func", "and_", "or_"]
            missing = [t for t in needed if t not in existing and re.search(r'\b' + t + r'\b', code)]
            if missing:
                code = code.replace(m.group(0), m.group(0) + ", " + ", ".join(missing))

    # Fix datetime import in models/crud
    if "datetime.now" in code and "from datetime import datetime" not in code:
        code = "from datetime import datetime, timezone\n" + code
    if "timezone.utc" in code and "from datetime import" in code:
        code = code.replace("from datetime import datetime\n", "from datetime import datetime, timezone\n")

    # Fix: LLM sometimes emits `import timezone` (not a stdlib module) instead of
    # `from datetime import timezone`. Remove the bare import; ensure the correct one is present.
    if re.search(r'^import timezone\b', code, re.MULTILINE):
        code = re.sub(r'^import timezone\b[^\n]*\n?', '', code, flags=re.MULTILINE)
        if "from datetime import" in code:
            code = re.sub(
                r'from datetime import ([^\n]+)',
                lambda m: m.group(0) if "timezone" in m.group(1)
                else m.group(0).rstrip() + ", timezone",
                code, count=1,
            )
        else:
            code = "from datetime import timezone\n" + code

    # Fix: ForeignKey references must match actual __tablename__ values in the same file.
    # Collect declared table names, then verify FK strings against them.
    _tablenames = dict(re.findall(r"__tablename__\s*=\s*['\"](\w+)['\"]", code))
    # Build a map: class_name → tablename (lower)
    _class_to_table: dict = {}
    for _cls, _tbl in re.findall(r'class\s+(\w+)\s*\(Base\)[^:]*:.*?__tablename__\s*=\s*[\'"](\w+)[\'"]', code, re.DOTALL):
        _class_to_table[_cls.lower()] = _tbl
    # For each ForeignKey string, check if the referenced table exists; if not, try to find the right name
    def _fix_fk(m: re.Match) -> str:
        fk_str = m.group(1)
        table_part = fk_str.split(".")[0]
        if table_part in _tablenames.values():
            return m.group(0)  # already correct
        # Try to find a close match among known table names
        import difflib as _dl
        close = _dl.get_close_matches(table_part, list(_tablenames.values()), n=1, cutoff=0.6)
        if close:
            return m.group(0).replace(f"'{fk_str}'", f"'{fk_str.replace(table_part, close[0])}'").replace(
                f'"{fk_str}"', f'"{fk_str.replace(table_part, close[0])}"'
            )
        return m.group(0)
    if _class_to_table:
        code = re.sub(r"ForeignKey\(['\"]([^'\"]+)['\"]\)", _fix_fk, code)

    # Fix missing typing imports (Optional, List, Dict, Any, Union, Tuple)
    _typing_needed = []
    for _t in ("Optional", "List", "Dict", "Any", "Union", "Tuple", "Set"):
        if re.search(r'\b' + _t + r'\b', code) and f"from typing import" not in code.split(_t)[0].split("\n")[-1]:
            _typing_needed.append(_t)
    if _typing_needed:
        if "from typing import" in code:
            m2 = re.search(r'^from typing import ([^\n]+)', code, re.MULTILINE)
            if m2:
                existing_types = [t.strip() for t in m2.group(1).split(",")]
                to_add = [t for t in _typing_needed if t not in existing_types]
                if to_add:
                    code = code.replace(m2.group(0), m2.group(0) + ", " + ", ".join(to_add))
        else:
            code = "from typing import " + ", ".join(_typing_needed) + "\n" + code

    # Remove pydantic v1 imports — always use v2
    code = code.replace("from pydantic.v1 import", "from pydantic import")
    code = code.replace("from pydantic import validator", "from pydantic import field_validator")

    # Fix async SQLAlchemy result fetching (common LLM mistake: .all() not .scalars().all())
    code = re.sub(
        r'(await db\.execute\([^)]+\))\.all\(\)',
        r'\1.scalars().all()',
        code,
    )
    code = re.sub(
        r'(await db\.execute\([^)]+\))\.first\(\)',
        r'\1.scalar_one_or_none()',
        code,
    )
    return code
