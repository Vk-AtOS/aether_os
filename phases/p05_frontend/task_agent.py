"""P05 Frontend Task Agent — React 18 + Vite 5 + TypeScript + TanStack project generator.

Strategy:
  1. Read architecture.json from p02 to get project name, db_schema, endpoints, route_map.
  2. Generate a complete frontend/ subdirectory with a production-ready React/Vite/TanStack project.
  3. Write docker-compose.yml to the parent project directory.
  4. ONE optional LLM call generates a domain-specific React component (DomainWidget.jsx) and
     injects it into Dashboard.tsx — non-fatal if it fails.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


def _pluralise(word: str) -> str:
    """Basic English pluralisation for FK endpoint derivation."""
    w = word.lower().rstrip("s")  # normalise first
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        return w[:-1] + "ies"
    if w.endswith(("s", "sh", "ch", "x", "z")):
        return w + "es"
    return w + "s"


# ── Domain detection ──────────────────────────────────────────────────────────

def _detect_domain(phase_input: Any) -> str:
    """Detect application domain from project description and entity names."""
    # Only trust the pre-resolved domain if it's a specific domain, not the generic fallbacks.
    # Exclude "ecommerce" from blind trust — it's the LLM's default guess for any app that
    # involves payments/memberships, so re-verify it against keyword scoring below.
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
        or data.get("raw_input")   # pipeline accumulates user prompt here
        or data.get("project_name")
        or ""
    ).lower()
    entities = [e.get("name", "").lower() for e in data.get("entities", [])]
    all_text = description + " " + " ".join(entities)

    # Weighted keyword matching: each keyword has a weight (default 1).
    # Phrases or highly specific terms get higher weights.
    # Final domain = highest total score (ties broken by dict order).
    # Requires at least 2 points to prevent a single generic word from winning.
    domain_keywords: Dict[str, List] = {
        "security":            [("camera", 3), ("cctv", 3), ("surveillance", 3), ("footage", 3),
                                ("nvr", 3), ("dvr", 3), ("ptz", 3), ("facial recognition", 3),
                                ("intrusion", 2), ("motion detection", 2), ("security camera", 3),
                                ("access control", 1), ("guard", 2), ("zone", 1), ("feed", 1)],
        "iot":                 [("sensor", 2), ("telemetry", 3), ("mqtt", 3), ("firmware", 3),
                                ("iot", 3), ("embedded", 2), ("actuator", 2), ("arduino", 3),
                                ("raspberry pi", 3), ("temperature sensor", 3), ("humidity", 2),
                                ("edge computing", 2), ("device", 1)],
        "healthcare":          [("patient", 3), ("appointment", 2), ("doctor", 2), ("clinic", 2),
                                ("medical", 2), ("prescription", 3), ("diagnosis", 3),
                                ("vitals", 3), ("nurse", 2), ("ehr", 3), ("emr", 3), ("health", 1)],
        "crm":                 [("crm", 3), ("lead", 2), ("deal", 2), ("opportunity", 2),
                                ("prospect", 2), ("sales pipeline", 3), ("funnel", 2),
                                ("contact", 1), ("sales", 1)],
        "ecommerce":           [("cart", 3), ("sku", 3), ("ecommerce", 3), ("storefront", 3),
                                ("add to cart", 3), ("shop", 2), ("store", 2), ("order", 2),
                                ("product", 1), ("payment", 1), ("purchase", 1)],
        "library":             [("library", 3), ("isbn", 3), ("librarian", 3), ("borrow", 3),
                                ("overdue", 3), ("book tracking", 3), ("catalog", 2), ("book", 2),
                                ("reading", 2), ("shelf", 2), ("member", 1)],
        "hrm":                 [("employee", 3), ("payroll", 3), ("attendance", 3), ("leave request", 3),
                                ("department", 2), ("salary", 3), ("human resources", 3),
                                ("workforce", 3), ("hrm", 3), ("hr platform", 3),
                                ("onboarding", 2), ("hire", 2), (" hr ", 2), ("hris", 3)],
        "finance":             [("invoice", 3), ("expense", 2), ("budget", 2), ("ledger", 3),
                                ("transaction", 2), ("accounting", 3), ("billing", 2),
                                ("financial", 2), ("payment", 1), ("account", 1)],
        "project_management":  [("sprint", 3), ("kanban", 3), ("backlog", 3), ("milestone", 2),
                                ("ticket", 2), ("board", 2), ("task", 1), ("project", 1)],
        "restaurant":          [("restaurant", 3), ("menu", 2), ("table", 2), ("reservation", 2),
                                ("kitchen", 2), ("waiter", 2), ("dish", 2), ("pos", 2)],
        "education":           [("student", 3), ("enrollment", 3), ("grade", 2), ("teacher", 2),
                                ("course", 2), ("lesson", 2), ("school", 2), ("class", 1)],
        "gym_fitness":         [("gym", 3), ("fitness", 3), ("workout", 3), ("trainer", 2),
                                ("membership", 2), ("exercise", 2), ("class schedule", 3),
                                ("weight", 1), ("cardio", 2), ("strength", 1), ("bench", 1),
                                ("locker", 2), ("personal trainer", 3), ("crossfit", 3),
                                ("yoga", 2), ("pilates", 2), ("sports club", 3)],
        "sports":              [("team", 2), ("match", 2), ("tournament", 3), ("season", 2),
                                ("league", 3), ("player", 2), ("score", 2), ("stadium", 3),
                                ("fixture", 3), ("referee", 2), ("coach", 2), ("sport", 1)],
        "hospitality":         [("hotel", 3), ("room", 2), ("booking", 2), ("checkin", 3),
                                ("checkout", 2), ("guest", 2), ("hostel", 3), ("resort", 3),
                                ("concierge", 3), ("housekeeping", 3), ("amenity", 2)],
        "real_estate":         [("property", 3), ("listing", 2), ("tenant", 3), ("lease", 3),
                                ("landlord", 3), ("rent", 2), ("mortgage", 3), ("agent", 2),
                                ("unit", 1), ("floor plan", 3), ("vacancy", 2)],
    }

    scores: Dict[str, int] = {}
    for domain, weighted_kws in domain_keywords.items():
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


# ── Domain-specific stat-card labels ─────────────────────────────────────────

_DOMAIN_STAT_LABELS: Dict[str, List[str]] = {
    "security":           ["Cameras Online", "Active Alerts", "Zones Monitored", "Incidents Today"],
    "iot":                ["Devices Online", "Active Sensors", "Alerts Today", "Avg Uptime %"],
    "healthcare":         ["Patients Today", "Appointments", "Avg Wait Time", "Staff On Duty"],
    "crm":                ["New Leads", "Open Deals", "Revenue This Month", "Conversion Rate"],
    "ecommerce":          ["Orders Today", "Revenue", "Items in Stock", "Cart Abandonment"],
    "library":            ["Books in Catalog", "Active Members", "Active Checkouts", "Overdue Items"],
    "hrm":                ["Headcount", "On Leave Today", "Open Positions", "Avg Tenure (yrs)"],
    "finance":            ["Invoices Due", "Revenue MTD", "Overdue Payments", "Burn Rate"],
    "project_management": ["Open Tasks", "Sprints Active", "PRs Merged", "Bugs Open"],
    "restaurant":         ["Tables Occupied", "Orders in Queue", "Avg Order Value", "Covers Today"],
    "education":          ["Enrolled Students", "Courses Active", "Avg Grade", "Attendance %"],
    "saas":               ["Active Users", "MRR", "Churn Rate", "NPS Score"],
    "gym_fitness":        ["Active Members", "Classes Today", "Check-ins Today", "Revenue MTD"],
    "sports":             ["Active Players", "Matches Today", "Teams Registered", "Tournaments"],
    "hospitality":        ["Rooms Occupied", "Check-ins Today", "Check-outs Today", "Revenue Today"],
    "real_estate":        ["Active Listings", "Vacant Units", "Leases Expiring", "Revenue MTD"],
}

# ── LLM-powered domain component generation ──────────────────────────────────

_DOMAIN_COMPONENT_DESC: Dict[str, str] = {
    "security": (
        "a CameraGrid showing a 2×3 grid of camera feed placeholders, each with a camera name, "
        "zone badge (e.g. 'Zone A', 'Entrance'), status dot (Online=green, Offline=red, Alert=amber), "
        "and a mock timestamp. Include a top bar showing total cameras online (e.g. 94/100) and "
        "active alerts count with a red badge."
    ),
    "iot": (
        "a DeviceStatusPanel showing a list of 5 mock IoT devices with name, type badge "
        "(Sensor/Gateway/Actuator), last-seen timestamp, and a status pill (Online/Offline/Warning). "
        "Include a summary row at top with total online count and a blinking active indicator."
    ),
    "healthcare": (
        "a PatientVitals card showing mock vitals (Heart Rate: 72 bpm, BP: 120/80, SpO2: 98%) "
        "with coloured status badges and a compact appointment list for today"
    ),
    "crm": (
        "a DealPipeline kanban-style row with 4 columns (New, Contacted, Proposal, Closed) "
        "showing deal count and total value badges per column"
    ),
    "ecommerce": (
        "a ProductGrid showing 4 product cards with image placeholder, name, price, "
        "stock badge (In Stock / Low Stock / Out), and an Add-to-Cart button"
    ),
    "hrm": (
        "an AttendanceTracker showing a 5-day weekly grid for 5 mock employees "
        "with colour-coded cells (Present=green, Absent=red, Leave=yellow)"
    ),
    "finance": (
        "an InvoiceStatus panel showing a row of 3 summary tiles "
        "(Paid, Pending, Overdue) with amounts and a small recent-invoices list"
    ),
    "project_management": (
        "a KanbanBoard with 3 columns (Todo, In Progress, Done) "
        "each containing 2-3 task cards with priority badges and assignee avatars"
    ),
    "restaurant": (
        "a TableMap showing a 3×4 grid of table circles colour-coded by status "
        "(Free=green, Occupied=red, Reserved=yellow) with table numbers"
    ),
    "education": (
        "a GradeDistribution component showing a horizontal bar chart of grade bands "
        "(A/B/C/D/F) with student counts and a pass-rate summary"
    ),
    "saas": (
        "a MetricsDashboard showing 4 KPI tiles (Active Users, MRR, Churn Rate, NPS) "
        "each with a trend arrow (up/down) and a sparkline-style indicator row"
    ),
    "gym_fitness": (
        "a GymDashboard showing today's class schedule (4 classes with time, name, trainer, "
        "and slots-remaining badge), a member check-in counter, and a 7-day attendance sparkline"
    ),
    "sports": (
        "a MatchDayPanel showing today's fixtures (3 matches with home/away team, time, venue) "
        "and a standings mini-table with position, played, won, lost, points columns"
    ),
    "hospitality": (
        "a RoomStatusGrid showing 12 room cards in a 4×3 grid colour-coded by status "
        "(Available=green, Occupied=blue, Cleaning=yellow, Maintenance=red) with room number and type"
    ),
    "real_estate": (
        "a PropertyMap showing 6 listing cards with address, type badge (Apartment/House/Commercial), "
        "price, status pill (Available/Under Offer/Leased), and a thumbnail placeholder"
    ),
    "crm": (
        "a DealPipeline kanban-style row with 4 columns (New, Contacted, Proposal, Closed) "
        "showing deal count and total value badges per column"
    ),
    "restaurant": (
        "a TableMap showing a 3×4 grid of table circles colour-coded by status "
        "(Free=green, Occupied=red, Reserved=yellow) with table numbers"
    ),
}


async def _generate_domain_component(
    domain: str, entities: List[dict], project_name: str, mem_hint: str = ""
) -> Optional[str]:
    """Generate a domain-specific React component via one LLM call.

    Returns JSX source (str) on success, or None when the call fails or the
    response looks invalid. This is always wrapped in a try/except at the call
    site so failures are non-fatal.
    """
    from aether_os.core.llm.client import get_llm_client  # lazy import

    component_desc = _DOMAIN_COMPONENT_DESC.get(domain, _DOMAIN_COMPONENT_DESC["saas"])
    entity_names = [e.get("name", "") or e.get("table", "") for e in entities[:5]] if entities else []

    # Inject golden few-shot examples for this domain
    golden_hint = ""
    try:
        from aether_os.core.learning.golden_retriever import get_golden_examples, format_golden_hint_p05
        _examples = await get_golden_examples(domain, limit=2)
        golden_hint = format_golden_hint_p05(_examples)
    except Exception:
        pass

    prompt = (
        f'Generate a React functional component for a {domain} application called "{project_name}".\n\n'
        f"The component should render: {component_desc}\n\n"
        f"{mem_hint}"
        f"{golden_hint}"
        "Hard requirements:\n"
        "- Tailwind CSS only (dark theme: bg-gray-900, bg-gray-800, text-white, etc.)\n"
        "- Use lucide-react icons (import at top: import {{ ... }} from 'lucide-react')\n"
        "- ALL data is static/mock — zero API calls, zero props, zero useState hooks for fetching\n"
        "- Export: export default function DomainWidget() {{}}\n"
        "- Maximum 120 lines\n"
        "- Visual polish: rounded-2xl, shadows, colour badges, proper spacing\n"
        f"- Entities available in this app (for label inspiration): {', '.join(entity_names)}\n\n"
        "Return ONLY the React component code. No markdown fences, no explanation."
    )

    client = get_llm_client()
    result = await client.call(prompt, task_type="ui_component", max_tokens=2000)
    if (
        result
        and "export default" in result
        and "function" in result
        and "return" in result
        and len(result) > 200
    ):
        # Strip accidental markdown fences
        result = re.sub(r"^```[a-z]*\n?", "", result.strip())
        result = re.sub(r"\n?```$", "", result.strip())
        return result
    return None


# ── Columns to exclude from display and forms ─────────────────────────────────
_EXCLUDED_COLS = frozenset([
    "id", "created_at", "updated_at", "deleted_at",
    "password", "password_hash", "token",
])

# ── Architecture reader ────────────────────────────────────────────────────────

def _read_architecture(data: dict) -> dict:
    """Return architecture dict from any known location, augmented with real API routes."""
    arch: Optional[dict] = None

    arch_path = data.get("p02_architecture_path", "")
    if arch_path:
        try:
            arch = json.loads(Path(arch_path).read_text())
        except Exception:
            pass

    if arch is None:
        project_dir = Path(data.get("project_dir", ""))
        if project_dir.exists():
            for candidate in sorted(project_dir.rglob("architecture.json"))[:3]:
                try:
                    arch = json.loads(candidate.read_text())
                    break
                except Exception:
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
                    path = r["path"]
                    table = path.lstrip("/").split("/")[0]
                    if table and table not in ("health", "docs", "openapi.json", "redoc", "admin"):
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
                    cols_by_table = _extract_columns_from_main_py(data, missing_tables)
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


def _extract_columns_from_main_py(data: dict, tables: List[str]) -> Dict[str, List[str]]:
    """Extract real column names from the generated backend.

    Strategy 1 (preferred): parse SQLAlchemy Column() definitions from models.py —
    the p04a multi-file generator writes ORM models here, not raw SQL.
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
                    # Detect table declaration: __tablename__ = "table_name"
                    tm = re.search(r'__tablename__\s*=\s*["\'](\w+)["\']', line)
                    if tm:
                        if current_table and current_cols:
                            cols_by_table[current_table] = current_cols
                        current_table = tm.group(1).lower()
                        current_cols = []
                        continue
                    # Detect Column definition: col_name = Column(...)
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


def _extract_all_entities_from_models_py(data: dict) -> List[dict]:
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
                # New class definition
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

            # Flush last entity
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

def _normalise_entities(arch: dict) -> List[dict]:
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

    entities = [e for e in entities if e["table"].lower() not in ("users",)]
    if not entities:
        entities = [{"table": "items", "columns": ["id", "name", "description", "status", "created_at"]}]
    return entities


# ── Naming utilities ───────────────────────────────────────────────────────────

def _to_pascal_case(s: str) -> str:
    """Convert snake_case or camelCase string to PascalCase. 'lead_contacts' → 'LeadContacts'."""
    # Handle already-camel strings too
    s = re.sub(r'([a-z])([A-Z])', r'\1_\2', s)
    parts = re.split(r'[_\-\s]+', s)
    return "".join(p.capitalize() for p in parts if p)


def _to_type_name(table: str) -> str:
    """Convert table name to singular PascalCase TypeScript type name.
    'patients' → 'Patient', 'lead_contacts' → 'LeadContact', 'telemetry_entries' → 'TelemetryEntry'
    """
    pascal = _to_pascal_case(table)
    # Singularise the last word component
    if pascal.endswith("ies"):
        return pascal[:-3] + "y"
    if pascal.endswith("sses") or pascal.endswith("xes") or pascal.endswith("ches"):
        return pascal[:-2]
    if pascal.endswith("s") and not pascal.endswith("ss"):
        return pascal[:-1]
    return pascal


def _to_label(s: str) -> str:
    """'lead_contacts' → 'Lead Contacts'"""
    return " ".join(p.capitalize() for p in re.split(r'[_\-\s]+', s) if p)


def _to_singular(label: str) -> str:
    """Very basic English singulariser for display labels."""
    if label.endswith("ies"):
        return label[:-3] + "y"
    if label.endswith("sses") or label.endswith("xes") or label.endswith("ches"):
        return label[:-2]
    if label.endswith("s") and not label.endswith("ss"):
        return label[:-1]
    return label


