"""Deterministic (no-LLM) SQLAlchemy model and Pydantic schema builders.

These fallback generators produce syntactically correct code purely from the
entity list when the IR fast-path or LLM codegen is unavailable.
Also provides post-processing helpers to fix common LLM codegen mistakes.
"""
from __future__ import annotations

import re


# ── AetherType → Pydantic type mapping ────────────────────────────────────────

# Standard imports block emitted at the top of every generated schemas.py
_SCHEMA_IMPORTS = """\
from __future__ import annotations
from decimal import Decimal
from datetime import datetime, date
from uuid import UUID
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field
"""

# Keywords in field *names* that imply a monetary/numeric type regardless of
# the explicit AetherType.  This catches LLM-generated fields whose type was
# set to "string" by mistake (e.g. price: string).
_MONEY_NAME_KEYWORDS = frozenset({
    "price", "amount", "cost", "salary", "rate", "total", "revenue",
    "balance", "fee", "tax", "discount", "subtotal", "markup",
})


def _aether_type_to_pydantic(aether_type: str, field_name: str = "") -> str:
    """Map an AetherType string (from Domain IR) to a Pydantic Optional[T] annotation."""
    t = (aether_type or "string").lower().strip()
    fn = (field_name or "").lower()

    if any(kw in fn for kw in _MONEY_NAME_KEYWORDS):
        return "Optional[Decimal]"
    if t in ("int", "integer", "bigint", "smallint"):
        return "Optional[int]"
    if t in ("float", "double", "real", "number"):
        return "Optional[float]"
    if t in ("decimal", "numeric", "money", "amount", "price", "cost", "salary"):
        return "Optional[Decimal]"
    if t in ("bool", "boolean"):
        return "Optional[bool]"
    if t in ("datetime", "timestamp", "timestamptz"):
        return "Optional[datetime]"
    if t == "date":
        return "Optional[date]"
    if t in ("uuid",):
        return "Optional[UUID]"
    if t in ("json", "jsonb", "dict", "object"):
        return "Optional[Dict[str, Any]]"
    if t in ("list", "array"):
        return "Optional[List[Any]]"
    if t == "fk":
        return "Optional[int]"
    return "Optional[str]"


# ── Domain constraint helpers ──────────────────────────────────────────────────

_MONEY_DOMAINS = frozenset({"fintech", "marketplace", "erp"})

_MONEY_FIELDS = frozenset({
    "amount", "price", "cost", "salary", "balance", "fee", "total",
    "subtotal", "tax_amount", "revenue", "daily_limit", "monthly_limit",
    "refund_amount", "discount", "commission",
})

_PHI_FIELDS = frozenset({
    "dob", "date_of_birth", "ssn", "mrn", "patient_id",
    "diagnosis", "symptoms", "treatment_plan", "instructions",
})

_AUDIT_SUFFIXES = ("_at", "_by")
_AUDIT_PREFIXES = ("created_", "updated_")


def _is_healthcare(domain: str) -> bool:
    return domain.lower() in ("healthcare", "hipaa")


def _is_money_domain(domain: str) -> bool:
    return domain.lower() in _MONEY_DOMAINS


def _needs_audit_annotation(field_name: str) -> bool:
    lower = field_name.lower()
    return (
        any(lower.endswith(s) for s in _AUDIT_SUFFIXES)
        or any(lower.startswith(p) for p in _AUDIT_PREFIXES)
    )


# ── Type inference ─────────────────────────────────────────────────────────────

def _col_to_sa_type(col_name: str, domain: str = "") -> str:
    """Infer SQLAlchemy column type from field name.

    When domain is a money domain (fintech/marketplace/erp), monetary fields
    are forced to Numeric(12, 2) instead of the generic Numeric(14, 2) so that
    generated code satisfies PCI/domain-pack constraints without relying on the LLM.
    """
    lower = col_name.lower()
    if lower.endswith("_id"):
        return "Integer, ForeignKey('users.id')" if "user" in lower else "Integer"
    if lower == "email" or lower.endswith("_email"):
        return "String(320), unique=True, index=True"
    if lower in ("phone", "mobile", "tel") or lower.endswith("_phone"):
        return "String(50)"
    if lower in _MONEY_FIELDS:
        # Money domains require Numeric; other domains get the same type for safety.
        return "Numeric(12, 2)" if _is_money_domain(domain) else "Numeric(14, 2)"
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


def _col_comment(field_name: str, domain: str) -> str:
    """Return an inline comment to append to a Column line, or empty string.

    Healthcare domain: PHI fields get # PHI - handle per HIPAA.
    """
    if _is_healthcare(domain) and field_name.lower() in _PHI_FIELDS:
        return "  # PHI - handle per HIPAA"
    return ""


# ── Fallback model generator ───────────────────────────────────────────────────

