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

# ── Domain detection ──────────────────────────────────────────────────────────

def _detect_domain(phase_input: Any) -> str:
    """Detect application domain from project description and entity names."""
    # Only trust the pre-resolved domain if it's a specific domain, not the generic fallbacks.
    _pre = getattr(phase_input, "domain", None) or ""
    if _pre and _pre not in ("", "unknown", "general", "saas"):
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

    domain_keywords = {
        "security":            ["camera", "cctv", "surveillance", "motion", "detection",
                                "guard", "alert", "incident", "zone", "monitor", "feed",
                                "security", "intrusion", "access control", "footage", "nvr",
                                "dvr", "ptz", "analytics", "ai detection", "facial"],
        "iot":                 ["sensor", "device", "telemetry", "mqtt", "firmware",
                                "gateway", "edge", "iot", "embedded", "actuator",
                                "temperature", "humidity", "smart", "arduino", "raspberry"],
        "healthcare":          ["patient", "appointment", "doctor", "clinic", "medical",
                                "prescription", "diagnosis", "health", "vitals", "nurse"],
        "crm":                 ["lead", "deal", "pipeline", "contact", "opportunity",
                                "prospect", "sales", "funnel", "crm"],
        "ecommerce":           ["product", "order", "cart", "inventory", "sku",
                                "purchase", "shop", "store", "payment", "checkout"],
        "hrm":                 ["employee", "payroll", "attendance", "leave",
                                "department", "salary", "hr", "hire", "onboard"],
        "finance":             ["invoice", "payment", "expense", "budget",
                                "transaction", "account", "billing", "ledger"],
        "project_management":  ["task", "sprint", "milestone", "ticket",
                                "board", "kanban", "project", "backlog"],
        "restaurant":          ["menu", "table", "reservation", "kitchen",
                                "dish", "waiter", "restaurant", "pos"],
        "education":           ["student", "course", "grade", "teacher",
                                "enrollment", "class", "lesson", "school"],
    }

    for domain, keywords in domain_keywords.items():
        if any(kw in all_text for kw in keywords):
            return domain
    return "saas"


# ── Domain-specific stat-card labels ─────────────────────────────────────────

_DOMAIN_STAT_LABELS: Dict[str, List[str]] = {
    "security":           ["Cameras Online", "Active Alerts", "Zones Monitored", "Incidents Today"],
    "iot":                ["Devices Online", "Active Sensors", "Alerts Today", "Avg Uptime %"],
    "healthcare":         ["Patients Today", "Appointments", "Avg Wait Time", "Staff On Duty"],
    "crm":                ["New Leads", "Open Deals", "Revenue This Month", "Conversion Rate"],
    "ecommerce":          ["Orders Today", "Revenue", "Items in Stock", "Cart Abandonment"],
    "hrm":                ["Headcount", "On Leave Today", "Open Positions", "Avg Tenure (yrs)"],
    "finance":            ["Invoices Due", "Revenue MTD", "Overdue Payments", "Burn Rate"],
    "project_management": ["Open Tasks", "Sprints Active", "PRs Merged", "Bugs Open"],
    "restaurant":         ["Tables Occupied", "Orders in Queue", "Avg Order Value", "Covers Today"],
    "education":          ["Enrolled Students", "Courses Active", "Avg Grade", "Attendance %"],
    "saas":               ["Active Users", "MRR", "Churn Rate", "NPS Score"],
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
}


