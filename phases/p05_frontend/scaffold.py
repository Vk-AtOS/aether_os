"""P05 Frontend — scaffold helpers: naming, typing, schema utilities, architecture reader.

Provides all the utility functions used to transform entity/schema data into
names, TypeScript types, field definitions, and icon mappings.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.phases.p05_frontend.prompts import (
    DOMAIN_KEYWORDS,
    LUCIDE_ICON_MAP,
    ENTITY_EMOJI_MAP,
)

logger = logging.getLogger(__name__)

# ── Columns to exclude from display and forms ─────────────────────────────────
EXCLUDED_COLS = frozenset([
    "id", "created_at", "updated_at", "deleted_at",
    "password", "password_hash", "token",
])


# ── Domain detection ──────────────────────────────────────────────────────────

def detect_domain(phase_input: Any) -> str:
    """Detect application domain from project description and entity names."""
    # Only trust the pre-resolved domain if it's a specific domain, not the generic fallbacks.
    _pre = (getattr(phase_input, "domain", None) or "").lower().strip()
    if _pre and _pre not in ("", "unknown", "general", "saas", "ecommerce"):
        return _pre

    data = (
        phase_input.input_data
        if hasattr(phase_input, "input_data")
        else (phase_input if isinstance(phase_input, dict) else {})
    )
    description = (
        data.get("description")
        or data.get("prompt")
        or data.get("raw_input")
        or data.get("project_name")
        or ""
    ).lower()
    entities = [e.get("name", "").lower() for e in data.get("entities", [])]
    all_text = description + " " + " ".join(entities)

    scores: Dict[str, int] = {}
    for domain, weighted_kws in DOMAIN_KEYWORDS.items():
        total = 0
        for item in weighted_kws:
            kw, weight = item if isinstance(item, tuple) else (item, 1)
            if kw in all_text:
                total += weight
        if total > 0:
            scores[domain] = total

    if scores:
        best = max(scores, key=lambda d: scores[d])
        if scores[best] >= 3:
            return best

    return "saas"


# ── Architecture reader ────────────────────────────────────────────────────────

def read_architecture(data: dict) -> dict:
    """Return architecture dict from any known location, augmented with real API routes."""
    arch: Optional[dict] = None

    arch_path = data.get("p02_architecture_path", "")
    if arch_path:
        try:
            arch = json.loads(Path(arch_path).read_text())
        except Exception as exc:
            logger.debug("p05: failed to read architecture from path %s (non-fatal): %s", arch_path, exc)

    if arch is None:
        _arch_inline = data.get("architecture_json")
        if isinstance(_arch_inline, dict) and (
            _arch_inline.get("database_schema") or _arch_inline.get("entities")
        ):
            arch = _arch_inline
            logger.debug("p05: architecture from inline architecture_json (%d tables)",
                         len(_arch_inline.get("database_schema", [])))

    if arch is None:
        project_dir = Path(data.get("project_dir", ""))
        if project_dir.exists():
            for candidate in sorted(project_dir.rglob("architecture.json"))[:3]:
                try:
                    arch = json.loads(candidate.read_text())
                    break
                except Exception as e:
                    logger.warning("p05_frontend scaffold: could not parse %s: %s", candidate, e)
                    continue

    if arch is None:
        arch = {
            "api_endpoints": [
                {"method": "GET",    "path": "/health",        "description": "Health check", "auth": False},
                {"method": "POST",   "path": "/auth/login",    "description": "Login",        "auth": False},
                {"method": "POST",   "path": "/auth/register", "description": "Register",     "auth": False},
                {"method": "GET",    "path": "/items",         "description": "List items",   "auth": True},
                {"method": "POST",   "path": "/items",         "description": "Create item",  "auth": True},
                {"method": "PUT",    "path": "/items/{id}",    "description": "Update item",  "auth": True},
                {"method": "DELETE", "path": "/items/{id}",    "description": "Delete item",  "auth": True},
            ],
            "database_schema": [
                {"table": "items", "columns": ["id", "name", "description", "status", "created_at"]}
            ],
            "tech_stack": {"backend": "FastAPI", "frontend": "React", "database": "SQLite"},
        }

    # Inject real endpoint paths + augment schema from p04's route manifest
    api_routes_path = data.get("api_routes_path", "")
    if api_routes_path:
        try:
            routes = json.loads(Path(api_routes_path).read_text())
            route_map: Dict[str, str] = {}
            for r in routes:
                if r.get("method") == "GET" and "{" not in r.get("path", ""):
                    # The backend serves everything under /api and the generated client's baseURL already ends in
                    # /api: strip the prefix, or the table is read as "api" (one entry for every route) and any
                    # path that is kept would be requested as /api/api/x.
                    path = re.sub(r"^/api(?=/|$)", "", r["path"]).rstrip("/") or "/"
                    table = path.lstrip("/").split("/")[0]
                    if table and table not in ("health", "ready", "metrics", "docs", "openapi.json", "redoc", "admin",
                                               "auth", "stats", "realtime", "pipeline-events"):
                        route_map[table] = path
            if route_map:
                arch["api_route_map"] = route_map
                logger.info("p05: loaded route_map with %d entries: %s", len(route_map), route_map)

                existing_tables = {
                    e.get("table", e.get("name", "")).lower()
                    for e in arch.get("database_schema", [])
                }
                missing_tables = [t for t in route_map if t.lower() not in existing_tables]
                if missing_tables:
                    cols_by_table = extract_columns_from_main_py(data, missing_tables)
                    schema = list(arch.get("database_schema", []))
                    for table in missing_tables:
                        schema.append({
                            "table": table,
                            "columns": cols_by_table.get(table, ["id", "name", "status", "created_at"])
                        })
                    arch["database_schema"] = schema
                    logger.info("p05: augmented schema with %d tables from route_map: %s",
                                len(missing_tables), missing_tables)
        except Exception as exc:
            logger.warning("p05: could not load api_routes_path %s: %s", api_routes_path, exc)

    return arch


def extract_columns_from_main_py(data: dict, tables: List[str]) -> Dict[str, List[str]]:
    """Extract real column names from the generated backend.

    Strategy 1 (preferred): parse SQLAlchemy Column() definitions from models.py.
    Strategy 2 (fallback): original CREATE TABLE regex scan of main.py.
    """
    cols_by_table: Dict[str, List[str]] = {}
    backend_out = data.get("backend_output_path", "") or data.get("p04_backend_path", "")

    # ── Strategy 1: SQLAlchemy ORM in models.py ──────────────────────────────
    if backend_out:
        p = Path(backend_out)
        models_candidates = [
            p / "src" / "models.py",
            p.parent / "src" / "models.py",
            p.parent / "backend_codegen" / "src" / "models.py",
        ]
        for models_path in models_candidates:
            if not models_path.exists():
                continue
            try:
                code = models_path.read_text()
                current_table: str = ""
                current_cols: List[str] = []
                for line in code.splitlines():
                    tm = re.search(r'__tablename__\s*=\s*["\'](\w+)["\']', line)
                    if tm:
                        if current_table and current_cols:
                            cols_by_table[current_table] = current_cols
                        current_table = tm.group(1).lower()
                        current_cols = []
                        continue
                    cm = re.match(r'\s{4}(\w+)\s*=\s*Column\(', line)
                    if cm and current_table:
                        col_name = cm.group(1)
                        if col_name not in ("id",) and not col_name.startswith("_"):
                            current_cols.append(col_name)
                if current_table and current_cols:
                    cols_by_table[current_table] = current_cols
                if cols_by_table:
                    logger.info("p05: extracted %d tables from models.py", len(cols_by_table))
                    return cols_by_table
            except Exception as exc:
                logger.warning("p05: models.py parse failed: %s", exc)

    # ── Strategy 2: legacy CREATE TABLE scan of main.py ──────────────────────
    main_py_path = data.get("backend_main_py", "")
    if not main_py_path and backend_out:
        p = Path(backend_out)
        for candidate in [p / "src" / "main.py", p.parent / "src" / "main.py",
                           p.parent / "backend_codegen" / "src" / "main.py"]:
            if candidate.exists():
                main_py_path = str(candidate)
                break
    if main_py_path and Path(main_py_path).exists():
        try:
            code = Path(main_py_path).read_text()
            for m in re.finditer(
                r"CREATE TABLE IF NOT EXISTS (\w+)\s*\(([^)]+)\)",
                code, re.IGNORECASE
            ):
                table_name = m.group(1).lower()
                if table_name in tables:
                    col_defs = m.group(2)
                    cols = []
                    for col_def in col_defs.split(","):
                        col_def = col_def.strip()
                        col_name = col_def.split()[0] if col_def.split() else ""
                        if col_name and col_name.upper() not in (
                            "PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"
                        ):
                            cols.append(col_name)
                    if cols:
                        cols_by_table[table_name] = cols
        except Exception as exc:
            logger.warning("p05: _extract_columns_from_main_py failed: %s", exc)
    return cols_by_table


def extract_all_entities_from_models_py(data: dict) -> List[dict]:
    """Parse models.py directly to get ALL non-user entities with their column names.

    Used when architecture.json has no database_schema (thin LLM output).
    Falls back gracefully — returns empty list if models.py can't be found/parsed.
    """
    backend_out = data.get("backend_output_path", "") or data.get("p04_backend_path", "")
    if not backend_out:
        return []

    p = Path(backend_out)
    candidates = [
        p / "src" / "models.py",
        p.parent / "src" / "models.py",
        p.parent / "backend_codegen" / "src" / "models.py",
    ]

    for models_path in candidates:
        if not models_path.exists():
            continue
        try:
            code = models_path.read_text()
            entities: List[dict] = []
            current_table: str = ""
            current_cols: List[str] = []
            skip_table = False

            for line in code.splitlines():
                if re.match(r'^class \w+\(Base\)', line):
                    if current_table and current_cols and not skip_table:
                        entities.append({"table": current_table, "columns": current_cols})
                    current_table = ""
                    current_cols = []
                    skip_table = False

                tm = re.search(r'__tablename__\s*=\s*["\'](\w+)["\']', line)
                if tm:
                    tbl = tm.group(1).lower()
                    skip_table = tbl in ("users", "user", "auth_users")
                    current_table = tbl
                    current_cols = []
                    continue

                cm = re.match(r'\s{4}(\w+)\s*=\s*Column\(', line)
                if cm and current_table and not skip_table:
                    col = cm.group(1)
                    if not col.startswith("_"):
                        current_cols.append(col)

            if current_table and current_cols and not skip_table:
                entities.append({"table": current_table, "columns": current_cols})

            if entities:
                logger.info(
                    "p05: extracted %d entities from models.py: %s",
                    len(entities), [e["table"] for e in entities],
                )
                return entities
        except Exception as exc:
            logger.warning("p05: _extract_all_entities_from_models_py failed: %s", exc)

    return []


# ── Schema helpers ─────────────────────────────────────────────────────────────

def normalise_entities(arch: dict) -> List[dict]:
    """Return list of {table, columns: [str]} dicts, skipping users/auth tables."""
    raw_schema = arch.get("database_schema", arch.get("db_schema", []))
    entities: List[dict] = []
    seen: set = set()
    for entry in raw_schema:
        table = entry.get("table", entry.get("name", ""))
        if not table or table in seen:
            continue
        seen.add(table)
        cols_raw = entry.get("columns", [])
        cols: List[str] = []
        for c in cols_raw:
            if isinstance(c, dict):
                cols.append(c.get("name", c.get("column", "")))
            else:
                cols.append(str(c))
        entities.append({"table": table, "columns": [c for c in cols if c]})

    if not entities:
        _ir_entities = arch.get("entities", [])
        for ent in _ir_entities:
            ent_name = ent.get("name", ent.get("table", ""))
            if not ent_name:
                continue
            _table = re.sub(r'([A-Z])', lambda m: '_' + m.group(1).lower(), ent_name).lstrip('_')
            if _table in seen:
                continue
            seen.add(_table)
            _cols: List[str] = []
            for field in ent.get("fields", ent.get("columns", ent.get("attributes", []))):
                if isinstance(field, dict):
                    _cols.append(field.get("name", field.get("column", "")))
                elif isinstance(field, str):
                    _cols.append(field)
            if not _cols:
                _cols = ["id", "name", "status", "created_at"]
            entities.append({"table": _table, "name": ent_name, "columns": [c for c in _cols if c]})

    entities = [e for e in entities if e["table"].lower() not in ("users",)]
    if not entities:
        entities = [{"table": "items", "columns": ["id", "name", "description", "status", "created_at"]}]
    return entities


# ── Naming utilities ───────────────────────────────────────────────────────────

def pluralise(word: str) -> str:
    """English pluralisation for FK endpoint derivation."""
    w = word.lower()
    if w.endswith("ies") or w.endswith("ses") or w.endswith("xes") or w.endswith("ches") or w.endswith("shes"):
        return w  # already plural
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        return w[:-1] + "ies"
    if w.endswith("ss") or w.endswith("sh") or w.endswith("ch") or w.endswith("x") or w.endswith("z"):
        return w + "es"
    if w.endswith("s"):
        return w  # already plural
    return w + "s"


def to_pascal_case(s: str) -> str:
    """Convert snake_case or camelCase string to PascalCase. 'lead_contacts' → 'LeadContacts'."""
    s = re.sub(r'([a-z])([A-Z])', r'\1_\2', s)
    parts = re.split(r'[_\-\s]+', s)
    return "".join(p.capitalize() for p in parts if p)


def to_type_name(table: str) -> str:
    """Convert table name to singular PascalCase TypeScript type name.
    'patients' → 'Patient', 'lead_contacts' → 'LeadContact'
    """
    pascal = to_pascal_case(table)
    if pascal.endswith("ies"):
        return pascal[:-3] + "y"
    if pascal.endswith("sses") or pascal.endswith("xes") or pascal.endswith("ches"):
        return pascal[:-2]
    if pascal.endswith("s") and not pascal.endswith("ss"):
        return pascal[:-1]
    return pascal


# Entities that get a public route in the customer portal (App.tsx) -- and so the only ones a customer page may link to.
# part03 (routes) and part04 (CustomerHome links) each kept their own list; the home page linked to routes that
# were never registered (TS2322 on every <Link to="/projects">).
CUSTOMER_ENTITY_KEYWORDS = ("product", "item", "listing", "service", "book", "course", "event",
                            "article", "post", "property", "menu", "catalog",
                            "class", "schedule", "trainer", "workout", "session", "plan",
                            "member", "booking", "reservation", "room", "team", "player",
                            "match", "fixture", "table", "dish")


def is_customer_entity(table: str) -> bool:
    return any(k in table.lower() for k in CUSTOMER_ENTITY_KEYWORDS)


def to_label(s: str) -> str:
    """'lead_contacts' → 'Lead Contacts'"""
    return " ".join(p.capitalize() for p in re.split(r'[_\-\s]+', s) if p)


def to_singular(label: str) -> str:
    """Very basic English singulariser for display labels."""
    if label.endswith("ies"):
        return label[:-3] + "y"
    if label.endswith("sses") or label.endswith("xes") or label.endswith("ches"):
        return label[:-2]
    if label.endswith("s") and not label.endswith("ss"):
        return label[:-1]
    return label


def slug(s: str) -> str:
    """'LeadContact' → 'lead-contact'"""
    return re.sub(r'([A-Z])', r'-\1', s).lstrip("-").lower()


# ── TypeScript type mapping ────────────────────────────────────────────────────

def col_to_ts_type(col: str) -> str:
    """Map a column name to a TypeScript type string."""
    lower = col.lower()
    if lower == "id" or lower.endswith("_id"):
        return "string | number"
    if "date" in lower or "time" in lower or lower.endswith("_at"):
        return "string"
    if lower == "email" or lower.endswith("_email"):
        return "string"
    if lower in ("price", "amount", "cost", "salary", "rate", "total", "revenue", "value"):
        return "number"
    if lower in ("count", "quantity", "age", "year") or lower.startswith("num_"):
        return "number"
    if (lower.startswith("is_") or lower.startswith("has_") or lower.startswith("can_")
            or lower in ("enabled", "active", "verified", "completed")):
        return "boolean"
    if lower == "rating":
        return "number"
    return "string"


# ── Field def mapping for CrudModal ───────────────────────────────────────────

def col_to_field_def_type(col: str) -> str:
    """Map column name to a CrudModal FieldDef type."""
    lower = col.lower()
    if lower == "email" or lower.endswith("_email"):
        return "email"
    if lower in ("phone", "mobile", "tel") or lower.endswith("_phone") or lower.endswith("_tel"):
        return "tel"
    if ("date" in lower or lower.endswith("_at")) and lower not in ("created_at", "updated_at", "deleted_at"):
        return "date"
    if lower in ("description", "notes", "body", "content", "bio"):
        return "textarea"
    if lower in ("price", "amount", "cost", "count", "qty", "quantity", "rating") or lower.startswith("num_"):
        return "number"
    if lower in ("status", "priority", "stage"):
        return "select"
    return "text"


def col_to_field_options(col: str) -> Optional[List[dict]]:
    """Return options array for select fields, or None."""
    lower = col.lower()
    if lower == "status":
        return [
            {"value": "active", "label": "Active"},
            {"value": "inactive", "label": "Inactive"},
            {"value": "pending", "label": "Pending"},
            {"value": "completed", "label": "Completed"},
            {"value": "cancelled", "label": "Cancelled"},
        ]
    if lower == "priority":
        return [
            {"value": "low", "label": "Low"},
            {"value": "medium", "label": "Medium"},
            {"value": "high", "label": "High"},
            {"value": "critical", "label": "Critical"},
        ]
    if lower == "stage":
        return [
            {"value": "prospecting", "label": "Prospecting"},
            {"value": "qualified", "label": "Qualified"},
            {"value": "proposal", "label": "Proposal"},
            {"value": "negotiation", "label": "Negotiation"},
            {"value": "closed_won", "label": "Closed Won"},
            {"value": "closed_lost", "label": "Closed Lost"},
        ]
    return None


# ── Icon / emoji mapping ───────────────────────────────────────────────────────

def entity_icon(entity_name: str) -> str:
    """Pick a lucide-react icon name for an entity."""
    lower = entity_name.lower().rstrip("s")
    for key, icon in LUCIDE_ICON_MAP.items():
        if key in lower:
            return icon
    return "Database"


def entity_emoji(entity_name: str) -> str:
    """Return a themed emoji for a given entity table name."""
    lower = entity_name.lower()
    for key, emoji in ENTITY_EMOJI_MAP.items():
        if key in lower:
            return emoji
    return "📁"


def resolve_entity_p67_fallback(data: dict, entities: List[dict]) -> List[dict]:
    """P67 fallback: replace generic 'items' entity with entities from pipeline data.

    When entity resolution only produced the generic 'items' placeholder, attempt
    to read entities from data['entities'] or data['architecture']['entities'].
    Returns the original list unchanged if the fallback isn't needed or fails.
    """
    import re as _re
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    if not (len(entities) == 1 and entities[0]["table"] == "items"):
        return entities
    _data_entities = data.get("entities", []) or data.get("architecture", {}).get("entities", [])
    if not _data_entities:
        return entities
    result: List[dict] = []
    for _e in _data_entities:
        _ename = _e.get("name", _e.get("table", "")) if isinstance(_e, dict) else str(_e)
        if not _ename or _ename.lower() in ("user", "users"):
            continue
        _etable = _re.sub(r'([A-Z])', lambda m: '_' + m.group(1).lower(), _ename).lstrip('_').lower()
        _ecols: List[str] = []
        if isinstance(_e, dict):
            for _f in _e.get("fields", _e.get("columns", _e.get("attributes", []))):
                if isinstance(_f, dict):
                    _ecols.append(_f.get("name", _f.get("column", "")))
                elif isinstance(_f, str):
                    _ecols.append(_f)
        result.append({"table": _etable, "name": _ename, "columns": [c for c in _ecols if c] or ["id", "name", "status", "created_at"]})
    if result:
        _logger.info("p05 [P67]: replaced 'items' with %d entities from pipeline data: %s", len(result), [e["table"] for e in result])
        return result
    return entities