def _slug(s: str) -> str:
    """'LeadContact' → 'lead-contact'"""
    return re.sub(r'([A-Z])', r'-\1', s).lstrip("-").lower()


# ── TypeScript type mapping ────────────────────────────────────────────────────

def _col_to_ts_type(col: str) -> str:
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

def _col_to_field_def_type(col: str) -> str:
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


def _col_to_field_options(col: str) -> Optional[List[dict]]:
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


# ── Icon mapping ───────────────────────────────────────────────────────────────

_LUCIDE_ICON_MAP: Dict[str, str] = {
    "user": "Users",
    "customer": "Users",
    "client": "Users",
    "contact": "Users",
    "employee": "Users",
    "patient": "Users",
    "student": "GraduationCap",
    "member": "Users",
    "order": "ShoppingCart",
    "cart": "ShoppingCart",
    "purchase": "ShoppingCart",
    "sale": "ShoppingCart",
    "product": "Package",
    "item": "Package",
    "inventory": "Package",
    "stock": "Package",
    "asset": "Package",
    "post": "FileText",
    "article": "FileText",
    "document": "FileText",
    "file": "FileText",
    "report": "FileText",
    "invoice": "FileText",
    "receipt": "FileText",
    "event": "Calendar",
    "booking": "Calendar",
    "appointment": "Calendar",
    "schedule": "Calendar",
    "shift": "Clock",
    "message": "MessageSquare",
    "comment": "MessageSquare",
    "chat": "MessageSquare",
    "ticket": "Ticket",
    "issue": "AlertCircle",
    "alert": "Bell",
    "notification": "Bell",
    "category": "Tag",
    "tag": "Tag",
    "lead": "TrendingUp",
    "deal": "Briefcase",
    "pipeline": "Briefcase",
    "project": "Briefcase",
    "task": "CheckSquare",
    "todo": "CheckSquare",
    "payment": "CreditCard",
    "transaction": "CreditCard",
    "sensor": "Cpu",
    "device": "Cpu",
    "gateway": "Wifi",
    "metric": "BarChart3",
    "log": "Activity",
    "review": "Star",
    "rating": "Star",
    "campaign": "Megaphone",
    "course": "BookOpen",
    "lesson": "BookOpen",
    "grade": "Award",
    "property": "Home",
    "vehicle": "Truck",
    "shipment": "Truck",
    "location": "MapPin",
    "address": "MapPin",
    "setting": "Settings",
    "config": "Settings",
}

# All icons actually used — collected from the map values
_ALL_USED_ICONS = sorted(set(_LUCIDE_ICON_MAP.values()))


def _entity_icon(entity_name: str) -> str:
    """Pick a lucide-react icon name for an entity."""
    lower = entity_name.lower().rstrip("s")
    for key, icon in _LUCIDE_ICON_MAP.items():
        if key in lower:
            return icon
    return "Database"


_ENTITY_EMOJI_MAP: Dict[str, str] = {
    "product": "🛍️", "item": "📦", "categor": "🏷️", "cart": "🛒", "order": "📋",
    "payment": "💳", "review": "⭐", "customer": "👤", "user": "👥", "coupon": "🎟️",
    "shipping": "🚚", "brand": "🏪", "discount": "💸", "wishlist": "❤️",
    "collection": "🗂️", "sku": "🔖", "service": "✨", "package": "📦",
}


def _entity_emoji(entity_name: str) -> str:
    """Return a themed emoji for a given entity table name."""
    lower = entity_name.lower()
    for key, emoji in _ENTITY_EMOJI_MAP.items():
        if key in lower:
            return emoji
    return "📁"


# ── Static file generators ─────────────────────────────────────────────────────

def _generate_package_json(project_slug: str) -> str:
    data = {
        "name": project_slug,
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview",
            "lint": "eslint src --ext .ts,.tsx --report-unused-disable-directives --max-warnings 0",
            "typecheck": "tsc --noEmit",
            "test": "vitest run",
            "test:watch": "vitest",
            "test:coverage": "vitest run --coverage"
        },
        "dependencies": {
            "react": "^18.3.1",
            "react-dom": "^18.3.1",
            "@tanstack/react-query": "^5.62.7",
            "@tanstack/react-router": "^1.58.3",
            "@tanstack/react-table": "^8.20.5",
            "axios": "^1.7.9",
            "lucide-react": "^0.469.0",
            "recharts": "^2.14.1",
            "react-hook-form": "^7.53.0",
            "@hookform/resolvers": "^3.9.0",
            "zod": "^3.23.8"
        },
        "devDependencies": {
            "@types/react": "^18.3.5",
            "@types/react-dom": "^18.3.0",
            "@typescript-eslint/eslint-plugin": "^7.18.0",
            "@typescript-eslint/parser": "^7.18.0",
            "eslint": "^8.57.0",
            "eslint-plugin-react-hooks": "^4.6.2",
            "eslint-plugin-react-refresh": "^0.4.9",
            "@vitejs/plugin-react": "^4.3.4",
            "typescript": "^5.5.3",
            "vite": "^6.0.5",
            "tailwindcss": "^3.4.17",
            "autoprefixer": "^10.4.20",
            "postcss": "^8.4.45",
            "@testing-library/react": "^14.0.0",
            "@testing-library/jest-dom": "^6.0.0",
            "@testing-library/user-event": "^14.0.0",
            "vitest": "^1.0.0",
            "@vitest/coverage-v8": "^1.0.0",
            "jsdom": "^24.0.0"
        }
    }
    return json.dumps(data, indent=2)


def _generate_eslint_config() -> str:
    return """\
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs'],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
  },
}
"""


def _generate_vite_config() -> str:
    return """\
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/app-preview/',
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/app-preview/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\\/app-preview\\/api/, ''),
      },
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\\/api/, ''),
      },
    }
  }
})
"""


def _generate_tsconfig() -> str:
    data = {
        "compilerOptions": {
            "target": "ES2020",
            "useDefineForClassFields": True,
            "lib": ["ES2020", "DOM", "DOM.Iterable"],
            "module": "ESNext",
            "skipLibCheck": True,
            "moduleResolution": "bundler",
            "allowImportingTsExtensions": True,
            "resolveJsonModule": True,
            "isolatedModules": True,
            "noEmit": True,
            "jsx": "react-jsx",
            "strict": True,
            "noUnusedLocals": False,
            "noUnusedParameters": False,
            "noFallthroughCasesInSwitch": True,
            "types": ["vite/client"]
        },
        "include": ["src"],
        "exclude": ["src/__tests__"]
    }
    return json.dumps(data, indent=2)


def _generate_tailwind_config(ui_theme: str = "default") -> str:
    # Theme-appropriate brand palette + dark-mode class
    _neon_palette = """\
        brand: {
          50:  '#e0ffff',
          100: '#b3fffe',
          200: '#80fffd',
          300: '#4dfffc',
          400: '#00ffff',
          500: '#00e5e5',
          600: '#00b3b3',
          700: '#008080',
          800: '#005555',
          900: '#003333',
        },
        surface: {
          50: '#0a0f1e',
          100: '#050810',
          200: '#0d1117',
          300: '#1a2035',
          400: '#242b45',
        },
        accent: {
          pink:   '#ff00ff',
          cyan:   '#00ffff',
          yellow: '#facc15',
        },"""
    _glass_palette = """\
        brand: {
          50:  '#f5f3ff',
          200: '#ddd6fe',
          500: '#8b5cf6',
          600: '#7c3aed',
          700: '#6d28d9',
          900: '#4c1d95',
        },"""
    _default_palette = """\
        brand: {
          50:  '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          900: '#1e3a8a',
        },"""

    _theme_palettes = {
        "neon_cyberpunk": (_neon_palette, "'Share Tech Mono', 'Courier New', monospace"),
        "glassmorphism":  (_glass_palette, None),
        "brutalist":      (_default_palette, "'Courier New', monospace"),
    }
    _palette, _font = _theme_palettes.get(ui_theme, (_default_palette, None))
    _dark = "darkMode: 'class'," if ui_theme in ("neon_cyberpunk", "glassmorphism") else ""
    _font_block = f"""
      fontFamily: {{
        mono: [{_font}],
      }},""" if _font else ""
    return f"""\
export default {{
  content: ['./index.html', './src/**/*.{{js,ts,jsx,tsx}}'],
  {_dark}
  theme: {{
    extend: {{
      colors: {{
{_palette}
      }},{_font_block}
    }}
  }},
  plugins: []
}}
"""


def _generate_postcss_config() -> str:
    return """\
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} }
}
"""


def _generate_index_html(project_name: str, description: str = "", domain: str = "saas") -> str:
    _desc = description or f"{project_name} — the modern platform built for your business."
    _og_type = "website"
    _schema_type = "WebSite"
    if domain in ("ecommerce", "marketplace"):
        _og_type = "website"
        _schema_type = "Store"
    elif domain == "saas":
        _schema_type = "SoftwareApplication"
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="{_desc}" />
  <meta name="robots" content="index, follow" />
  <meta name="theme-color" content="#6366f1" />

  <!-- Open Graph / Social -->
  <meta property="og:type" content="{_og_type}" />
  <meta property="og:title" content="{project_name}" />
  <meta property="og:description" content="{_desc}" />
  <meta property="og:site_name" content="{project_name}" />

  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{project_name}" />
  <meta name="twitter:description" content="{_desc}" />

  <!-- Preconnect for perf -->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://picsum.photos" />

  <!-- Favicon -->
  <link rel="icon" type="image/svg+xml" href="/vite.svg" />

  <title>{project_name}</title>

  <!-- Schema.org structured data -->
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "{_schema_type}",
    "name": "{project_name}",
    "description": "{_desc}",
    "url": "/"
  }}
  </script>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>
"""


def _generate_nginx_conf(config: Optional[dict] = None) -> str:
    # PIPELINE-044: use configurable container name and port instead of hardcoding
    _cfg = config or {}
    container_name = _cfg.get("container_name", "app")
    app_port = _cfg.get("app_port", 8000)
    return f"""\
server {{
  listen 80;
  root /usr/share/nginx/html;
  index index.html;

  gzip on;
  gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
  gzip_min_length 1024;

  # Proxy /api/* to the backend (strips /api prefix)
  # Backend service is named '{container_name}' in docker-compose.yml
  location /api/ {{
    proxy_pass http://{container_name}:{app_port}/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 60s;
    proxy_connect_timeout 10s;
  }}

  # Static assets — long cache
  location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot|map)$ {{
    expires 1y;
    add_header Cache-Control "public, immutable";
    try_files $uri =404;
  }}

  # SPA fallback — React Router handles client-side routes
  location / {{
    try_files $uri $uri/ /index.html;
  }}
}}
"""


def _generate_dockerfile() -> str:
    return """\
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
# Use npm ci if lockfile exists, otherwise npm install (for first-time builds)
RUN [ -f package-lock.json ] && npm ci || npm install
COPY . .
# Accept backend URL as build arg so API calls are baked into the bundle.
# Default is empty — nginx /api/ proxy handles routing on any server.
# Override: docker build --build-arg VITE_API_URL=http://your-server:8000 .
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://localhost:80 || exit 1
"""


def _generate_env_example() -> str:
    return (
        "# Frontend environment variables — copy to .env\n\n"
        "# API base URL. Must be accessible from the user's browser.\n"
        "# Dev: http://localhost:8000  (default, direct to backend)\n"
        "# Docker remote server: http://your-server-ip:8000\n"
        "VITE_API_URL=http://localhost:8000\n"
    )


_THEME_CSS: dict = {
    "glassmorphism": """\