async def _generate_domain_component(domain: str, entities: List[dict], project_name: str) -> Optional[str]:
    """Generate a domain-specific React component via one LLM call.

    Returns JSX source (str) on success, or None when the call fails or the
    response looks invalid. This is always wrapped in a try/except at the call
    site so failures are non-fatal.
    """
    from aether_os.core.llm.client import get_llm_client  # lazy import

    component_desc = _DOMAIN_COMPONENT_DESC.get(domain, _DOMAIN_COMPONENT_DESC["saas"])
    entity_names = [e.get("name", "") or e.get("table", "") for e in entities[:5]] if entities else []

    prompt = (
        f'Generate a React functional component for a {domain} application called "{project_name}".\n\n'
        f"The component should render: {component_desc}\n\n"
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
    """Parse CREATE TABLE statements in the generated main.py to get real column names."""
    cols_by_table: Dict[str, List[str]] = {}
    main_py_path = data.get("backend_main_py", "")
    if not main_py_path:
        backend_out = data.get("backend_output_path", "") or data.get("p04_backend_path", "")
        if backend_out:
            p = Path(backend_out)
            for candidate in [p / "src" / "main.py", p.parent / "src" / "main.py",
                               p.parent / "backend_codegen" / "src" / "main.py"]:
                if candidate.exists():
                    main_py_path = str(candidate)
                    break
    if not main_py_path or not Path(main_py_path).exists():
        return cols_by_table
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


# ── Static file generators ─────────────────────────────────────────────────────

def _generate_package_json(project_slug: str) -> str:
    data = {
        "name": project_slug,
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "tsc && vite build",
            "preview": "vite preview",
            "lint": "eslint src --ext .ts,.tsx --report-unused-disable-directives --max-warnings 0",
            "typecheck": "tsc --noEmit"
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
            "postcss": "^8.4.45"
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
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\\/api/, ''),
      }
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
            "noFallthroughCasesInSwitch": True
        },
        "include": ["src"]
    }
    return json.dumps(data, indent=2)


def _generate_tailwind_config() -> str:
    return """\
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#eff6ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          900: '#1e3a8a',
        }
      }
    }
  },
  plugins: []
}
"""


def _generate_postcss_config() -> str:
    return """\
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} }
}
"""


def _generate_index_html(project_name: str) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="icon" type="image/svg+xml" href="/vite.svg" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{project_name}</title>
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


def _generate_index_css() -> str:
    return """\
@tailwind base;
@tailwind components;
@tailwind utilities;
"""


def _generate_main_tsx() -> str:
    return """\
import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { ToastProvider } from './components/Toaster'
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
        <RouterProvider router={router} />
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
    lines.append("// When unset: proxy via Vite /api → backend (dev) or nginx /api → backend (prod)")
    lines.append("const BASE = import.meta.env.VITE_API_URL ?? ''")
    lines.append("const API_PREFIX = BASE ? '' : '/api'")
    lines.append("")
    lines.append("export const apiClient = axios.create({ baseURL: BASE + API_PREFIX })")
    lines.append("")
    lines.append("apiClient.interceptors.request.use(cfg => {")
    lines.append("  const token = getToken()")
    lines.append("  if (token) cfg.headers.Authorization = `Bearer ${token}`")
    lines.append("  return cfg")
    lines.append("})")
    lines.append("")
    lines.append("apiClient.interceptors.response.use(")
    lines.append("  r => r,")
    lines.append("  err => {")
    lines.append("    if (err.response?.status === 401) { clearToken(); window.location.href = '/login' }")
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


def _generate_app(entities: List[dict]) -> str:
    """Generate src/App.tsx with TanStack Router."""
    entity_imports: List[str] = []
    entity_routes: List[str] = []
    entity_route_children: List[str] = []

    for ent in entities:
        table = ent["table"]
        pascal = _to_pascal_case(table)
        route_path = f"/{table.replace('_', '-')}"
        route_var = f"{table}Route"

        entity_imports.append(f"import {{ {pascal}Page }} from './pages/{pascal}Page'")
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
import {{ Dashboard }} from './pages/Dashboard'
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

export const router = createRouter({{ routeTree }})

declare module '@tanstack/react-router' {{
  interface Register {{ router: typeof router }}
}}
"""


def _generate_layout(entities: List[dict], project_name: str) -> str:
    """Generate src/components/Layout.tsx."""
    # Collect icons needed
    icons_needed = {"LayoutDashboard", "LogOut"}
    for ent in entities:
        icons_needed.add(_entity_icon(ent["table"]))
    icons_str = ", ".join(sorted(icons_needed))

    nav_items: List[str] = [
        "  { to: '/' as const, label: 'Dashboard', Icon: LayoutDashboard },",
    ]
    for ent in entities:
        table = ent["table"]
        label = _to_label(table)
        icon = _entity_icon(table)
        route_path = f"/{table.replace('_', '-')}"
        nav_items.append(f"  {{ to: '{route_path}' as const, label: '{label}', Icon: {icon} }},")

    nav_items_str = "\n".join(nav_items)

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
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { X } from 'lucide-react'