def _fallback_models(project_name: str, entities: list, domain: str = "", multi_tenancy: bool = False) -> str:
    """Generate SQLAlchemy models from entity list.

    domain: if provided, domain-specific column types are applied (e.g. Numeric
    for money fields in fintech/marketplace/erp).
    multi_tenancy: the users table and every entity table get an org_id column (the CRUD routers filter on it;
    without the column every request raised AttributeError, KAN-169).
    """
    entity_classes = []
    # `<x>_id` links to an entity only when one named <x> exists in this app: (class name, table) by lowered name
    _entity_by_key = {
        str(e.get("name", "")).replace("_", "").lower(): (e.get("name"), e.get("table") or str(e.get("name", "")).lower() + "s")
        for e in entities if e.get("name")
    }
    for ent in entities:
        name = ent.get("name", "Item")
        table = ent.get("table", name.lower() + "s")
        fields = ent.get("fields", []) or [{"name": "name"}, {"name": "description"}]
        cols = ["    id = Column(Integer, primary_key=True, index=True)"]
        rels = []
        for f in fields:
            fn = f.get("name", f) if isinstance(f, dict) else str(f)
            if fn in ("id", "created_at", "updated_at") or (multi_tenancy and fn == "org_id"):
                continue
            sa_type = _col_to_sa_type(fn, domain)
            _target = _entity_by_key.get(fn[:-3].replace("_", "").lower()) if fn.endswith("_id") and "user" not in fn else None
            if _target:
                sa_type = f"Integer, ForeignKey('{_target[1]}.id')"

            if fn in ("status", "type", "stage", "priority"):
                sa_type += f", CheckConstraint(\"{fn} IN ('active', 'inactive', 'pending', 'open', 'closed', 'new')\", name='ck_{table}_{fn}')"

            nullable = "False" if any(req in fn.lower() for req in ("name", "email", "title", "status")) else "True"
            comment = _col_comment(fn, domain)
            cols.append(f"    {fn} = Column({sa_type}, nullable={nullable}){comment}")

            # Healthcare HIPAA: add audit_columns annotation comment for audit fields
            if _is_healthcare(domain) and _needs_audit_annotation(fn):
                cols.append(f"    # audit_columns: {fn} required for HIPAA audit trail")

            if _target:
                # no ForeignKey / no such entity used to leave a relationship SQLAlchemy could not configure,
                # which failed the first query of every request (KAN-169)
                rels.append(f"    {fn[:-3]} = relationship('{_target[0]}', foreign_keys=[{fn}], lazy='selectin')")

        cols += rels
        if multi_tenancy:
            cols.append("    org_id = Column(String(64), nullable=False, index=True)")
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
    # Money domains need Decimal import; include it unconditionally (harmless if unused).
    decimal_import = "from decimal import Decimal\n" if _is_money_domain(domain) else ""
    return (
        "from __future__ import annotations\n"
        "from datetime import datetime, timezone\n"
        + decimal_import
        + "from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, Float, ForeignKey, CheckConstraint, func\n"
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
        "    full_name = Column(String(255), nullable=True)\n"   # the generated Users page shows and edits it
        + ("    org_id = Column(String(64), nullable=True, index=True)\n" if multi_tenancy else "")
        + "    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)\n"
        "    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)\n"
        + ("\n\n\n" + entity_block + "\n" if entity_block else "\n")
    )


# ── Fallback schema generator ──────────────────────────────────────────────────

def _fallback_schemas(entities: list, domain: str = "") -> str:
    """Generate Pydantic schemas from entity list with domain-aware types."""
    # Always emit full imports — Decimal/UUID etc. are referenced by _aether_type_to_pydantic
    blocks = _SCHEMA_IMPORTS.splitlines() + [""]
    blocks += [
        "class UserCreate(BaseModel):",
        "    model_config = ConfigDict(extra='ignore')",
        "    email: str",
        "    password: str",
        "",
        "class UserResponse(BaseModel):",
        "    model_config = ConfigDict(from_attributes=True, extra='ignore')",
        "    id: int",
        "    email: str",
        "    role: str",
        "    is_active: bool",
        "",
    ]
    # Fields that must never appear in response/read schemas (security: password exposure)
    _RESPONSE_EXCLUDED_FIELDS = {"password_hash", "password", "hashed_password"}

    for ent in entities:
        name = ent.get("name", "Item")
        fields = ent.get("fields", []) or [{"name": "name"}, {"name": "description"}]
        all_field_lines = []
        response_field_lines = []
        for f in fields:
            fn = f.get("name", f) if isinstance(f, dict) else str(f)
            if fn in ("id", "created_at", "updated_at"):
                continue
            # Derive correct Pydantic type from IR AetherType; domain overrides apply on top
            atype = f.get("type", "string") if isinstance(f, dict) else "string"
            pydantic_type = _aether_type_to_pydantic(atype, fn)
            # Domain override: force Decimal for money fields in money domains
            if _is_money_domain(domain) and fn.lower() in _MONEY_FIELDS:
                pydantic_type = "Optional[Decimal]"
            # PHI comment for healthcare
            phi_comment = "  # PHI - handle per HIPAA" if _is_healthcare(domain) and fn.lower() in _PHI_FIELDS else ""
            # Audit annotation for healthcare
            audit_comment = "  # audit_columns" if _is_healthcare(domain) and _needs_audit_annotation(fn) else ""
            suffix = phi_comment or audit_comment

            all_field_lines.append(f"    {fn}: {pydantic_type} = None{suffix}")
            if fn not in _RESPONSE_EXCLUDED_FIELDS:
                response_field_lines.append(f"    {fn}: {pydantic_type} = None{suffix}")

        base_fields = response_field_lines if response_field_lines else ["    name: Optional[str] = None"]
        # Update schemas keep the same inferred types (all Optional so PATCH works correctly)
        update_fields = all_field_lines if all_field_lines else ["    name: Optional[str] = None"]
        blocks += [
            f"class {name}Base(BaseModel):",
            "    model_config = ConfigDict(extra='ignore')",
        ] + base_fields + [
            "",
            f"class {name}Create({name}Base):",
            "    pass",
            "",
            f"class {name}Update(BaseModel):",
            "    model_config = ConfigDict(extra='ignore')",
        ] + update_fields + [
            "",
            f"class {name}Response({name}Base):",
            "    model_config = ConfigDict(from_attributes=True, extra='ignore')",
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
        if re.search(r'\b' + _t + r'\b', code) and "from typing import" not in code.split(_t)[0].split("\n")[-1]:
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