/* Glassmorphism theme */
body { background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%) fixed; min-height: 100vh; }
.glass-card { background: rgba(255,255,255,0.12); backdrop-filter: blur(16px) saturate(180%); -webkit-backdrop-filter: blur(16px) saturate(180%); border: 1px solid rgba(255,255,255,0.25); box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
""",
    "neomorphism": """\
/* Neomorphism theme */
body { background: #e0e5ec; color: #4b5563; }
.neo-card { background: #e0e5ec; border-radius: 12px; box-shadow: 6px 6px 12px #a3b1c6, -6px -6px 12px #ffffff; border: none; }
.neo-inset { box-shadow: inset 4px 4px 8px #a3b1c6, inset -4px -4px 8px #ffffff; }
.neo-btn { background: #e0e5ec; border-radius: 8px; box-shadow: 4px 4px 8px #a3b1c6, -4px -4px 8px #ffffff; border: none; }
.neo-btn:active { box-shadow: inset 2px 2px 5px #a3b1c6, inset -2px -2px 5px #ffffff; }
""",
    "material": """\
/* Material Design 3 theme */
body { background: #fffbfe; color: #1c1b1f; font-family: 'Roboto', 'Google Sans', sans-serif; }
.md-surface { background: #f3edf7; border-radius: 12px; }
.md-surface-variant { background: #e7e0ec; }
.md-primary { background: #6750a4; color: #ffffff; border-radius: 100px; }
.md-secondary { background: #625b71; color: #ffffff; border-radius: 100px; }
.md-elevation-1 { box-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 1px 3px 1px rgba(0,0,0,0.15); }
.md-elevation-2 { box-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 2px 6px 2px rgba(0,0,0,0.15); }
.md-ripple { position: relative; overflow: hidden; }
""",
    "flat": """\
/* Flat / Minimal theme */
body { background: #ffffff; color: #111827; }
* { box-shadow: none !important; }
.flat-card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 0; }
.flat-btn { border-radius: 0; border: 2px solid #111827; background: #111827; color: #ffffff; }
.flat-btn-outline { border-radius: 0; border: 2px solid #111827; background: transparent; color: #111827; }
""",
    "brutalist": """\
/* Brutalist theme */
body { background: #ffffff; color: #000000; font-family: 'Courier New', monospace; }
* { border-radius: 0 !important; }
.brut-card { background: #ffffff; border: 2px solid #000000; box-shadow: 4px 4px 0 #000000; }
.brut-card:hover { box-shadow: 6px 6px 0 #000000; transform: translate(-2px,-2px); }
.brut-btn { background: #000000; color: #ffffff; border: 2px solid #000000; padding: 8px 16px; box-shadow: 3px 3px 0 #f97316; }
.brut-btn:hover { box-shadow: 5px 5px 0 #f97316; transform: translate(-2px,-2px); }
.brut-accent { background: #facc15; color: #000000; }
""",
    "neon_cyberpunk": """\
/* Neon / Cyberpunk theme */
body { background: #050810; color: #e2e8f0; font-family: 'Share Tech Mono', 'Courier New', monospace; }
body::before { content:''; position:fixed; inset:0; background-image: linear-gradient(rgba(0,255,255,0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(0,255,255,0.03) 1px,transparent 1px); background-size: 40px 40px; pointer-events:none; z-index:0; }
.cyber-card { background: rgba(5,8,16,0.85); border: 1px solid #00ffff; box-shadow: 0 0 12px rgba(0,255,255,0.25), inset 0 0 12px rgba(0,255,255,0.05); }
.cyber-card-magenta { border-color: #ff00ff; box-shadow: 0 0 12px rgba(255,0,255,0.25), inset 0 0 12px rgba(255,0,255,0.05); }
.cyber-text-glow { color: #00ffff; text-shadow: 0 0 8px #00ffff; }
.cyber-btn { background: transparent; border: 1px solid #00ffff; color: #00ffff; box-shadow: 0 0 8px rgba(0,255,255,0.4); }
.cyber-btn:hover { background: rgba(0,255,255,0.1); box-shadow: 0 0 16px rgba(0,255,255,0.6); }
""",
    "soft_pastel": """\
/* Soft Pastel theme */
body { background: #fdf4ff; color: #3b1f5e; font-family: 'Nunito', 'Inter', sans-serif; }
.pastel-card { background: #fce7f3; border: 1px solid #fbcfe8; border-radius: 16px; box-shadow: 0 4px 20px rgba(168,85,247,0.08); }
.pastel-card-blue { background: #e0f2fe; border-color: #bae6fd; }
.pastel-card-green { background: #dcfce7; border-color: #bbf7d0; }
.pastel-btn { background: #a855f7; color: #ffffff; border-radius: 50px; box-shadow: 0 4px 12px rgba(168,85,247,0.3); }
.pastel-btn:hover { background: #9333ea; box-shadow: 0 6px 16px rgba(168,85,247,0.4); transform: translateY(-1px); }
""",
}


_SPEED_MS: dict = {
    "instant": 0, "fast": 150, "normal": 300, "slow": 500, "cinematic": 800,
}

_TRANSITION_CSS: dict = {
    "fade":  "transition: opacity {ms}ms ease;",
    "slide": "transition: transform {ms}ms ease, opacity {ms}ms ease;",
    "scale": "transition: transform {ms}ms cubic-bezier(.4,0,.2,1), opacity {ms}ms ease;",
    "flip":  "transition: transform {ms}ms ease; transform-style: preserve-3d;",
    "blur":  "transition: filter {ms}ms ease, opacity {ms}ms ease;",
}

_SKELETON_CSS: dict = {
    "pulse":   ".skeleton { animation: pulse 1.5s cubic-bezier(.4,0,.6,1) infinite; background: rgba(148,163,184,.2); border-radius:4px; } @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}",
    "shimmer": ".skeleton { background: linear-gradient(90deg,rgba(148,163,184,.1) 25%,rgba(148,163,184,.25) 50%,rgba(148,163,184,.1) 75%); background-size:200% 100%; animation:shimmer 1.5s infinite; border-radius:4px; } @keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}",
}


def _generate_index_css(
    ui_theme: str = "default",
    page_transition: str = "fade",
    animation_speed: str = "normal",
    micro_interactions: bool = True,
    scroll_reveal: bool = True,
    loading_style: str = "shimmer",
    hover_lift: bool = True,
) -> str:
    base = """\
@tailwind base;
@tailwind components;
@tailwind utilities;
"""
    parts: list[str] = [base]

    # Theme layer
    theme_extra = _THEME_CSS.get(ui_theme, "")
    if theme_extra:
        parts.append(theme_extra)

    # Animation speed variable
    ms = _SPEED_MS.get(animation_speed, 300)
    parts.append(f":root {{ --anim-speed: {ms}ms; }}")

    # Page transitions
    if page_transition != "none" and ms > 0:
        tpl = _TRANSITION_CSS.get(page_transition, _TRANSITION_CSS["fade"])
        rule = tpl.replace("{ms}", str(ms))
        parts.append(f".page-enter {{ {rule} }}")

    # Loading skeleton
    skel = _SKELETON_CSS.get(loading_style, "")
    if skel:
        parts.append(skel)

    # Hover lift
    if hover_lift:
        parts.append(
            ".hover-lift { transition: transform var(--anim-speed) ease, box-shadow var(--anim-speed) ease; }"
            " .hover-lift:hover { transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,0.18); }"
        )

    # Micro-interactions
    if micro_interactions:
        parts.append(
            ".btn-press:active { transform: scale(0.96); }"
            " .btn-press { transition: transform calc(var(--anim-speed) * 0.5) ease; }"
        )

    # Scroll reveal (CSS-only baseline; JS layer can enhance)
    if scroll_reveal:
        parts.append(
            ".reveal { opacity: 0; transform: translateY(16px); transition: opacity var(--anim-speed) ease, transform var(--anim-speed) ease; }"
            " .reveal.visible { opacity: 1; transform: translateY(0); }"
        )

    return "\n".join(parts)


def _generate_main_tsx() -> str:
    return """\
import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { ToastProvider } from './components/Toaster'
import { ErrorBoundary } from './components/ErrorBoundary'
import { router } from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
    mutations: { retry: 0 },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ErrorBoundary>
          <RouterProvider router={router} />
        </ErrorBoundary>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
"""


def _generate_auth_ts() -> str:
    return """\
export const TOKEN_KEY = 'token'
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)
"""


# ── Dynamic file generators ────────────────────────────────────────────────────

def _generate_types(entities: List[dict]) -> str:
    """Generate src/types/index.ts with one interface per entity."""
    lines: List[str] = ["// Auto-generated by AetherOS p05_frontend", ""]

    for ent in entities:
        table = ent["table"]
        columns = ent["columns"]
        type_name = _to_type_name(table)  # singular: "Patient", "TelemetryEntry"

        lines.append(f"export interface {type_name} {{")
        for col in columns:
            ts_type = _col_to_ts_type(col)
            optional = col.lower() in ("created_at", "updated_at", "deleted_at") or col == "id"
            suffix = "?" if optional else ""
            lines.append(f"  {col}{suffix}: {ts_type}")
        lines.append("}")

        # Create type (omit id, created_at, updated_at, deleted_at)
        omit_fields = [c for c in columns if c.lower() in _EXCLUDED_COLS]
        if omit_fields:
            omit_str = " | ".join(f"'{f}'" for f in omit_fields)
            lines.append(f"export type {type_name}Create = Omit<{type_name}, {omit_str}>")
        else:
            lines.append(f"export type {type_name}Create = {type_name}")
        lines.append("")

    return "\n".join(lines)


def _generate_api(entities: List[dict], route_map: Dict[str, str]) -> str:
    """Generate src/lib/api.ts."""
    lines: List[str] = [
        "// Auto-generated by AetherOS p05_frontend",
        "import axios from 'axios'",
        "import { getToken, clearToken } from './auth'",
        "",
    ]

    # Build entity type imports (use singular type names)
    type_imports = [_to_type_name(e["table"]) for e in entities]
    create_imports = [f"{_to_type_name(e['table'])}Create" for e in entities]
    all_type_imports = type_imports + create_imports
    lines.append(f"import type {{ {', '.join(all_type_imports)} }} from '../types'")
    lines.append("")
    lines.append("// When VITE_API_URL is set: direct calls to backend URL (prod/Docker)")
    lines.append("// When unset: Vite dev proxy rewrites /api/* → backend; nginx does the same in prod")
    lines.append("const BASE = import.meta.env.VITE_API_URL ?? ''")
    lines.append("const API_PREFIX = BASE ? '' : '/api'")
    lines.append("")
    lines.append("export const apiClient = axios.create({ baseURL: BASE + API_PREFIX })")
    lines.append("export const api = apiClient  // alias used by IR-generated components")
    lines.append("")
    lines.append("apiClient.interceptors.request.use(cfg => {")
    lines.append("  const token = getToken()")
    lines.append("  if (token) cfg.headers.Authorization = `Bearer ${token}`")
    lines.append("  return cfg")
    lines.append("})")
    lines.append("")
    lines.append("// Debounce flag — prevents concurrent 401s from triggering multiple redirects")
    lines.append("let _sessionExpired = false")
    lines.append("")
    lines.append("apiClient.interceptors.response.use(")
    lines.append("  r => r,")
    lines.append("  err => {")
    lines.append("    const url = err.config?.url ?? ''")
    lines.append("    const is401 = err.response?.status === 401")
    lines.append("    const isAuthRoute = url.includes('/auth/login') || url.includes('/auth/register')")
    lines.append("    if (is401 && !isAuthRoute && !_sessionExpired) {")
    lines.append("      _sessionExpired = true")
    lines.append("      clearToken()")
    lines.append("      // Use replace (not href=) so the browser back-button still works after re-login")
    lines.append("      setTimeout(() => { _sessionExpired = false; window.location.replace('/login') }, 80)")
    lines.append("    }")
    lines.append("    return Promise.reject(err)")
    lines.append("  },")
    lines.append(")")
    lines.append("")
    lines.append("export const authApi = {")
    lines.append("  login: (email: string, password: string) =>")
    lines.append("    apiClient.post<{ access_token: string }>('/auth/login', { email, password }).then(r => r.data),")
    lines.append("  register: (email: string, password: string) =>")
    lines.append("    apiClient.post('/auth/register', { email, password }).then(r => r.data),")
    lines.append("}")

    for ent in entities:
        table = ent["table"]
        type_name = _to_type_name(table)    # singular: "Patient"
        endpoint = route_map.get(table, f"/{table}")
        # camelCase api object name: e.g. "lead_contacts" → "leadContactsApi"
        camel = table[0].lower() + _to_pascal_case(table)[1:]

        lines.append("")
        lines.append(f"export const {camel}Api = {{")
        lines.append(f"  list: () => apiClient.get<{type_name}[]>('{endpoint}').then(r => r.data),")
        lines.append(f"  create: (data: {type_name}Create) => apiClient.post<{type_name}>('{endpoint}', data).then(r => r.data),")
        lines.append(f"  update: (id: string | number, data: Partial<{type_name}Create>) =>")
        lines.append(f"    apiClient.put<{type_name}>(`{endpoint}/${{id}}`, data).then(r => r.data),")
        lines.append(f"  remove: (id: string | number) => apiClient.delete(`{endpoint}/${{id}}`),")
        lines.append("}")

    return "\n".join(lines) + "\n"


def _generate_app(entities: List[dict], dual_portal: bool = False) -> str:
    """Generate src/App.tsx with TanStack Router.

    When dual_portal=True, generates two route trees:
      - Customer portal at /  (browsing, self-service)
      - Admin portal at /admin (full CRUD management)
    Login page reads JWT role and redirects accordingly.
    """
    if dual_portal:
        return _generate_dual_app(entities)

    entity_imports: List[str] = []
    entity_routes: List[str] = []
    entity_route_children: List[str] = []

    for ent in entities:
        table = ent["table"]
        pascal = ent.get("name") or _to_pascal_case(table)
        route_path = f"/{table.replace('_', '-')}"
        route_var = f"{table}Route"

        entity_imports.append(f"import {pascal}Page from './pages/{pascal}Page'")
        entity_routes.append(
            f"const {route_var} = createRoute({{\n"
            f"  getParentRoute: () => layoutRoute,\n"
            f"  path: '{route_path}',\n"
            f"  component: {pascal}Page,\n"
            f"}})"
        )
        entity_route_children.append(f"    {route_var},")

    imports_str = "\n".join(entity_imports)
    routes_str = "\n\n".join(entity_routes)
    children_str = "\n".join(entity_route_children)

    return f"""\
// Auto-generated by AetherOS p05_frontend
import {{ createRootRoute, createRoute, createRouter, Outlet, redirect }} from '@tanstack/react-router'
import {{ Layout }} from './components/Layout'
import {{ LoginPage }} from './pages/LoginPage'
import Dashboard from './pages/Dashboard'
{imports_str}

const rootRoute = createRootRoute({{ component: () => <Outlet /> }})

const layoutRoute = createRoute({{
  getParentRoute: () => rootRoute,
  id: 'layout',
  component: Layout,
  beforeLoad: () => {{
    if (!localStorage.getItem('token')) throw redirect({{ to: '/login' }})
  }},
}})

const loginRoute = createRoute({{
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
}})

const dashboardRoute = createRoute({{
  getParentRoute: () => layoutRoute,
  path: '/',
  component: Dashboard,
}})

{routes_str}

const routeTree = rootRoute.addChildren([
  loginRoute,
  layoutRoute.addChildren([
    dashboardRoute,
{children_str}
  ]),
])

export const router = createRouter({{ routeTree, basepath: '/app-preview' }})

declare module '@tanstack/react-router' {{
  interface Register {{ router: typeof router }}
}}
"""


def _generate_dual_app(entities: List[dict]) -> str:
    """Generate App.tsx with two portals: /  (customer) and /admin (owner/operator)."""
    entity_imports: List[str] = []
    admin_routes: List[str] = []
    admin_children: List[str] = []
    customer_routes: List[str] = []
    customer_children: List[str] = []

    # Customer-facing entities: product-like browsable items and member-self-service entities
    _customer_kws = ("product", "item", "listing", "service", "book", "course", "event",
                     "article", "post", "property", "menu", "catalog",
                     "class", "schedule", "trainer", "workout", "session", "plan",
                     "member", "booking", "reservation", "room", "team", "player",
                     "match", "fixture", "table", "dish")

    for ent in entities:
        table = ent["table"]
        pascal = ent.get("name") or _to_pascal_case(table)
        route_var = f"{table}Route"
        admin_route_var = f"admin{pascal}Route"

        entity_imports.append(f"import {pascal}Page from './pages/{pascal}Page'")

        # Every entity goes to admin
        admin_routes.append(
            f"const {admin_route_var} = createRoute({{\n"
            f"  getParentRoute: () => adminLayoutRoute,\n"
            f"  path: '/admin/{table.replace('_', '-')}',\n"
            f"  component: {pascal}Page,\n"
            f"}})"
        )
        admin_children.append(f"    {admin_route_var},")

        # Customer-like entities also appear in the customer portal (read-oriented)
        is_customer_entity = any(k in table.lower() for k in _customer_kws)
        if is_customer_entity:
            customer_routes.append(
                f"const {route_var} = createRoute({{\n"
                f"  getParentRoute: () => customerLayoutRoute,\n"
                f"  path: '/{table.replace('_', '-')}',\n"
                f"  component: {pascal}Page,\n"
                f"}})"
            )
            customer_children.append(f"    {route_var},")

    imports_str = "\n".join(entity_imports)
    admin_routes_str = "\n\n".join(admin_routes)
    customer_routes_str = "\n\n".join(customer_routes)
    admin_children_str = "\n".join(admin_children)
    customer_children_str = "\n".join(customer_children)

    return f"""\
// Auto-generated by AetherOS p05_frontend — dual portal (customer + admin)
import {{ createRootRoute, createRoute, createRouter, Outlet, redirect }} from '@tanstack/react-router'
import {{ CustomerLayout }} from './components/CustomerLayout'
import {{ AdminLayout }} from './components/AdminLayout'
import {{ LoginPage }} from './pages/LoginPage'
import CustomerHome from './pages/CustomerHome'
import AdminDashboard from './pages/Dashboard'
{imports_str}

function _getRole(): string | null {{
  try {{
    const t = localStorage.getItem('token')
    if (!t) return null
    return JSON.parse(atob(t.split('.')[1]))?.role ?? 'user'
  }} catch {{ return null }}
}}

const rootRoute = createRootRoute({{ component: () => <Outlet /> }})

// ── Customer portal ───────────────────────────────────────────────────────────
const customerLayoutRoute = createRoute({{
  getParentRoute: () => rootRoute,
  id: 'customer',
  component: CustomerLayout,
  beforeLoad: () => {{
    if (!localStorage.getItem('token')) throw redirect({{ to: '/login' }})
  }},
}})

const customerHomeRoute = createRoute({{
  getParentRoute: () => customerLayoutRoute,
  path: '/',
  component: CustomerHome,
}})

{customer_routes_str}

// ── Admin portal ──────────────────────────────────────────────────────────────
const adminLayoutRoute = createRoute({{
  getParentRoute: () => rootRoute,
  id: 'admin',
  component: AdminLayout,
  beforeLoad: () => {{
    const role = _getRole()
    if (!role) throw redirect({{ to: '/login' }})
    if (role !== 'admin') throw redirect({{ to: '/' }})
  }},
}})

const adminDashboardRoute = createRoute({{
  getParentRoute: () => adminLayoutRoute,
  path: '/admin',
  component: AdminDashboard,
}})

{admin_routes_str}

// ── Auth ──────────────────────────────────────────────────────────────────────
const loginRoute = createRoute({{
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
}})

const routeTree = rootRoute.addChildren([
  loginRoute,
  customerLayoutRoute.addChildren([
    customerHomeRoute,
{customer_children_str}
  ]),
  adminLayoutRoute.addChildren([
    adminDashboardRoute,
{admin_children_str}
  ]),
])

export const router = createRouter({{ routeTree, basepath: '/app-preview' }})

declare module '@tanstack/react-router' {{
  interface Register {{ router: typeof router }}
}}
"""


def _generate_admin_layout(entities: List[dict], project_name: str) -> str:
    """Generate AdminLayout.tsx — dark sidebar for the owner/operator portal."""
    nav_items: List[str] = [f"  {{ to: '/admin' as const, label: 'Dashboard', icon: 'LayoutDashboard' }},"]
    for ent in entities:
        table = ent["table"]
        label = _to_label(table)
        icon = _entity_icon(table)
        nav_items.append(f"  {{ to: '/admin/{table.replace('_', '-')}' as const, label: '{label}', icon: '{icon}' }},")
    nav_str = "\n".join(nav_items)
    icons_needed = sorted({"LayoutDashboard", "LogOut"} | {_entity_icon(e["table"]) for e in entities})
    icons_import = ", ".join(icons_needed)

    return f"""\
// Auto-generated by AetherOS p05_frontend — admin/owner portal layout
import {{ Outlet, Link, useRouter }} from '@tanstack/react-router'
import {{ {icons_import} }} from 'lucide-react'
import {{ clearToken }} from '../lib/auth'

const _ICON_MAP: Record<string, React.FC<any>> = {{ {", ".join(f"'{i}': {i}" for i in icons_needed)} }}

const NAV = [
{nav_str}
]

export function AdminLayout() {{
  const router = useRouter()
  const handleLogout = () => {{ clearToken(); router.navigate({{ to: '/login' }}) }}
  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      <aside className="w-64 bg-gray-900 text-white flex flex-col shrink-0">
        <div className="px-6 py-5 border-b border-gray-700">
          <span className="text-lg font-bold text-white">{project_name}</span>
          <span className="ml-2 text-xs bg-brand-600 text-white px-2 py-0.5 rounded-full font-semibold">Admin</span>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {{NAV.map(item => {{
            const Icon = _ICON_MAP[item.icon]
            return (
              <Link key={{item.to}} to={{item.to}}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-300 hover:bg-gray-800 hover:text-white transition-colors [&.active]:bg-brand-600 [&.active]:text-white text-sm font-medium">
                {{Icon && <Icon size={{16}} />}} {{item.label}}
              </Link>
            )
          }})}}
        </nav>
        <div className="px-3 py-4 border-t border-gray-700 space-y-1">
          <a href="/" className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white text-sm transition-colors">
            <span className="text-xs">🌐</span> Customer View
          </a>
          <button onClick={{handleLogout}}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white text-sm transition-colors">
            <LogOut size={{16}} /> Logout
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}}
"""


def _generate_customer_layout(entities: List[dict], project_name: str) -> str:
    """Generate CustomerLayout.tsx — clean top-nav for the end-user/customer portal."""
    # Customer nav items: only browsable entity pages and member-self-service entities
    _customer_kws = ("product", "item", "listing", "service", "book", "course", "event",
                     "article", "post", "property", "menu", "catalog",
                     "class", "schedule", "trainer", "workout", "session", "plan",
                     "member", "booking", "reservation", "room", "team", "player",
                     "match", "fixture", "table", "dish")
    nav_items: List[str] = [f"  {{ to: '/' as const, label: 'Home' }},"]
    for ent in entities:
        table = ent["table"]
        if any(k in table.lower() for k in _customer_kws):
            label = _to_label(table)
            nav_items.append(f"  {{ to: '/{table.replace('_', '-')}' as const, label: '{label}' }},")
    nav_str = "\n".join(nav_items)

    return f"""\
// Auto-generated by AetherOS p05_frontend — customer-facing portal layout
import {{ Outlet, Link, useRouter }} from '@tanstack/react-router'
import {{ LogOut, User }} from 'lucide-react'
import {{ clearToken, getToken }} from '../lib/auth'

const NAV = [
{nav_str}
]

export function CustomerLayout() {{
  const router = useRouter()
  const handleLogout = () => {{ clearToken(); router.navigate({{ to: '/login' }}) }}
  const isLoggedIn = !!getToken()
  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="sticky top-0 z-40 bg-white border-b border-gray-100 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="text-xl font-extrabold text-gray-900 hover:text-brand-600 transition-colors">
            {project_name}
          </Link>
          <nav className="hidden md:flex items-center gap-1">
            {{NAV.map(item => (
              <Link key={{item.to}} to={{item.to}}
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors [&.active]:text-brand-600 [&.active]:bg-brand-50">
                {{item.label}}
              </Link>
            ))}}
          </nav>
          <div className="flex items-center gap-2">
            {{isLoggedIn ? (
              <button onClick={{handleLogout}}
                className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors">
                <LogOut size={{15}} /> Sign out
              </button>
            ) : (
              <Link to="/login"
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white text-sm font-semibold rounded-lg hover:bg-brand-700 transition-colors">
                <User size={{15}} /> Sign in
              </Link>
            )}}
          </div>
        </div>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
      <footer className="bg-gray-50 border-t border-gray-100 py-8 mt-12">
        <div className="max-w-7xl mx-auto px-4 text-center text-sm text-gray-400">
          © {{new Date().getFullYear()}} {project_name}
        </div>
      </footer>
    </div>
  )
}}
"""


def _generate_customer_home(
    entities: List[dict], route_map: Dict[str, str], project_name: str, domain: str
) -> str:
    """Generate CustomerHome.tsx — public-facing landing page for the customer portal."""
    # Pick the most browsable entity (product-like items)
    _browse_kws = ("product", "item", "listing", "book", "service", "course", "event",
                   "article", "menu", "property", "catalog")
    primary = next(
        (e for e in entities if any(k in e["table"].lower() for k in _browse_kws)),
        entities[0] if entities else {"table": "items", "columns": []}
    )
    primary_table = primary["table"]
    primary_label = _to_label(primary_table)
    primary_endpoint = route_map.get(primary_table, f"/{primary_table}")
    primary_route = f"/{primary_table.replace('_', '-')}"

    # Domain-specific hero copy
    _hero_copy = {
        "ecommerce":   ("Shop the Collection", "Handcrafted products built to last. Free shipping on orders over $50."),
        "marketplace": ("Discover Unique Finds", "Connect with sellers and discover products you'll love."),
        "library":     ("Explore Our Collection", "Browse thousands of books. Reserve online, pick up in-store."),
        "healthcare":  ("Your Health, Your Way", "Book appointments and manage your health records online."),
        "education":   ("Learn Something New", "Explore courses from expert instructors at your own pace."),
        "hospitality": ("Book Your Stay", "Discover beautiful rooms and seamless experiences."),
        "events":      ("Find Your Next Event", "Concerts, workshops, and experiences near you."),
        "food":        ("Order Fresh, Eat Well", "Restaurant-quality meals delivered to your door."),
        "saas":        ("Start Building Today", "Powerful tools to grow your business faster."),
        "gym_fitness": ("Train Smarter, Live Better", "Book classes, track progress, and manage your membership — all in one place."),
        "sports":      ("Play Your Best Game", "Schedules, standings, and stats for your league — all in one place."),
        "hospitality": ("Your Perfect Stay Awaits", "Browse rooms, check availability, and book in seconds."),
        "real_estate": ("Find Your Next Property", "Browse listings, schedule viewings, and manage your lease online."),
        "hrm":         ("Your Workforce, Simplified", "Manage teams, track attendance, and run payroll with ease."),
        "crm":         ("Close More Deals", "Track leads, manage pipelines, and grow your revenue."),
        "restaurant":  ("Great Food, Great Experience", "Reserve a table, browse the menu, and order online."),
    }
    hero_title, hero_sub = _hero_copy.get(domain, (f"Welcome to {project_name}", "Explore what we have to offer."))

    return f"""\
// Auto-generated by AetherOS p05_frontend — customer home
import React from 'react'
import {{ useQuery }} from '@tanstack/react-query'
import {{ Link }} from '@tanstack/react-router'
import {{ apiClient }} from '../lib/api'
import {{ ArrowRight, Star }} from 'lucide-react'

export default function CustomerHome() {{
  const {{ data: raw, isLoading }} = useQuery({{
    queryKey: ['{primary_table}'],
    queryFn: () => apiClient.get('{primary_endpoint}').then(r => r.data),
    staleTime: 60_000,
  }})
  const items: any[] = Array.isArray(raw) ? raw : (raw?.items ?? raw?.data ?? [])
  const featured = items.slice(0, 8)

  return (
    <div className="min-h-screen bg-white">
      {{/* Hero */}}
      <section className="bg-gradient-to-br from-gray-900 via-brand-900 to-brand-700 text-white py-24 md:py-36 relative overflow-hidden">
        <div className="absolute inset-0 opacity-[0.06]"
          style={{{{ backgroundImage: 'repeating-linear-gradient(0deg,transparent,transparent 40px,#fff 40px,#fff 41px),repeating-linear-gradient(90deg,transparent,transparent 40px,#fff 40px,#fff 41px)' }}}} />
        <div className="relative max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-5xl md:text-7xl font-extrabold leading-none tracking-tight mb-6">
            {hero_title}
          </h1>
          <p className="text-lg md:text-xl text-gray-300 mb-10 max-w-2xl mx-auto">{hero_sub}</p>
          <Link to="{primary_route}"
            className="inline-flex items-center gap-2 bg-white text-brand-800 font-bold px-8 py-4 rounded-xl hover:bg-brand-50 transition-all shadow-xl">
            Browse {primary_label} <ArrowRight size={{18}} />
          </Link>
        </div>
        <div className="absolute bottom-0 left-0 right-0">
          <svg viewBox="0 0 1440 40" fill="white" preserveAspectRatio="none" className="w-full h-8">
            <path d="M0,40 C360,0 1080,40 1440,10 L1440,40 Z" />
          </svg>
        </div>
      </section>

      {{/* Featured items */}}
      <section className="py-16 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-end justify-between mb-8">
          <div>
            <h2 className="text-2xl font-extrabold text-gray-900">Featured {primary_label}</h2>
            <p className="text-gray-500 mt-1 text-sm">Handpicked just for you</p>
          </div>
          <Link to="{primary_route}" className="text-sm font-semibold text-brand-600 hover:text-brand-700 flex items-center gap-1">
            View all <ArrowRight size={{14}} />
          </Link>
        </div>
        {{isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {{[...Array(8)].map((_,i) => (
              <div key={{i}} className="rounded-2xl bg-gray-100 h-64 animate-pulse" />
            ))}}
          </div>
        ) : featured.length === 0 ? (
          <div className="text-center py-16 text-gray-400">No items found.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
            {{featured.map((item: any, i: number) => {{
              const seed = item.id ?? i + 1
              const name = item.name ?? item.title ?? item.label ?? `Item ${{item.id}}`
              const price = item.price ?? item.unit_price ?? item.fee ?? null
              return (
                <Link key={{item.id ?? i}} to="{primary_route}"
                  className="group bg-white rounded-2xl border border-gray-100 shadow-sm hover:shadow-xl transition-all hover:-translate-y-1 overflow-hidden flex flex-col">
                  <div className="aspect-square bg-gradient-to-br from-gray-50 to-gray-100 overflow-hidden">
                    <img src={{`https://picsum.photos/seed/${{seed}}/400/400`}} alt={{name}}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                      loading="lazy" onError={{(e) => {{ (e.target as HTMLImageElement).style.display = 'none' }}}} />
                  </div>
                  <div className="p-4 flex flex-col flex-1">
                    <h3 className="font-semibold text-gray-900 text-sm line-clamp-2 mb-2">{{name}}</h3>
                    <div className="flex items-center gap-1 mb-3">
                      {{[1,2,3,4,5].map(s => <Star key={{s}} size={{11}} className="fill-amber-400 text-amber-400" />)}}
                    </div>
                    {{price != null && (
                      <p className="text-lg font-bold text-gray-900 mt-auto">${{typeof price === 'number' ? price.toFixed(2) : price}}</p>
                    )}}
                  </div>
                </Link>
              )
            }})}}
          </div>
        )}}
      </section>
    </div>
  )
}}
"""


def _generate_layout(entities: List[dict], project_name: str, layout_mode: str = "admin") -> str:
    """Generate src/components/Layout.tsx."""
    # Collect icons needed
    icons_needed = {"LayoutDashboard", "LogOut"}
    for ent in entities:
        icons_needed.add(_entity_icon(ent["table"]))
    for ent in entities:
        icons_needed.add(_entity_icon(ent["table"]))

    if layout_mode == "storefront":
        # Premium storefront layout: announcement bar, sticky nav with search + cart badge, rich footer
        nav_items_list: List[str] = []
        for ent in entities:
            table = ent["table"]
            label = _to_label(table)
            route_path = f"/{table.replace('_', '-')}"
            nav_items_list.append(f"  {{ to: '{route_path}' as const, label: '{label}' }},")
        nav_items_str = "\n".join(nav_items_list)

        return f"""\
// Auto-generated by AetherOS p05_frontend — premium storefront layout
import {{ useState }} from 'react'
import {{ Link, useRouter, Outlet }} from '@tanstack/react-router'
import {{ clearToken }} from '../lib/auth'
import {{ ShoppingCart, User, Search, Menu, X, Heart }} from 'lucide-react'
import {{ useQuery }} from '@tanstack/react-query'
import {{ apiClient }} from '../lib/api'

const NAV_ITEMS = [
{nav_items_str}
]

const FOOTER_HELP = ['FAQ', 'Shipping & Returns', 'Track Your Order', 'Size Guide', 'Contact Us']
const FOOTER_COMPANY = ['About Us', 'Blog', 'Careers', 'Press', 'Sustainability']
const PAYMENT_METHODS = ['VISA', 'MC', 'AMEX', 'PayPal', 'Apple Pay']

export function Layout() {{
  const router = useRouter()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)

  const handleLogout = () => {{
    clearToken()
    router.navigate({{ to: '/login' }})
  }}

  const {{ data: cartData }} = useQuery({{
    queryKey: ['__cart_count'],
    queryFn: () => apiClient.get('/carts').then(r => {{
      const d = r.data
      return Array.isArray(d) ? d.length : (d?.items?.length ?? d?.total ?? 0)
    }}).catch(() => 0),
    refetchInterval: 60_000,
    staleTime: 30_000,
  }})
  const cartCount = (cartData as number) || 0

  return (
    <div className="min-h-screen bg-white flex flex-col font-sans">
      {{/* ── Announcement bar ── */}}
      <div className="bg-gray-900 text-white text-center py-2 text-xs font-medium tracking-wide">
        🚚 Free shipping on orders over $50 &nbsp;·&nbsp; Use code{' '}
        <span className="underline font-bold cursor-pointer">WELCOME10</span> for 10% off your first order
      </div>

      {{/* ── Sticky header ── */}}
      <header className="sticky top-0 z-50 bg-white/95 backdrop-blur-sm border-b border-gray-100 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16 gap-4">
            {{/* Logo */}}
            <Link to="/" className="flex-shrink-0 text-xl font-extrabold tracking-tight text-gray-900 hover:text-brand-600 transition-colors">
              {project_name}
            </Link>

            {{/* Center nav — desktop */}}
            <nav className="hidden lg:flex items-center gap-7 flex-1 justify-center">
              {{NAV_ITEMS.map(({{ to, label }}) => (
                <Link key={{to}} to={{to}}
                  className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors relative group
                    [&.active]:text-brand-600 [&.active]:font-semibold">
                  {{label}}
                  <span className="absolute -bottom-1 left-0 h-0.5 w-0 bg-brand-600 transition-all duration-200 group-hover:w-full group-[&.active]:w-full rounded-full" />
                </Link>
              ))}}
            </nav>

            {{/* Right actions */}}
            <div className="flex items-center gap-1">
              <button onClick={{() => setSearchOpen(v => !v)}}
                className="p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Search">
                <Search size={{20}} />
              </button>
              <button className="hidden sm:block p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Wishlist">
                <Heart size={{20}} />
              </button>
              <Link to="/carts" className="relative p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Cart">
                <ShoppingCart size={{20}} />
                {{cartCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 h-5 w-5 flex items-center justify-center rounded-full bg-brand-600 text-[10px] font-bold text-white shadow">
                    {{cartCount > 9 ? '9+' : cartCount}}
                  </span>
                )}}
              </Link>
              <button onClick={{handleLogout}}
                className="hidden sm:flex items-center gap-1.5 ml-1 px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Account">
                <User size={{16}} />
                Account
              </button>
              <button className="lg:hidden p-2 text-gray-500 hover:bg-gray-100 rounded-lg ml-1"
                onClick={{() => setMobileOpen(v => !v)}} aria-label="Menu">
                {{mobileOpen ? <X size={{22}} /> : <Menu size={{22}} />}}
              </button>
            </div>
          </div>
        </div>

        {{/* Search bar */}}
        {{searchOpen && (
          <div className="border-t border-gray-100 px-4 py-3 bg-white animate-in fade-in duration-150">
            <div className="max-w-2xl mx-auto flex items-center gap-3 bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-100 transition-all">
              <Search size={{16}} className="text-gray-400 shrink-0" />
              <input autoFocus placeholder="Search products, categories..."
                className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 focus:outline-none"
                onKeyDown={{e => e.key === 'Escape' && setSearchOpen(false)}} />
              <button onClick={{() => setSearchOpen(false)}} className="text-gray-400 hover:text-gray-600">
                <X size={{16}} />
              </button>
            </div>
          </div>
        )}}

        {{/* Mobile nav */}}
        {{mobileOpen && (
          <div className="lg:hidden border-t border-gray-100 bg-white px-4 pb-4">
            {{NAV_ITEMS.map(({{ to, label }}) => (
              <Link key={{to}} to={{to}} onClick={{() => setMobileOpen(false)}}
                className="block py-3 border-b border-gray-50 text-base font-medium text-gray-700 hover:text-brand-600 transition-colors">
                {{label}}
              </Link>
            ))}}
            <button onClick={{handleLogout}} className="mt-3 flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700">
              <User size={{16}} /> Account / Sign Out
            </button>
          </div>
        )}}
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      {{/* ── Rich footer ── */}}
      <footer className="bg-gray-900 text-gray-400 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-14 pb-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-10 mb-12">
            {{/* Brand column */}}
            <div>
              <span className="text-xl font-extrabold text-white block mb-3">{project_name}</span>
              <p className="text-sm leading-relaxed mb-5">
                Curated quality. Delivered with care. Your go-to destination for authentic craftsmanship and thoughtful design.
              </p>
              <div className="flex gap-2">
                {{['𝕏', 'f', 'in', '▶'].map(s => (
                  <button key={{s}} className="w-9 h-9 rounded-full bg-gray-800 hover:bg-brand-600 flex items-center justify-center text-xs font-bold text-gray-300 hover:text-white transition-all">
                    {{s}}
                  </button>
                ))}}
              </div>
            </div>
            {{/* Shop links */}}
            <div>
              <h4 className="text-white font-semibold text-xs uppercase tracking-widest mb-4">Shop</h4>
              <ul className="space-y-2.5 text-sm">
                {{NAV_ITEMS.slice(0, 6).map(({{ to, label }}) => (
                  <li key={{to}}>
                    <Link to={{to}} className="hover:text-white hover:translate-x-0.5 transition-all inline-block">{{label}}</Link>
                  </li>
                ))}}
              </ul>
            </div>
            {{/* Help links */}}
            <div>
              <h4 className="text-white font-semibold text-xs uppercase tracking-widest mb-4">Help</h4>
              <ul className="space-y-2.5 text-sm">
                {{FOOTER_HELP.map(l => (
                  <li key={{l}}><a href="#" className="hover:text-white transition-colors">{{l}}</a></li>
                ))}}
              </ul>
            </div>
            {{/* Newsletter */}}
            <div>
              <h4 className="text-white font-semibold text-xs uppercase tracking-widest mb-4">Stay in the Loop</h4>
              <p className="text-sm mb-4">New arrivals, exclusive deals, and insider stories. No spam, ever.</p>
              <div className="flex gap-2">
                <input type="email" placeholder="your@email.com"
                  className="flex-1 min-w-0 px-3 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-all" />
                <button className="shrink-0 px-4 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-sm font-semibold transition-colors">
                  Join
                </button>
              </div>
              <p className="text-xs mt-2 text-gray-600">By subscribing you agree to our Privacy Policy.</p>
            </div>
          </div>

          <div className="border-t border-gray-800 pt-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs">
            <p>&copy; {{new Date().getFullYear()}} {project_name}. All rights reserved.</p>
            <div className="flex flex-wrap items-center gap-4">
              {{['Privacy Policy', 'Terms of Service', 'Cookie Settings'].map(l => (
                <a key={{l}} href="#" className="hover:text-white transition-colors">{{l}}</a>
              ))}}
              <div className="flex items-center gap-1.5 ml-2">
                {{PAYMENT_METHODS.map(p => (
                  <span key={{p}} className="bg-gray-800 border border-gray-700 px-2 py-0.5 rounded text-[10px] font-mono text-gray-400">{{p}}</span>
                ))}}
              </div>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}}
"""

    # Default admin sidebar layout
    icons_str = ", ".join(sorted(icons_needed))
    nav_items_admin: List[str] = [
        "  { to: '/' as const, label: 'Dashboard', Icon: LayoutDashboard },",
    ]
    for ent in entities:
        table = ent["table"]
        label = _to_label(table)
        icon = _entity_icon(table)
        route_path = f"/{table.replace('_', '-')}"
        nav_items_admin.append(f"  {{ to: '{route_path}' as const, label: '{label}', Icon: {icon} }},")

    nav_items_str = "\n".join(nav_items_admin)

    return f"""\
// Auto-generated by AetherOS p05_frontend
import {{ Link, useRouter, Outlet }} from '@tanstack/react-router'
import {{ clearToken }} from '../lib/auth'
import {{ {icons_str} }} from 'lucide-react'

const NAV_ITEMS = [
{nav_items_str}
]

export function Layout() {{
  const router = useRouter()
  const handleLogout = () => {{
    clearToken()
    router.navigate({{ to: '/login' }})
  }}

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-64 bg-gray-900 text-white flex flex-col">
        <div className="p-6 border-b border-gray-700">
          <h1 className="text-xl font-bold text-white">{project_name}</h1>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {{NAV_ITEMS.map(({{ to, label, Icon }}) => (
            <Link
              key={{to}}
              to={{to}}
              className="flex items-center gap-3 px-4 py-2.5 rounded-lg text-gray-300 hover:bg-gray-800 hover:text-white transition-colors [&.active]:bg-brand-600 [&.active]:text-white"
            >
              <Icon size={{18}} />
              {{label}}
            </Link>
          ))}}
        </nav>
        <button
          onClick={{handleLogout}}
          className="flex items-center gap-3 px-8 py-4 text-gray-400 hover:text-white border-t border-gray-700"
        >
          <LogOut size={{18}} />
          Logout
        </button>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}}
"""


def _generate_data_table() -> str:
    return """\
// Auto-generated by AetherOS p05_frontend
import { useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ChevronUp, ChevronDown } from 'lucide-react'

interface Props<T> {
  data: T[]
  columns: ColumnDef<T>[]
  isLoading?: boolean
}

export function DataTable<T>({ data, columns, isLoading }: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [globalFilter, setGlobalFilter] = useState('')

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-600" />
      </div>
    )
  }

  return (
    <div>
      <input
        value={globalFilter}
        onChange={e => setGlobalFilter(e.target.value)}
        placeholder="Search..."
        className="mb-4 w-full max-w-sm px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
      />
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map(header => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className="px-4 py-3 text-left font-medium text-gray-600 cursor-pointer hover:text-gray-900 select-none"
                  >
                    <div className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === 'asc' ? (
                        <ChevronUp size={14} />
                      ) : header.column.getIsSorted() === 'desc' ? (
                        <ChevronDown size={14} />
                      ) : null}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map(row => (
              <tr key={row.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} className="px-4 py-3 text-gray-700">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {table.getRowModel().rows.length === 0 && (
          <div className="text-center py-12 text-gray-400">No records found</div>
        )}
      </div>
      <p className="mt-2 text-xs text-gray-400">
        {table.getFilteredRowModel().rows.length} records
      </p>
    </div>
  )
}
"""


def _generate_crud_modal() -> str:
    return """\
// Auto-generated by AetherOS p05_frontend
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { X } from 'lucide-react'
import { apiClient } from '../lib/api'

export interface FieldDef {
  name: string
  label: string
  type: 'text' | 'email' | 'tel' | 'date' | 'number' | 'textarea' | 'select' | 'fk-select'
  required?: boolean
  options?: { value: string; label: string }[]
  /** For fk-select: the related entity endpoint path, e.g. "/categories" */
  fkEndpoint?: string
  /** For fk-select: key to use as option label from fetched records */
  fkLabelKey?: string
}

interface Props<T extends Record<string, unknown>> {
  isOpen: boolean
  onClose: () => void
  onSubmit: (data: T) => void
  initialValues?: Partial<T>
  fields: FieldDef[]
  title: string
  isLoading?: boolean
  /** fkConfig: maps field name → entity endpoint path for auto-populated FK dropdowns */
  fkConfig?: Record<string, string>
}

export function CrudModal<T extends Record<string, unknown>>({
  isOpen,
  onClose,
  onSubmit,
  initialValues,
  fields,
  title,
  isLoading,
  fkConfig,
}: Props<T>) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<T>()

  const [fkOptions, setFkOptions] = useState<Record<string, { value: string; label: string }[]>>({})

  useEffect(() => {
    if (isOpen) reset((initialValues ?? {}) as T)
  }, [isOpen, initialValues, reset])

  // Fetch FK options when the modal opens
  useEffect(() => {
    if (!isOpen) return
    const fkFields = fields.filter(f => f.type === 'fk-select' || (f.name.endsWith('_id') && fkConfig?.[f.name]))
    fkFields.forEach(field => {
      const endpoint = field.fkEndpoint ?? fkConfig?.[field.name]
      if (!endpoint) return
      const labelKey = field.fkLabelKey ?? 'name'
      apiClient.get<{ items?: unknown[]; [k: string]: unknown }>(endpoint)
        .then(res => {
          const records: unknown[] = (res.data as any)?.items ?? (Array.isArray(res.data) ? res.data : [])
          const opts = records.map((r: any) => ({
            value: String(r.id ?? r._id ?? ''),
            label: String(r[labelKey] ?? r.name ?? r.title ?? r.email ?? r.id ?? ''),
          }))
          setFkOptions(prev => ({ ...prev, [field.name]: opts }))
        })
        .catch(() => {})
    })
  }, [isOpen, fields, fkConfig])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-6 border-b">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={20} />
          </button>
        </div>
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex-1 overflow-y-auto p-6 space-y-4"
        >
          {fields.map(f => {
            // Determine if this is a FK select field
            const isFkSelect = f.type === 'fk-select' || (f.name.endsWith('_id') && !!(fkConfig?.[f.name] || f.fkEndpoint))
            const resolvedOptions = isFkSelect ? (fkOptions[f.name] ?? []) : (f.options ?? [])
            return (
              <div key={f.name}>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {f.label}
                  {f.required && <span className="text-red-500 ml-1">*</span>}
                </label>
                {f.type === 'textarea' ? (
                  <textarea
                    {...register(f.name as keyof T extends string ? keyof T : never, {
                      required: f.required,
                    } as any)}
                    className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-brand-500"
                    rows={3}
                  />
                ) : f.type === 'select' || isFkSelect ? (
                  <select
                    {...register(f.name as any, { required: f.required })}
                    className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-brand-500"
                  >
                    <option value="">
                      {isFkSelect && resolvedOptions.length === 0 ? 'Loading...' : 'Select...'}
                    </option>
                    {resolvedOptions.map(o => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={f.type}
                    {...register(f.name as any, { required: f.required })}
                    className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-brand-500"
                  />
                )}
                {errors[f.name as keyof T] && (
                  <p className="text-xs text-red-500 mt-1">Required</p>
                )}
              </div>
            )
          })}
          <div className="flex justify-end gap-3 pt-4 border-t">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
            >
              {isLoading ? 'Saving...' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
"""


def _generate_toaster() -> str:
    return """\
// Auto-generated by AetherOS p05_frontend
// Simple toast notification component using state
import { useState, useCallback, createContext, useContext } from 'react'
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'

interface Toast {
  id: string
  message: string
  type: 'success' | 'error' | 'info'
}

interface ToastContextValue {
  toast: (message: string, type?: Toast['type']) => void
}

const ToastContext = createContext<ToastContextValue>({ toast: () => undefined })

export function useToast() {
  return useContext(ToastContext)
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const toast = useCallback((message: string, type: Toast['type'] = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3500)
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-sm text-white min-w-[260px] ${
              t.type === 'success' ? 'bg-green-600'
              : t.type === 'error' ? 'bg-red-600'
              : 'bg-gray-800'
            }`}
          >
            {t.type === 'success' ? <CheckCircle size={16} />
              : t.type === 'error' ? <AlertCircle size={16} />
              : <Info size={16} />}
            <span className="flex-1">{t.message}</span>
            <button
              onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}
              className="text-white/70 hover:text-white"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
"""


def _generate_vitest_config() -> str:
    return """\
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
    },
  },
})
"""


def _generate_test_setup() -> str:
    return """\
import '@testing-library/jest-dom'
"""


def _generate_login_test(project_name: str) -> str:
    return f"""\
import {{ render, screen }} from '@testing-library/react'
import {{ describe, it, expect }} from 'vitest'
import {{ LoginPage }} from '../pages/LoginPage'

describe('LoginPage', () => {{
  it('renders login form', () => {{
    render(<LoginPage />)
    expect(screen.getByRole('button', {{ name: /sign in|log in|login/i }})).toBeInTheDocument()
  }})

  it('shows email and password fields', () => {{
    render(<LoginPage />)
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument()
  }})
}})
"""


def _generate_dashboard_test() -> str:
    return """\
import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Mock the api module to match apiClient export
vi.mock('../lib/api', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}))

describe('Dashboard', () => {
  it('renders without crashing', async () => {
    const { default: Dashboard } = await import('../pages/Dashboard')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={qc}><Dashboard /></QueryClientProvider>
    )
    expect(container).toBeTruthy()
  })
})
"""


def _generate_error_boundary() -> str:
    return """\
import React, { Component, ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { hasError: boolean; error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="text-center p-8 max-w-md">
            <div className="text-6xl mb-4">⚠️</div>
            <h1 className="text-2xl font-bold text-gray-900 mb-2">Something went wrong</h1>
            <p className="text-gray-500 mb-6">{this.state.error?.message ?? 'An unexpected error occurred.'}</p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              Try again
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
"""


def _generate_not_found_page() -> str:
    return """\
import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center p-8 max-w-md">
        <div className="text-8xl font-black text-gray-200 mb-4">404</div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Page not found</h1>
        <p className="text-gray-500 mb-6">The page you're looking for doesn't exist or has been moved.</p>
        <Link
          to="/"
          className="inline-block px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          Back to home
        </Link>
      </div>
    </div>
  )
}

export default NotFoundPage
"""


def _generate_frontend_readme(project_name: str) -> str:
    return f"""\
# {project_name} Frontend

Auto-generated React 18 + Vite 5 + TypeScript frontend by AetherOS.

## Quick Start

```bash
cp .env.example .env
npm install
npm run dev
```

Runs on http://localhost:3000

## Stack

- React 18 + TypeScript
- Vite 5 (bundler)
- TanStack Router (routing)
- TanStack Query (data fetching)
- Tailwind CSS (styling)
- shadcn/ui components

## Scripts

| Command | Description |
|---|---|
| npm run dev | Dev server with HMR |
| npm run build | Production build |
| npm run test | Run Vitest tests |
| npm run test:coverage | Coverage report |
| npm run lint | ESLint |

## Environment Variables

Copy `.env.example` to `.env` and set:
- `VITE_API_URL` — backend API base URL
"""


def _generate_login_page(project_name: str, layout_mode: str = "admin") -> str:
    if layout_mode == "dual":
        return f"""\
// Auto-generated by AetherOS p05_frontend — dual portal login
import {{ useState }} from 'react'
import {{ useNavigate }} from '@tanstack/react-router'
import {{ authApi }} from '../lib/api'
import {{ setToken }} from '../lib/auth'

function _getRole(token: string): string {{
  try {{ return JSON.parse(atob(token.split('.')[1]))?.role ?? 'user' }}
  catch {{ return 'user' }}
}}

export function LoginPage() {{
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {{
    e.preventDefault()
    setLoading(true)
    setError('')
    try {{
      const {{ access_token }} = await authApi.login(email, password)
      setToken(access_token)
      const role = _getRole(access_token)
      // Route admins to the management portal, everyone else to the customer portal
      navigate({{ to: role === 'admin' ? '/admin' : '/' }})
    }} catch {{
      setError('Invalid email or password')
    }} finally {{
      setLoading(false)
    }}
  }}

  return (
    <div className="min-h-screen flex">
      {{/* Hero / branding panel — hidden on mobile */}}
      <div className="hidden lg:flex lg:w-1/2 bg-brand-600 flex-col items-center justify-center p-12 text-white">
        <div className="max-w-md text-center space-y-6">
          <h1 className="text-4xl font-extrabold">{project_name}</h1>
          <p className="text-brand-100 text-lg">
            Sign in to access your account and everything {project_name} has to offer.
          </p>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="bg-brand-700/50 rounded-xl p-4">
              <p className="font-bold text-white text-base mb-1">Members</p>
              <p className="text-brand-200">Book, manage and track — all in one place.</p>
            </div>
            <div className="bg-brand-700/50 rounded-xl p-4">
              <p className="font-bold text-white text-base mb-1">Admins</p>
              <p className="text-brand-200">Full management portal with analytics.</p>
            </div>
          </div>
        </div>
      </div>
      {{/* Login form panel */}}
      <div className="flex-1 flex items-center justify-center bg-gray-50 p-8">
        <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-md">
          <div className="lg:hidden mb-6 text-center">
            <h1 className="text-2xl font-bold text-brand-600">{project_name}</h1>
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-1">Welcome back</h2>
          <p className="text-gray-500 mb-8 text-sm">Sign in to your account to continue.</p>
          <form onSubmit={{handleSubmit}} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email address</label>
              <input type="email" value={{email}} onChange={{e => setEmail(e.target.value)}} required
                placeholder="you@example.com"
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
              <input type="password" value={{password}} onChange={{e => setPassword(e.target.value)}} required
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 text-sm" />
            </div>
            {{error && <p className="text-sm text-red-500 bg-red-50 px-3 py-2 rounded-lg">{{error}}</p>}}
            <button type="submit" disabled={{loading}}
              className="w-full py-3 bg-brand-600 text-white rounded-xl hover:bg-brand-700 disabled:opacity-50 font-semibold text-sm transition-colors">
              {{loading ? 'Signing in…' : 'Sign in'}}
            </button>
          </form>
          <div className="mt-6 p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm space-y-1">
            <p className="font-semibold text-amber-800">Demo credentials</p>
            <p className="text-amber-700">Admin: <span className="font-mono">admin@example.com</span> / <span className="font-mono">Admin1234!</span></p>
            <p className="text-amber-700">User: <span className="font-mono">user@example.com</span> / <span className="font-mono">User1234!</span></p>
          </div>
        </div>
      </div>
    </div>
  )
}}
"""

    if layout_mode == "storefront":
        return f"""\
// Auto-generated by AetherOS p05_frontend (storefront login)
import {{ useState }} from 'react'
import {{ useNavigate }} from '@tanstack/react-router'
import {{ authApi }} from '../lib/api'
import {{ setToken }} from '../lib/auth'

export function LoginPage() {{
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {{
    e.preventDefault()
    setLoading(true)
    setError('')
    try {{
      const {{ access_token }} = await authApi.login(email, password)
      setToken(access_token)
      navigate({{ to: '/' }})
    }} catch {{
      setError('Invalid email or password')
    }} finally {{
      setLoading(false)
    }}
  }}

  return (
    <div className="min-h-screen bg-gradient-to-br from-brand-50 to-brand-100 flex">
      {{/* Branding / Hero panel */}}
      <div className="hidden lg:flex lg:w-1/2 bg-brand-600 flex-col items-center justify-center p-12 text-white">
        <div className="max-w-md text-center">
          <h1 className="text-4xl font-extrabold mb-4">{project_name}</h1>
          <p className="text-brand-100 text-lg mb-8">
            Welcome back! Sign in to access your account and continue shopping.
          </p>
          <div className="grid grid-cols-2 gap-4 text-sm text-brand-200">
            <div className="bg-brand-700/50 rounded-lg p-4">
              <p className="font-semibold text-white text-lg">Free shipping</p>
              <p>On orders over $50</p>
            </div>
            <div className="bg-brand-700/50 rounded-lg p-4">
              <p className="font-semibold text-white text-lg">Easy returns</p>
              <p>30-day return policy</p>
            </div>
          </div>
        </div>
      </div>
      {{/* Login form panel */}}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-md">
          <div className="lg:hidden mb-6 text-center">
            <h1 className="text-2xl font-bold text-brand-600">{project_name}</h1>
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-1">Sign in</h2>
          <p className="text-gray-500 mb-8">Welcome back — we missed you!</p>
          <form onSubmit={{handleSubmit}} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email address</label>
              <input
                type="email"
                value={{email}}
                onChange={{e => setEmail(e.target.value)}}
                required
                placeholder="you@example.com"
                className="w-full px-3 py-2.5 border rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
              <input
                type="password"
                value={{password}}
                onChange={{e => setPassword(e.target.value)}}
                required
                className="w-full px-3 py-2.5 border rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
              />
            </div>
            {{error && <p className="text-sm text-red-500">{{error}}</p>}}
            <button
              type="submit"
              disabled={{loading}}
              className="w-full py-3 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-semibold text-base transition-colors"
            >
              {{loading ? 'Signing in...' : 'Sign in to your account'}}
            </button>
          </form>
          <p className="mt-6 text-center text-sm text-gray-500">
            Don't have an account?{{' '}}
            <a href="#" className="text-brand-600 font-medium hover:underline">Create one free</a>
          </p>
          <div className="mt-6 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm">
            <p className="font-medium text-amber-800 mb-1">Demo credentials</p>
            <p className="text-amber-700">Email: <span className="font-mono">admin@example.com</span></p>
            <p className="text-amber-700">Password: <span className="font-mono">Admin1234!</span></p>
          </div>
        </div>
      </div>
    </div>
  )
}}
"""

    # Default admin login page
    return f"""\
// Auto-generated by AetherOS p05_frontend
import {{ useState }} from 'react'
import {{ useNavigate }} from '@tanstack/react-router'
import {{ authApi }} from '../lib/api'
import {{ setToken }} from '../lib/auth'

export function LoginPage() {{
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {{
    e.preventDefault()
    setLoading(true)
    setError('')
    try {{
      const {{ access_token }} = await authApi.login(email, password)
      setToken(access_token)
      navigate({{ to: '/' }})
    }} catch {{
      setError('Invalid email or password')
    }} finally {{
      setLoading(false)
    }}
  }}

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-brand-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-brand-600 rounded-xl mb-4">
            <span className="text-white font-extrabold text-xl">{project_name[0] if project_name else 'A'}</span>
          </div>
          <h1 className="text-2xl font-extrabold text-gray-900">{project_name}</h1>
          <p className="text-gray-500 mt-1 text-sm">Sign in to your admin account</p>
        </div>
        <form onSubmit={{handleSubmit}} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email address</label>
            <input
              type="email"
              value={{email}}
              onChange={{e => setEmail(e.target.value)}}
              required
              placeholder="admin@example.com"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={{password}}
              onChange={{e => setPassword(e.target.value)}}
              required
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 text-sm"
            />
          </div>
          {{error && <p className="text-sm text-red-500 bg-red-50 px-3 py-2 rounded-lg">{{error}}</p>}}
          <button
            type="submit"
            disabled={{loading}}
            className="w-full py-3 bg-brand-600 text-white rounded-xl hover:bg-brand-700 disabled:opacity-50 font-semibold text-sm transition-colors"
          >
            {{loading ? 'Signing in…' : 'Sign in'}}
          </button>
        </form>
        <div className="mt-6 p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm space-y-1">
          <p className="font-semibold text-amber-800">Demo credentials</p>
          <p className="text-amber-700">Email: <span className="font-mono">admin@example.com</span></p>
          <p className="text-amber-700">Password: <span className="font-mono">Admin1234!</span></p>
        </div>
      </div>
    </div>
  )
}}
"""


def _generate_dashboard(entities: List[dict], route_map: Dict[str, str], domain: str = "saas") -> str:
    """Generate src/pages/Dashboard.tsx — storefront homepage for ecommerce, stat cards for others."""
    if domain in ("ecommerce", "marketplace"):
        return _generate_storefront_home(entities, route_map)

    query_lines: List[str] = []
    stat_cards: List[str] = []

    icons = ["BarChart3", "Users", "Activity", "TrendingUp", "Package", "FileText", "Calendar", "Database"]
    domain_labels = _DOMAIN_STAT_LABELS.get(domain, _DOMAIN_STAT_LABELS["saas"])

    for i, ent in enumerate(entities):
        table = ent["table"]
        camel = table[0].lower() + _to_pascal_case(table)[1:]
        endpoint = route_map.get(table, f"/{table}")
        label = domain_labels[i] if i < len(domain_labels) else _to_label(table)
        icon = icons[i % len(icons)]

        query_lines.append(
            f"  const {{ data: {camel}Data }} = useQuery({{\n"
            f"    queryKey: ['{table}'],\n"
            f"    queryFn: () => apiClient.get<unknown[]>('{endpoint}').then(r => r.data),\n"
            f"  }})"
        )
        stat_cards.append(
            f"        <div className=\"bg-white rounded-2xl border border-gray-100 p-6 shadow-sm hover:shadow-md transition-shadow\">\n"
            f"          <div className=\"flex items-center justify-between mb-3\">\n"
            f"            <p className=\"text-sm font-semibold text-gray-500 uppercase tracking-wide\">{label}</p>\n"
            f"            <div className=\"p-2 bg-brand-50 rounded-lg\">\n"
            f"              <{icon} size={{18}} className=\"text-brand-600\" />\n"
            f"            </div>\n"
            f"          </div>\n"
            f"          <p className=\"text-4xl font-bold text-gray-900\">{{{camel}Data?.length ?? '—'}}</p>\n"
            f"          <p className=\"text-xs text-gray-400 mt-2\">Total {label.lower()}</p>\n"
            f"        </div>"
        )

    queries_str = "\n".join(query_lines)
    cards_str = "\n".join(stat_cards)
    used_icons = sorted(set(icons[i % len(icons)] for i in range(len(entities))))
    icons_import = ", ".join(used_icons) if used_icons else "BarChart3"

    return f"""\
// Auto-generated by AetherOS p05_frontend  (domain: {domain})
import {{ useQuery }} from '@tanstack/react-query'
import {{ {icons_import} }} from 'lucide-react'
import {{ apiClient }} from '../lib/api'

export function Dashboard() {{
{queries_str}

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 mt-1">Welcome back. Here's what's happening today.</p>
      </div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
{cards_str}
      </div>
      {{/* DOMAIN_WIDGET_SLOT */}}
    </div>
  )
}}
"""


def _generate_storefront_home(entities: List[dict], route_map: Dict[str, str]) -> str:
    """Generate a full storefront homepage: hero, trust badges, live product grid."""
    # Pick the most product-like entity as the primary showcase
    _product_keywords = ("product", "item", "goods", "service", "listing", "sku", "artifact", "piece")
    primary_entity = next(
        (e for e in entities if any(k in e["table"].lower() for k in _product_keywords)),
        entities[0] if entities else {"table": "products", "columns": []}
    )
    primary_table = primary_entity["table"]
    primary_endpoint = route_map.get(primary_table, f"/{primary_table}")
    primary_route = f"/{primary_table.replace('_', '-')}"

    # Build category nav from other entities (avoid backslash in f-string expressions)
    other_entities = [e for e in entities if e["table"] != primary_table][:5]
    _cat_parts: List[str] = []
    for _ce in other_entities:
        _ct = _ce["table"]
        _cl = _to_label(_ct)
        _ce_emoji = _entity_emoji(_ct)
        _cat_parts.append(
            f"            <a href='#{_ct}' className=\"group flex flex-col items-center gap-3 p-4 rounded-2xl bg-gray-50 hover:bg-brand-50 border border-transparent hover:border-brand-200 transition-all\">\n"
            f"              <div className=\"text-2xl\">{_ce_emoji}</div>\n"
            f"              <span className=\"text-xs font-semibold text-gray-700 group-hover:text-brand-700 text-center\">{_cl}</span>\n"
            f"            </a>"
        )
    category_links = "\n".join(_cat_parts)

    return f"""\
// Auto-generated by AetherOS p05_frontend — storefront homepage
import {{ useQuery }} from '@tanstack/react-query'
import {{ Link }} from '@tanstack/react-router'
import {{ apiClient }} from '../lib/api'
import {{ ArrowRight, Star, ShoppingCart, CheckCircle }} from 'lucide-react'

const TRUST_BADGES = [
  {{ emoji: '🚚', title: 'Free Shipping', sub: 'On orders over $50' }},
  {{ emoji: '🔒', title: 'Secure Payment', sub: '256-bit SSL encryption' }},
  {{ emoji: '🔄', title: 'Easy Returns', sub: '30-day return policy' }},
  {{ emoji: '💬', title: '24/7 Support', sub: 'Always here to help' }},
]

function StarRating({{ rating = 4.5 }}: {{ rating?: number }}) {{
  return (
    <div className="flex items-center gap-0.5">
      {{[1,2,3,4,5].map(s => (
        <Star key={{s}} size={{12}}
          className={{s <= Math.round(rating) ? 'fill-amber-400 text-amber-400' : 'text-gray-200'}} />
      ))}}
    </div>
  )
}}

function ProductCard({{ product, index }}: {{ product: any; index: number }}) {{
  const seed = product.id ?? index + 1
  const rawPrice = product.price ?? product.unit_price ?? product.amount ?? 0
  const price = typeof rawPrice === 'number' ? rawPrice : parseFloat(rawPrice) || 0
  const category = product.category ?? product.type ?? product.collection ?? 'Collection'
  const rating = typeof product.rating === 'number' ? product.rating : 4.2 + (seed % 10) * 0.08

  return (
    <div className="group relative bg-white rounded-2xl overflow-hidden border border-gray-100 shadow-sm hover:shadow-2xl transition-all duration-300 hover:-translate-y-1 flex flex-col">
      {{/* Image */}}
      <div className="relative aspect-square bg-gradient-to-br from-gray-50 to-gray-100 overflow-hidden">
        <img
          src={{`https://picsum.photos/seed/${{seed}}/400/400`}}
          alt={{product.name ?? 'Product'}}
          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
          loading="lazy"
          onError={{(e) => {{ (e.target as HTMLImageElement).style.display = 'none' }}}}
        />
        {{product.is_featured && (
          <span className="absolute top-3 left-3 bg-brand-600 text-white text-[10px] font-bold px-2.5 py-1 rounded-full uppercase tracking-wider">
            Featured
          </span>
        )}}
        {{product.stock_quantity === 0 && (
          <div className="absolute inset-0 bg-white/60 flex items-center justify-center">
            <span className="text-sm font-semibold text-gray-600">Out of Stock</span>
          </div>
        )}}
      </div>
      {{/* Content */}}
      <div className="p-4 flex flex-col flex-1">
        <p className="text-[11px] font-bold text-brand-600 uppercase tracking-wider mb-1">{{category}}</p>
        <h3 className="font-semibold text-gray-900 text-sm leading-snug mb-2 line-clamp-2 flex-1">
          {{product.name ?? product.title ?? 'Product'}}
        </h3>
        <div className="flex items-center gap-2 mb-3">
          <StarRating rating={{rating}} />
          <span className="text-[11px] text-gray-400">
            ({{product.review_count ?? Math.floor(10 + (seed * 7) % 190)}})
          </span>
        </div>
        <div className="flex items-center justify-between mt-auto">
          <div>
            <span className="text-lg font-bold text-gray-900">${{price > 0 ? price.toFixed(2) : '—'}}</span>
            {{price > 0 && <span className="text-xs text-gray-400 ml-1 line-through">${{(price * 1.2).toFixed(2)}}</span>}}
          </div>
          <button
            className="flex items-center gap-1.5 bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-3 py-1.5 rounded-xl text-sm font-semibold transition-all"
            disabled={{product.stock_quantity === 0}}
          >
            <ShoppingCart size={{14}} />
            Add
          </button>
        </div>
      </div>
    </div>
  )
}}

export function Dashboard() {{
  const {{ data: raw, isLoading }} = useQuery({{
    queryKey: ['{primary_table}'],
    queryFn: () => apiClient.get('{primary_endpoint}').then(r => r.data),
    staleTime: 60_000,
  }})
  const products: any[] = Array.isArray(raw) ? raw : (raw?.items ?? raw?.data ?? [])

  return (
    <div className="min-h-screen bg-white">
      {{/* ── Hero Section ── */}}
      <section className="relative overflow-hidden bg-gradient-to-br from-gray-900 via-brand-900 to-brand-700 text-white">
        {{/* Subtle grid overlay */}}
        <div className="absolute inset-0 opacity-[0.07]"
          style={{{{ backgroundImage: 'repeating-linear-gradient(0deg,transparent,transparent 40px,#fff 40px,#fff 41px),repeating-linear-gradient(90deg,transparent,transparent 40px,#fff 40px,#fff 41px)' }}}} />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24 md:py-36">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 bg-white/10 backdrop-blur-sm border border-white/20 rounded-full px-4 py-1.5 mb-8">
              <CheckCircle size={{14}} className="text-green-400" />
              <span className="text-xs font-semibold tracking-wide">New Collection · Spring 2025</span>
            </div>
            <h1 className="text-5xl md:text-7xl font-extrabold leading-none tracking-tight mb-6">
              Discover<br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-200 to-white">
                Something
              </span><br />
              Beautiful
            </h1>
            <p className="text-lg md:text-xl text-gray-300 mb-10 leading-relaxed max-w-xl">
              Handcrafted with love. Every piece in our collection is thoughtfully designed and built to last a lifetime.
            </p>
            <div className="flex flex-wrap gap-4">
              <Link to="{primary_route}"
                className="inline-flex items-center gap-2 bg-white text-brand-800 font-bold px-8 py-4 rounded-xl hover:bg-brand-50 transition-all shadow-xl hover:shadow-2xl hover:-translate-y-0.5">
                Shop Now <ArrowRight size={{18}} />
              </Link>
              <a href="#featured"
                className="inline-flex items-center gap-2 border-2 border-white/30 text-white font-semibold px-8 py-4 rounded-xl hover:bg-white/10 transition-all">
                Explore Collection
              </a>
            </div>
          </div>
        </div>
        {{/* Wave divider */}}
        <div className="absolute bottom-0 left-0 right-0">
          <svg viewBox="0 0 1440 60" fill="white" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none" className="w-full h-10 md:h-16">
            <path d="M0,60 C360,0 1080,60 1440,20 L1440,60 Z" />
          </svg>
        </div>
      </section>

      {{/* ── Trust badges ── */}}
      <section className="py-12 border-b border-gray-100">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            {{TRUST_BADGES.map(b => (
              <div key={{b.title}} className="flex items-center gap-3">
                <div className="text-2xl shrink-0">{{b.emoji}}</div>
                <div>
                  <p className="text-sm font-semibold text-gray-900">{{b.title}}</p>
                  <p className="text-xs text-gray-500">{{b.sub}}</p>
                </div>
              </div>
            ))}}
          </div>
        </div>
      </section>

      {{/* ── Featured Products ── */}}
      <section id="featured" className="py-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-end justify-between mb-10">
            <div>
              <p className="text-brand-600 text-xs font-bold uppercase tracking-widest mb-2">Our Collection</p>
              <h2 className="text-3xl md:text-4xl font-extrabold text-gray-900">Featured Products</h2>
            </div>
            <Link to="{primary_route}"
              className="hidden sm:flex items-center gap-2 text-sm font-semibold text-brand-600 hover:text-brand-700 transition-colors">
              View All <ArrowRight size={{16}} />
            </Link>
          </div>

          {{isLoading ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
              {{Array.from({{ length: 8 }}).map((_, i) => (
                <div key={{i}} className="rounded-2xl bg-gray-100 animate-pulse" style={{{{ aspectRatio: '3/4' }}}} />
              ))}}
            </div>
          ) : products.length === 0 ? (
            <div className="text-center py-20 text-gray-400">
              <ShoppingCart size={{48}} className="mx-auto mb-4 opacity-30" />
              <p className="text-lg font-medium">No products yet</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
              {{products.slice(0, 8).map((p, i) => (
                <ProductCard key={{p.id ?? i}} product={{p}} index={{i}} />
              ))}}
            </div>
          )}}

          {{products.length > 8 && (
            <div className="text-center mt-10">
              <Link to="{primary_route}"
                className="inline-flex items-center gap-2 border-2 border-brand-600 text-brand-600 font-bold px-8 py-3.5 rounded-xl hover:bg-brand-600 hover:text-white transition-all">
                View All {{products.length}} Products <ArrowRight size={{18}} />
              </Link>
            </div>
          )}}
        </div>
      </section>

      {{/* ── Why Choose Us ── */}}
      <section className="py-16 bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <p className="text-brand-600 text-xs font-bold uppercase tracking-widest mb-2">Why Us</p>
          <h2 className="text-3xl font-extrabold text-gray-900 mb-12">Made With Purpose</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {{[
              {{ emoji: '🎨', title: 'Artisan Quality', desc: 'Every item is crafted by skilled artisans using time-tested techniques and premium materials.' }},
              {{ emoji: '🌱', title: 'Sustainably Sourced', desc: 'We partner with ethical suppliers to ensure our products are good for you and the planet.' }},
              {{ emoji: '❤️', title: 'Made with Love', desc: 'Each product carries the dedication and passion of the maker—quality you can feel.' }},
            ].map(f => (
              <div key={{f.title}} className="bg-white rounded-2xl p-8 shadow-sm hover:shadow-md transition-shadow">
                <div className="text-4xl mb-4">{{f.emoji}}</div>
                <h3 className="text-lg font-bold text-gray-900 mb-2">{{f.title}}</h3>
                <p className="text-sm text-gray-600 leading-relaxed">{{f.desc}}</p>
              </div>
            ))}}
          </div>
        </div>
      </section>

      {{/* ── Social proof ── */}}
      <section className="py-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <p className="text-brand-600 text-xs font-bold uppercase tracking-widest mb-2">Testimonials</p>
          <h2 className="text-3xl font-extrabold text-gray-900 mb-10">What Our Customers Say</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {{[
              {{ name: 'Sarah M.', text: 'Absolutely beautiful quality. I was amazed by how much care went into every detail.', rating: 5 }},
              {{ name: 'James R.', text: 'Fast shipping, stunning packaging, and the product exceeded my expectations. Will be back!', rating: 5 }},
              {{ name: 'Emily K.', text: 'Best purchase I\'ve made in years. My friends keep asking where I got it from.', rating: 5 }},
            ].map(r => (
              <div key={{r.name}} className="bg-white rounded-2xl p-6 border border-gray-100 shadow-sm text-left">
                <div className="flex items-center gap-0.5 mb-3">
                  {{[1,2,3,4,5].map(s => <Star key={{s}} size={{14}} className="fill-amber-400 text-amber-400" />)}}
                </div>
                <p className="text-gray-700 text-sm leading-relaxed mb-4">"{{r.text}}"</p>
                <p className="font-semibold text-gray-900 text-sm">— {{r.name}}</p>
              </div>
            ))}}
          </div>
        </div>
      </section>
    </div>
  )
}}
"""


def _generate_entity_page(
    ent: dict,
    route_map: Dict[str, str],
    fk_refs: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    """Generate a full CRUD page for one entity.

    fk_refs: maps field_name -> {endpoint, label_key} from domain_ir FK data.
    When None, heuristic pluralisation is used as fallback.
    """
    table = ent["table"]
    columns = ent["columns"]
    pascal = _to_pascal_case(table)       # component name: "LeadContacts" (page class)
    type_name = _to_type_name(table)      # type name: "LeadContact" (singular)
    camel = table[0].lower() + pascal[1:]  # api var: "leadContactsApi"
    label = _to_label(table)
    singular = _to_singular(label)

    # Visible columns for the table (exclude sensitive/system cols)
    display_cols = [c for c in columns if c.lower() not in _EXCLUDED_COLS]

    # Form fields (exclude same set)
    form_cols = [c for c in columns if c.lower() not in _EXCLUDED_COLS]

    # Build ColumnDef list
    col_defs: List[str] = []
    for col in display_cols:
        col_label = _to_label(col)
        col_defs.append(
            f"  {{\n"
            f"    accessorKey: '{col}' as const,\n"
            f"    header: '{col_label}',\n"
            f"    cell: ({{ getValue }}) => {{\n"
            f"      const v = getValue() as unknown\n"
            f"      if (v === null || v === undefined) return <span className=\"text-gray-400\">—</span>\n"
            f"      return <span>{{String(v)}}</span>\n"
            f"    }},\n"
            f"  }},"
        )

    # Build FIELDS array — FK fields get fk-select type with real endpoint + label key
    field_defs: List[str] = []
    fk_config_entries: List[str] = []   # for FK_CONFIG prop (legacy CrudModal support)

    for col in form_cols:
        col_label = _to_label(col)
        field_type = _col_to_field_def_type(col)
        is_required = col.lower() not in ("description", "notes", "body", "content", "bio")
        options = _col_to_field_options(col)
        col_lower = col.lower()

        is_fk = col_lower.endswith("_id") and col_lower != "id"

        if is_fk:
            # Resolve endpoint + label key from domain_ir refs (most accurate)
            # or fall back to corrected heuristic (fixed pluralisation, /api/ prefix)
            if fk_refs and col in fk_refs:
                ref_info = fk_refs[col]
                fk_endpoint = ref_info["endpoint"]
                fk_label = ref_info.get("label_key", "name")
            else:
                related = col[:-3]  # strip "_id": category_id → category
                fk_endpoint = f"/api/{_pluralise(related)}"
                fk_label = "name"

            field_defs.append(
                f"  {{ name: '{col}', label: '{col_label}', type: 'fk-select', "
                f"required: {str(is_required).lower()}, "
                f"fkEndpoint: '{fk_endpoint}', fkLabelKey: '{fk_label}' }},"
            )
            fk_config_entries.append(f"  '{col}': '{fk_endpoint}',")

        elif options is not None:
            opts_json = json.dumps(options)
            field_defs.append(
                f"  {{ name: '{col}', label: '{col_label}', type: '{field_type}', "
                f"required: {str(is_required).lower()}, options: {opts_json} }},"
            )
        else:
            field_defs.append(
                f"  {{ name: '{col}', label: '{col_label}', type: '{field_type}', "
                f"required: {str(is_required).lower()} }},"
            )

    col_defs_str = "\n".join(col_defs)
    field_defs_str = "\n".join(field_defs)

    fk_config_str = "\n".join(fk_config_entries)
    fk_config_prop = f"\n        fkConfig={{FK_CONFIG}}" if fk_config_entries else ""
    fk_config_const = (
        f"\nconst FK_CONFIG: Record<string, string> = {{\n{fk_config_str}\n}}\n"
        if fk_config_entries else ""
    )

    return f"""\
// Auto-generated by AetherOS p05_frontend
import {{ useState }} from 'react'
import {{ useQuery, useMutation, useQueryClient }} from '@tanstack/react-query'
import {{ type ColumnDef }} from '@tanstack/react-table'
import {{ DataTable }} from '../components/DataTable'
import {{ CrudModal, type FieldDef }} from '../components/CrudModal'
import {{ {camel}Api }} from '../lib/api'
import {{ type {type_name} }} from '../types'
import {{ useToast }} from '../components/Toaster'
import {{ Plus, Pencil, Trash2 }} from 'lucide-react'

const FIELDS: FieldDef[] = [
{field_defs_str}
]
{fk_config_const}

export function {pascal}Page() {{
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<{type_name} | null>(null)
  const qc = useQueryClient()
  const {{ toast }} = useToast()

  const {{ data = [], isLoading }} = useQuery({{
    queryKey: ['{table}'],
    queryFn: {camel}Api.list,
  }})

  const create = useMutation({{
    mutationFn: {camel}Api.create,
    onSuccess: () => {{
      qc.invalidateQueries({{ queryKey: ['{table}'] }})
      setModalOpen(false)
      toast('{singular} created', 'success')
    }},
    onError: (err: unknown) => {{
      const msg = (err as {{ response?: {{ data?: {{ detail?: string }} }} }})?.response?.data?.detail ?? 'Failed to create {singular}'
      toast(msg, 'error')
    }},
  }})

  const update = useMutation({{
    mutationFn: ({{ id, data }}: {{ id: string | number; data: Partial<{type_name}> }}) =>
      {camel}Api.update(id, data),
    onSuccess: () => {{
      qc.invalidateQueries({{ queryKey: ['{table}'] }})
      setModalOpen(false)
      setEditing(null)
      toast('{singular} updated', 'success')
    }},
    onError: (err: unknown) => {{
      const msg = (err as {{ response?: {{ data?: {{ detail?: string }} }} }})?.response?.data?.detail ?? 'Failed to update {singular}'
      toast(msg, 'error')
    }},
  }})

  const remove = useMutation({{
    mutationFn: {camel}Api.remove,
    onSuccess: () => {{
      qc.invalidateQueries({{ queryKey: ['{table}'] }})
      toast('{singular} deleted', 'success')
    }},
    onError: () => toast('Failed to delete {singular}', 'error'),
  }})

  const columns: ColumnDef<{type_name}>[] = [
{col_defs_str}
    {{
      id: 'actions',
      header: '',
      cell: ({{ row }}) => (
        <div className="flex gap-2">
          <button
            onClick={{() => {{ setEditing(row.original); setModalOpen(true) }}}}
            className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
            title="Edit"
          >
            <Pencil size={{15}} />
          </button>
          <button
            onClick={{() => {{
              if (window.confirm('Delete this record?')) {{
                remove.mutate(row.original.id as string | number)
              }}
            }}}}
            className="p-1.5 text-gray-400 hover:text-red-500 rounded"
            title="Delete"
          >
            <Trash2 size={{15}} />
          </button>
        </div>
      ),
    }},
  ]

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{label}</h1>
        <button
          onClick={{() => {{ setEditing(null); setModalOpen(true) }}}}
          className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 text-sm font-medium"
        >
          <Plus size={{16}} />
          Add {singular}
        </button>
      </div>

      <DataTable data={{data}} columns={{columns}} isLoading={{isLoading}} />

      <CrudModal
        isOpen={{modalOpen}}
        onClose={{() => {{ setModalOpen(false); setEditing(null) }}}}
        onSubmit={{formData => {{
          if (editing) {{
            update.mutate({{ id: editing.id as string | number, data: formData as Partial<{type_name}> }})
          }} else {{
            create.mutate(formData as any)
          }}
        }}}}
        initialValues={{editing ?? undefined}}
        fields={{FIELDS}}
        title={{editing ? `Edit {singular}` : `New {singular}`}}
        isLoading={{create.isPending || update.isPending}}{fk_config_prop}
      />
    </div>
  )
}}
"""


def _generate_product_grid_page(ent: dict, route_map: Dict[str, str]) -> str:
    """Generate a beautiful product card grid page for ecommerce entities."""
    table = ent["table"]
    pascal = _to_pascal_case(table)
    label = _to_label(table)
    singular = _to_singular(label)
    endpoint = route_map.get(table, f"/{table}")

    # Detect price / name / image fields
    cols = [c.lower() for c in ent.get("columns", [])]
    price_field = next((c for c in cols if c in ("price", "unit_price", "amount", "cost", "sale_price")), "price")
    name_field = next((c for c in cols if c in ("name", "title", "product_name")), "name")
    img_field = next((c for c in cols if "image" in c or "photo" in c or "thumbnail" in c), None)
    cat_field = next((c for c in cols if "category" in c or "type" in c or "collection" in c), None)

    img_expr = f"product.{img_field}" if img_field else "null"
    cat_expr = f"product.{cat_field} ?? 'Collection'" if cat_field else "'Collection'"

    return f"""\
// Auto-generated by AetherOS p05_frontend - product card grid
import {{ useState }} from 'react'
import {{ useQuery }} from '@tanstack/react-query'
import {{ apiClient }} from '../lib/api'
import {{ Star, ShoppingCart, Search, SlidersHorizontal }} from 'lucide-react'

const SORT_OPTIONS = [
  {{ value: 'default', label: 'Featured' }},
  {{ value: 'price-asc', label: 'Price: Low to High' }},
  {{ value: 'price-desc', label: 'Price: High to Low' }},
  {{ value: 'name', label: 'Name A–Z' }},
]

function StarRating({{ rating = 4.5 }}: {{ rating?: number }}) {{
  return (
    <div className="flex items-center gap-0.5">
      {{[1,2,3,4,5].map(s => (
        <Star key={{s}} size={{11}}
          className={{s <= Math.round(rating) ? 'fill-amber-400 text-amber-400' : 'text-gray-200'}} />
      ))}}
    </div>
  )
}}

function ProductCard({{ product, index }}: {{ product: any; index: number }}) {{
  const seed = product.id ?? index + 1
  const rawPrice = product.{price_field} ?? 0
  const price = typeof rawPrice === 'number' ? rawPrice : parseFloat(rawPrice) || 0
  const rating = typeof product.rating === 'number' ? product.rating : 4.0 + ((seed * 13) % 10) * 0.1
  const imgSrc = {img_expr} ?? `https://picsum.photos/seed/${{seed}}/400/400`

  return (
    <div className="group bg-white rounded-2xl overflow-hidden border border-gray-100 shadow-sm hover:shadow-xl transition-all duration-300 hover:-translate-y-0.5 flex flex-col">
      <div className="relative aspect-square bg-gray-50 overflow-hidden">
        <img src={{imgSrc}} alt={{product.{name_field} ?? '{singular}'}}
          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
          loading="lazy"
          onError={{e => {{ (e.target as HTMLImageElement).src = `https://picsum.photos/seed/${{seed + 100}}/400/400` }}}} />
        {{price > 0 && (
          <span className="absolute top-3 right-3 bg-green-500 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
            Save {{Math.floor(Math.random() * 20 + 10)}}%
          </span>
        )}}
      </div>
      <div className="p-4 flex flex-col flex-1">
        <p className="text-[11px] font-bold text-brand-600 uppercase tracking-wider mb-1">{{{cat_expr}}}</p>
        <h3 className="text-sm font-semibold text-gray-900 leading-snug mb-2 line-clamp-2 flex-1">
          {{product.{name_field} ?? '{singular}'}}
        </h3>
        <StarRating rating={{rating}} />
        <div className="flex items-center justify-between mt-3">
          <span className="text-lg font-bold text-gray-900">
            {{price > 0 ? `$${{price.toFixed(2)}}` : 'Contact us'}}
          </span>
          <button className="flex items-center gap-1.5 bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-3 py-1.5 rounded-xl text-xs font-bold transition-all">
            <ShoppingCart size={{13}} /> Add
          </button>
        </div>
      </div>
    </div>
  )
}}

export function {pascal}Page() {{
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('default')
  const [showFilters, setShowFilters] = useState(false)

  const {{ data: raw, isLoading }} = useQuery({{
    queryKey: ['{table}'],
    queryFn: () => apiClient.get('{endpoint}').then(r => r.data),
    staleTime: 60_000,
  }})

  const all: any[] = Array.isArray(raw) ? raw : (raw?.items ?? raw?.data ?? [])
  const filtered = all
    .filter(p => !search || (p.{name_field} ?? '').toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {{
      if (sort === 'price-asc') return (a.{price_field} ?? 0) - (b.{price_field} ?? 0)
      if (sort === 'price-desc') return (b.{price_field} ?? 0) - (a.{price_field} ?? 0)
      if (sort === 'name') return (a.{name_field} ?? '').localeCompare(b.{name_field} ?? '')
      return 0
    }})

  return (
    <div className="min-h-screen bg-white">
      {{/* Page header */}}
      <div className="bg-gray-50 border-b border-gray-100 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-extrabold text-gray-900">{label}</h1>
          <p className="text-gray-500 mt-1 text-sm">{{all.length}} items available</p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {{/* Toolbar */}}
        <div className="flex flex-col sm:flex-row gap-4 mb-8">
          <div className="relative flex-1 max-w-sm">
            <Search size={{16}} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="search"
              placeholder="Search {label.lower()}..."
              value={{search}}
              onChange={{e => setSearch(e.target.value)}}
              className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-300 focus:border-brand-400 transition-all"
            />
          </div>
          <div className="flex items-center gap-3 ml-auto">
            <button onClick={{() => setShowFilters(v => !v)}}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-gray-200 text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all">
              <SlidersHorizontal size={{15}} /> Filters
            </button>
            <select value={{sort}} onChange={{e => setSort(e.target.value)}}
              className="px-4 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand-300 bg-white cursor-pointer">
              {{SORT_OPTIONS.map(o => <option key={{o.value}} value={{o.value}}>{{o.label}}</option>)}}
            </select>
          </div>
        </div>

        {{/* Results count */}}
        {{search && (
          <p className="text-sm text-gray-500 mb-4">
            {{filtered.length}} result{{filtered.length !== 1 ? 's' : ''}} for "<span className="font-semibold">{{search}}</span>"
          </p>
        )}}

        {{/* Grid */}}
        {{isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
            {{Array.from({{ length: 12 }}).map((_, i) => (
              <div key={{i}} className="rounded-2xl bg-gray-100 animate-pulse" style={{{{ aspectRatio: '3/4' }}}} />
            ))}}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-24">
            <ShoppingCart size={{48}} className="mx-auto mb-4 text-gray-200" />
            <h3 className="text-lg font-semibold text-gray-700">No {label.lower()} found</h3>
            {{search && <p className="text-sm text-gray-400 mt-1">Try a different search term</p>}}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
            {{filtered.map((p, i) => <ProductCard key={{p.id ?? i}} product={{p}} index={{i}} />)}}
          </div>
        )}}
      </div>
    </div>
  )
}}
"""


def _is_product_entity(table: str) -> bool:
    """Return True if this entity should render as a product card grid in storefront."""
    lower = table.lower()
    _product_kws = ("product", "item", "goods", "listing", "sku", "artifact", "merchandise", "commodity")
    return any(k in lower for k in _product_kws)


def _generate_docker_compose(project_dir: Path) -> str:
    """Generate a docker-compose.yml that wires app + frontend services."""
    return """\
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "${API_PORT:-8000}:8000"
    environment:
      DATABASE_URL: ${DATABASE_URL:-sqlite:///./data/app.db}
      SECRET_KEY: ${SECRET_KEY:-changeme-in-production-use-64-char-hex}
    volumes:
      - db_data:/app/data
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 20s

  frontend:
    build:
      context: ./frontend
      args:
        # VITE_ vars baked at build time — pass as args, not runtime env
        # Default is empty so nginx /api/ proxy is used (works on any server)
        # Override: VITE_API_URL=http://your-server:8000 docker-compose up
        VITE_API_URL: ${VITE_API_URL:-}
    ports:
      - "${PORT:-80}:80"
    depends_on:
      app:
        condition: service_healthy

volumes:
  db_data:
"""


# ── Main entry point ───────────────────────────────────────────────────────────

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data

    # 1. Read architecture
    arch = _read_architecture(data)
    project_name = data.get("project_name", arch.get("project_name", "Project Dashboard"))
    project_slug = re.sub(r"[^a-z0-9-]", "-", project_name.lower()).strip("-") or "project"
    route_map: Dict[str, str] = arch.get("api_route_map", {})

    # 2. Normalise entities — prefer Domain IR when available
    _ir_path_str = data.get("domain_ir_path", "")
    _domain_ir = None
    if _ir_path_str:
        _ir_p = Path(_ir_path_str)
        if _ir_p.exists():
            try:
                from aether_os.core.domain_ir import DomainIR as _DomainIR
                from aether_os.phases.p05_frontend.ir_generators import ir_to_p05_entities as _ir_to_ents
                _domain_ir = _DomainIR.load(_ir_p)
                if _domain_ir.entities:
                    entities = _ir_to_ents(_domain_ir)
                    logger.info(
                        "p05: IR fast-path — %d typed entities from domain_ir.json",
                        len(entities),
                    )
                else:
                    _domain_ir = None
            except Exception as _ir_exc:
                logger.warning("p05: domain_ir load failed (%s) — using arch fallback", _ir_exc)
                _domain_ir = None

    if _domain_ir is None:
        entities = _normalise_entities(arch)
        # 2a. If we only got the generic 'items' fallback, try reading models.py directly.
        if len(entities) == 1 and entities[0]["table"] == "items":
            _models_entities = _extract_all_entities_from_models_py(data)
            if _models_entities:
                logger.info(
                    "p05: replaced generic 'items' fallback with %d real entities from models.py",
                    len(_models_entities),
                )
                entities = _models_entities

    # 2b. Detect application domain (used for stat labels + LLM widget)
    domain = _detect_domain(phase_input)
    logger.info("p05_frontend: detected domain=%s for project=%s", domain, project_name)

    from aether_os.phases.utils import memory_hint
    mem = memory_hint(memory_ctx)

    # Extract designer spec settings
    designer_spec = data.get("designer_spec") or {}
    _design = designer_spec.get("design") or {}
    ui_theme: str = _design.get("ui_theme", "default") or "default"
    page_transition: str = _design.get("page_transition", "fade") or "fade"
    animation_speed: str = _design.get("animation_speed", "normal") or "normal"
    micro_interactions: bool = bool(_design.get("micro_interactions", True))
    scroll_reveal: bool = bool(_design.get("scroll_reveal", True))
    loading_style: str = _design.get("loading_style", "shimmer") or "shimmer"
    hover_lift: bool = bool(_design.get("hover_lift", True))
    logger.info("p05_frontend: ui_theme=%s transition=%s speed=%s", ui_theme, page_transition, animation_speed)

    # Detect layout mode from designer_spec, domain, or raw_input keywords
    _layout_from_spec = (_design.get("layout") or "")
    _raw = data.get("raw_input", "").lower()
    _domain_val = domain  # already detected above

    # Domains that benefit from dual portal (customer-facing + owner/admin split)
    _dual_portal_domains = ("ecommerce", "marketplace", "library", "healthcare",
                             "hospitality", "education", "events", "real_estate",
                             "fitness", "food", "saas", "gym_fitness", "sports",
                             "restaurant")
    # Domains that are purely internal management tools
    _internal_only_domains = ("crm", "hrm", "analytics", "fintech", "iot",
                               "security", "logistics")

    if "layout_mode" in (designer_spec or {}):
        layout_mode = designer_spec["layout_mode"]
    elif _layout_from_spec:
        layout_mode = _layout_from_spec
    elif "dual portal" in _raw or "customer portal" in _raw or "member portal" in _raw:
        layout_mode = "dual"
    elif "storefront" in _raw or "customer-facing" in _raw or "landing page" in _raw:
        layout_mode = "storefront"
    elif _domain_val in _dual_portal_domains:
        # Domain takes priority over loose keyword heuristics — "management" and "admin"
        # appear naturally in almost every app description; trust the domain signal first.
        layout_mode = "dual"
    elif _domain_val in _internal_only_domains:
        layout_mode = "admin"
    elif "admin panel" in _raw or "internal tool" in _raw or "back office" in _raw or "back-office" in _raw:
        layout_mode = "admin"
    else:
        layout_mode = "dual"  # default: generate both portals
    logger.info("p05_frontend: layout_mode=%s", layout_mode)

    # 3. Build frontend/ directory
    frontend_dir = output_dir / "frontend"
    src_dir = frontend_dir / "src"
    (src_dir / "lib").mkdir(parents=True, exist_ok=True)
    (src_dir / "types").mkdir(parents=True, exist_ok=True)
    (src_dir / "components").mkdir(parents=True, exist_ok=True)
    (src_dir / "pages").mkdir(parents=True, exist_ok=True)

    # ── Static files ──────────────────────────────────────────────────────────
    (frontend_dir / "package.json").write_text(_generate_package_json(project_slug))
    (frontend_dir / "vite.config.ts").write_text(_generate_vite_config())
    (frontend_dir / "tsconfig.json").write_text(_generate_tsconfig())
    (frontend_dir / "tailwind.config.js").write_text(_generate_tailwind_config(ui_theme))
    (frontend_dir / "postcss.config.js").write_text(_generate_postcss_config())
    (frontend_dir / "index.html").write_text(_generate_index_html(project_name, domain=domain))
    (frontend_dir / "nginx.conf").write_text(_generate_nginx_conf(data))
    (frontend_dir / "Dockerfile").write_text(_generate_dockerfile())
    (frontend_dir / ".env.example").write_text(_generate_env_example())
    (frontend_dir / ".eslintrc.cjs").write_text(_generate_eslint_config())
    (frontend_dir / "README.md").write_text(_generate_frontend_readme(project_name))
    (src_dir / "index.css").write_text(_generate_index_css(
        ui_theme=ui_theme,
        page_transition=page_transition,
        animation_speed=animation_speed,
        micro_interactions=micro_interactions,
        scroll_reveal=scroll_reveal,
        loading_style=loading_style,
        hover_lift=hover_lift,
    ))
    (src_dir / "main.tsx").write_text(_generate_main_tsx())

    # ── lib/ ──────────────────────────────────────────────────────────────────
    (src_dir / "lib" / "auth.ts").write_text(_generate_auth_ts())
    (src_dir / "lib" / "api.ts").write_text(_generate_api(entities, route_map))

    # ── types/ ────────────────────────────────────────────────────────────────
    (src_dir / "types" / "index.ts").write_text(_generate_types(entities))

    # ── components/ ───────────────────────────────────────────────────────────
    if layout_mode == "dual":
        # Dual portal: separate customer-facing and admin layouts
        (src_dir / "components" / "CustomerLayout.tsx").write_text(
            _generate_customer_layout(entities, project_name)
        )
        (src_dir / "components" / "AdminLayout.tsx").write_text(
            _generate_admin_layout(entities, project_name)
        )
        # Keep Layout.tsx as alias pointing to AdminLayout for backwards compat
        (src_dir / "components" / "Layout.tsx").write_text(
            "export { AdminLayout as Layout } from './AdminLayout'\n"
        )
    else:
        (src_dir / "components" / "Layout.tsx").write_text(
            _generate_layout(entities, project_name, layout_mode=layout_mode)
        )
    (src_dir / "components" / "DataTable.tsx").write_text(_generate_data_table())
    (src_dir / "components" / "CrudModal.tsx").write_text(_generate_crud_modal())
    (src_dir / "components" / "Toaster.tsx").write_text(_generate_toaster())
    (src_dir / "components" / "ErrorBoundary.tsx").write_text(_generate_error_boundary())

    # ── pages/ ────────────────────────────────────────────────────────────────
    (src_dir / "pages" / "LoginPage.tsx").write_text(
        _generate_login_page(project_name, layout_mode=layout_mode)
    )
    (src_dir / "pages" / "NotFoundPage.tsx").write_text(_generate_not_found_page())
    if layout_mode == "dual":
        # Generate customer-facing home page (browsing/self-service)
        (src_dir / "pages" / "CustomerHome.tsx").write_text(
            _generate_customer_home(entities, route_map, project_name, domain)
        )

    if _domain_ir and _domain_ir.entities:
        # IR fast-path: dashboard with real KPI cards, entity pages with typed forms
        from aether_os.phases.p05_frontend.ir_generators import (
            generate_ir_dashboard_tsx as _gen_dash,
            generate_ir_entity_page as _gen_ent_page,
            generate_ir_types_ts as _gen_types,
        )
        (src_dir / "pages" / "Dashboard.tsx").write_text(
            _gen_dash(_domain_ir, entities, project_name, domain=domain)
        )
        for ir_entity in _domain_ir.entities:
            # In storefront mode, product-type entities get a beautiful card grid
            if layout_mode == "storefront" and _is_product_entity(ir_entity.table):
                _ir_ent_dict = {
                    "table": ir_entity.table,
                    "name": ir_entity.name,
                    "columns": [f.name for f in ir_entity.fields],
                }
                (src_dir / "pages" / f"{ir_entity.name}Page.tsx").write_text(
                    _generate_product_grid_page(_ir_ent_dict, route_map)
                )
            else:
                (src_dir / "pages" / f"{ir_entity.name}Page.tsx").write_text(
                    _gen_ent_page(ir_entity)
                )
        # Override types/index.ts with IR-derived typed interfaces + Zod schemas
        (src_dir / "types" / "index.ts").write_text(_gen_types(_domain_ir))
        logger.info("p05: IR fast-path — dashboard + %d typed entity pages written", len(_domain_ir.entities))
    else:
        (src_dir / "pages" / "Dashboard.tsx").write_text(_generate_dashboard(entities, route_map, domain))

        # Build a global FK refs map from domain_ir (if partially loaded) so fallback
        # entity pages get correct FK endpoints and label keys instead of pure heuristics.
        _global_fk_refs: Dict[str, Dict[str, str]] = {}
        if _domain_ir:
            try:
                from aether_os.core.domain_ir import AetherType as _AT
                for ir_ent in (_domain_ir.entities or []):
                    for ir_field in ir_ent.fields:
                        if ir_field.type == _AT.FK and ir_field.ref_entity:
                            ref_lower = ir_field.ref_entity.lower()
                            _global_fk_refs[ir_field.name] = {
                                "endpoint": f"/api/{_pluralise(ref_lower)}",
                                "label_key": getattr(ir_field, "display_field", None) or "name",
                            }
            except Exception as _fk_exc:
                logger.debug("p05: could not build fk_refs from domain_ir: %s", _fk_exc)

        for ent in entities:
            # Use entity name (singular) to match App.tsx and IR fast-path naming
            pascal = ent.get("name") or _to_pascal_case(ent["table"])
            # In storefront mode, product-type entities get a beautiful card grid
            if layout_mode == "storefront" and _is_product_entity(ent["table"]):
                (src_dir / "pages" / f"{pascal}Page.tsx").write_text(
                    _generate_product_grid_page(ent, route_map)
                )
            else:
                (src_dir / "pages" / f"{pascal}Page.tsx").write_text(
                    _generate_entity_page(ent, route_map, fk_refs=_global_fk_refs or None)
                )

    # ── App.tsx ───────────────────────────────────────────────────────────────
    (src_dir / "App.tsx").write_text(_generate_app(entities, dual_portal=(layout_mode == "dual")))

    # ── Tests ─────────────────────────────────────────────────────────────────
    tests_dir = src_dir / "__tests__"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "setup.ts").write_text(_generate_test_setup())
    (tests_dir / "LoginPage.test.tsx").write_text(_generate_login_test(project_name))
    (tests_dir / "Dashboard.test.tsx").write_text(_generate_dashboard_test())
    (frontend_dir / "vitest.config.ts").write_text(_generate_vitest_config())

    # ── Domain-specific LLM component (non-fatal bonus step) ─────────────────
    domain_widget_generated = False
    try:
        domain_component = await _generate_domain_component(domain, entities, project_name, mem)
        if domain_component:
            domain_file = src_dir / "components" / "DomainWidget.jsx"
            domain_file.write_text(domain_component)

            # Patch Dashboard.tsx: add import + replace slot sentinel with actual widget
            dashboard_file = src_dir / "pages" / "Dashboard.tsx"
            if dashboard_file.exists():
                content = dashboard_file.read_text()
                if "DomainWidget" not in content:
                    # Insert import after the first import line
                    content = content.replace(
                        "import { useQuery }",
                        "import DomainWidget from '../components/DomainWidget'\nimport { useQuery }",
                        1,
                    )
                    # Replace the sentinel slot with the actual rendered widget
                    content = content.replace(
                        "{/* DOMAIN_WIDGET_SLOT */}",
                        '<div className="mt-8"><DomainWidget /></div>',
                        1,
                    )
                    dashboard_file.write_text(content)

            domain_widget_generated = True
            logger.info(
                "p05_frontend: generated %s DomainWidget.jsx (%d chars)",
                domain,
                len(domain_component),
            )
    except Exception as _de:
        logger.debug("p05_frontend: domain component generation failed (non-fatal): %s", _de)
        # Clean up the sentinel comment so it doesn't appear in the shipped JSX
        try:
            dashboard_file = src_dir / "pages" / "Dashboard.tsx"
            if dashboard_file.exists():
                content = dashboard_file.read_text()
                content = content.replace("      {/* DOMAIN_WIDGET_SLOT */}\n", "")
                dashboard_file.write_text(content)
        except Exception:
            pass

    # 4. Write docker-compose.yml to the project root (one level up from output_dir)
    # output_dir is like ~/.aether_os/projects/<run_id>/p05_frontend
    # project_dir is ~/.aether_os/projects/<run_id>
    project_dir = output_dir.parent
    docker_compose_path = project_dir / "docker-compose.yml"
    docker_compose_path.write_text(_generate_docker_compose(project_dir))

    # 4a. Copy frontend to canonical project_dir/frontend/ so docker-compose
    # `context: ./frontend` resolves correctly and the delivery ZIP has frontend/ at root.
    _canonical_frontend = project_dir / "frontend"
    if not _canonical_frontend.exists() and frontend_dir.exists():
        try:
            import shutil as _shutil
            _shutil.copytree(str(frontend_dir), str(_canonical_frontend),
                             ignore=_shutil.ignore_patterns("node_modules", ".git", "dist", "build"))
            logger.info("p05_frontend: mirrored frontend/ to project root")
        except Exception as _copy_err:
            logger.warning("p05_frontend: could not mirror frontend to project root: %s", _copy_err)

    # ── Frontend council audit ─────────────────────────────────────────────────
    frontend_audit: Dict[str, Any] = {"passed": True, "failures": [], "corrections": ""}
    try:
        dashboard_code = (src_dir / "pages" / "Dashboard.tsx").read_text()
        from aether_os.core.council.council import FrontendAuditCouncil
        frontend_audit = await FrontendAuditCouncil().audit(dashboard_code)
        if not frontend_audit["passed"]:
            logger.warning("[p05] FrontendAuditCouncil failures: %s", frontend_audit["failures"])
    except Exception as _fac_exc:
        logger.debug("[p05] FrontendAuditCouncil skipped: %s", _fac_exc)

    # 5. Write frontend_meta.json
    generated_files = [
        "frontend/package.json",
        "frontend/vite.config.ts",
        "frontend/vitest.config.ts",
        "frontend/tsconfig.json",
        "frontend/tailwind.config.js",
        "frontend/postcss.config.js",
        "frontend/index.html",
        "frontend/nginx.conf",
        "frontend/Dockerfile",
        "frontend/.env.example",
        "frontend/.eslintrc.cjs",
        "frontend/README.md",
        "frontend/src/index.css",
        "frontend/src/main.tsx",
        "frontend/src/App.tsx",
        "frontend/src/lib/auth.ts",
        "frontend/src/lib/api.ts",
        "frontend/src/types/index.ts",
        "frontend/src/components/Layout.tsx",
        "frontend/src/components/DataTable.tsx",
        "frontend/src/components/CrudModal.tsx",
        "frontend/src/components/Toaster.tsx",
        "frontend/src/components/ErrorBoundary.tsx",
        "frontend/src/pages/LoginPage.tsx",
        "frontend/src/pages/Dashboard.tsx",
        "frontend/src/pages/NotFoundPage.tsx",
        "frontend/src/__tests__/setup.ts",
        "frontend/src/__tests__/LoginPage.test.tsx",
        "frontend/src/__tests__/Dashboard.test.tsx",
    ] + [f"frontend/src/pages/{_to_pascal_case(e['table'])}Page.tsx" for e in entities]
    if domain_widget_generated:
        generated_files.append("frontend/src/components/DomainWidget.jsx")

    meta = {
        "renderer": "react-vite-tanstack",
        "framework": "react18",
        "version": "0.1.0",
        "project_name": project_name,
        "project_slug": project_slug,
        "domain": domain,
        "entities": [e["table"] for e in entities],
        "entity_count": len(entities),
        "used_llm": domain_widget_generated,
        "domain_widget_generated": domain_widget_generated,
        "confidence": 0.9,
        "files_generated": generated_files,
        "frontend_audit": frontend_audit,
    }
    (output_dir / "frontend_meta.json").write_text(json.dumps(meta, indent=2))

    logger.info(
        "p05_frontend: generated React/Vite project at %s (entities=%s)",
        frontend_dir,
        [e["table"] for e in entities],
    )

    return TaskResult(
        output_path=str(frontend_dir),
        confidence=0.9,
        metadata=meta,
        success=True,
        issues=[],
    )