export interface FieldDef {
  name: string
  label: string
  type: 'text' | 'email' | 'tel' | 'date' | 'number' | 'textarea' | 'select'
  required?: boolean
  options?: { value: string; label: string }[]
}

interface Props<T extends Record<string, unknown>> {
  isOpen: boolean
  onClose: () => void
  onSubmit: (data: T) => void
  initialValues?: Partial<T>
  fields: FieldDef[]
  title: string
  isLoading?: boolean
}

export function CrudModal<T extends Record<string, unknown>>({
  isOpen,
  onClose,
  onSubmit,
  initialValues,
  fields,
  title,
  isLoading,
}: Props<T>) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<T>()

  useEffect(() => {
    if (isOpen) reset((initialValues ?? {}) as T)
  }, [isOpen, initialValues, reset])

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
          {fields.map(f => (
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
              ) : f.type === 'select' ? (
                <select
                  {...register(f.name as any, { required: f.required })}
                  className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-brand-500"
                >
                  <option value="">Select...</option>
                  {f.options?.map(o => (
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
          ))}
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


def _generate_login_page(project_name: str) -> str:
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
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-lg p-8 w-full max-w-md">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">{project_name}</h1>
        <p className="text-gray-500 mb-8">Sign in to your account</p>
        <form onSubmit={{handleSubmit}} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              value={{email}}
              onChange={{e => setEmail(e.target.value)}}
              required
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={{password}}
              onChange={{e => setPassword(e.target.value)}}
              required
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-brand-500"
            />
          </div>
          {{error && <p className="text-sm text-red-500">{{error}}</p>}}
          <button
            type="submit"
            disabled={{loading}}
            className="w-full py-2.5 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
          >
            {{loading ? 'Signing in...' : 'Sign in'}}
          </button>
        </form>
      </div>
    </div>
  )
}}
"""


def _generate_dashboard(entities: List[dict], route_map: Dict[str, str], domain: str = "saas") -> str:
    """Generate src/pages/Dashboard.tsx with domain-aware stat cards."""
    query_lines: List[str] = []
    stat_cards: List[str] = []

    icons = ["BarChart3", "Users", "Activity", "TrendingUp", "Package", "FileText", "Calendar", "Database"]

    # Use domain-specific labels for the first four stat cards; fall back to entity label
    domain_labels = _DOMAIN_STAT_LABELS.get(domain, _DOMAIN_STAT_LABELS["saas"])

    for i, ent in enumerate(entities):
        table = ent["table"]
        camel = table[0].lower() + _to_pascal_case(table)[1:]
        endpoint = route_map.get(table, f"/{table}")
        # Use domain-specific label for first N cards, then fall back to entity name
        label = domain_labels[i] if i < len(domain_labels) else _to_label(table)
        icon = icons[i % len(icons)]

        query_lines.append(
            f"  const {{ data: {camel}Data }} = useQuery({{\n"
            f"    queryKey: ['{table}'],\n"
            f"    queryFn: () => apiClient.get<unknown[]>('{endpoint}').then(r => r.data),\n"
            f"  }})"
        )
        stat_cards.append(
            f"        <div className=\"bg-white rounded-xl border border-gray-200 p-6 shadow-sm\">\n"
            f"          <div className=\"flex items-center justify-between mb-2\">\n"
            f"            <p className=\"text-sm font-medium text-gray-500\">{label}</p>\n"
            f"            <{icon} size={{20}} className=\"text-brand-500\" />\n"
            f"          </div>\n"
            f"          <p className=\"text-3xl font-bold text-gray-900\">{{{camel}Data?.length ?? '—'}}</p>\n"
            f"        </div>"
        )

    queries_str = "\n".join(query_lines)
    cards_str = "\n".join(stat_cards)

    # Collect only the icons actually used
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
    <div className="p-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-8">Dashboard</h1>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
{cards_str}
      </div>
      {{/* DOMAIN_WIDGET_SLOT */}}
    </div>
  )
}}
"""


def _generate_entity_page(ent: dict, route_map: Dict[str, str]) -> str:
    """Generate a full CRUD page for one entity."""
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

    # Build FIELDS array
    field_defs: List[str] = []
    for col in form_cols:
        col_label = _to_label(col)
        field_type = _col_to_field_def_type(col)
        is_required = col.lower() not in ("description", "notes", "body", "content", "bio")
        options = _col_to_field_options(col)

        if options is not None:
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
        isLoading={{create.isPending || update.isPending}}
      />
    </div>
  )
}}
"""


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

    # 2. Normalise entities
    entities = _normalise_entities(arch)

    # 2a. Detect application domain (used for stat labels + LLM widget)
    domain = _detect_domain(phase_input)
    logger.info("p05_frontend: detected domain=%s for project=%s", domain, project_name)

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
    (frontend_dir / "tailwind.config.js").write_text(_generate_tailwind_config())
    (frontend_dir / "postcss.config.js").write_text(_generate_postcss_config())
    (frontend_dir / "index.html").write_text(_generate_index_html(project_name))
    (frontend_dir / "nginx.conf").write_text(_generate_nginx_conf(data))
    (frontend_dir / "Dockerfile").write_text(_generate_dockerfile())
    (frontend_dir / ".env.example").write_text(_generate_env_example())
    (frontend_dir / ".eslintrc.cjs").write_text(_generate_eslint_config())
    (src_dir / "index.css").write_text(_generate_index_css())
    (src_dir / "main.tsx").write_text(_generate_main_tsx())

    # ── lib/ ──────────────────────────────────────────────────────────────────
    (src_dir / "lib" / "auth.ts").write_text(_generate_auth_ts())
    (src_dir / "lib" / "api.ts").write_text(_generate_api(entities, route_map))

    # ── types/ ────────────────────────────────────────────────────────────────
    (src_dir / "types" / "index.ts").write_text(_generate_types(entities))

    # ── components/ ───────────────────────────────────────────────────────────
    (src_dir / "components" / "Layout.tsx").write_text(_generate_layout(entities, project_name))
    (src_dir / "components" / "DataTable.tsx").write_text(_generate_data_table())
    (src_dir / "components" / "CrudModal.tsx").write_text(_generate_crud_modal())
    (src_dir / "components" / "Toaster.tsx").write_text(_generate_toaster())

    # ── pages/ ────────────────────────────────────────────────────────────────
    (src_dir / "pages" / "LoginPage.tsx").write_text(_generate_login_page(project_name))
    (src_dir / "pages" / "Dashboard.tsx").write_text(_generate_dashboard(entities, route_map, domain))
    for ent in entities:
        pascal = _to_pascal_case(ent["table"])
        (src_dir / "pages" / f"{pascal}Page.tsx").write_text(_generate_entity_page(ent, route_map))

    # ── App.tsx ───────────────────────────────────────────────────────────────
    (src_dir / "App.tsx").write_text(_generate_app(entities))

    # ── Domain-specific LLM component (non-fatal bonus step) ─────────────────
    domain_widget_generated = False
    try:
        domain_component = await _generate_domain_component(domain, entities, project_name)
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

    # 5. Write frontend_meta.json
    generated_files = [
        "frontend/package.json",
        "frontend/vite.config.ts",
        "frontend/tsconfig.json",
        "frontend/tailwind.config.js",
        "frontend/postcss.config.js",
        "frontend/index.html",
        "frontend/nginx.conf",
        "frontend/Dockerfile",
        "frontend/.env.example",
        "frontend/.eslintrc.cjs",
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
        "frontend/src/pages/LoginPage.tsx",
        "frontend/src/pages/Dashboard.tsx",
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
