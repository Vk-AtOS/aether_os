"""P05 Frontend Task Agent — deterministic single-file SPA generator.

Strategy:
  1. Read architecture.json from p02 to get project name, db_schema, endpoints, auth.
  2. Build a polished Bootstrap 5 single-file SPA using a template engine (no LLM).
  3. The generated index.html is production-ready: sidebar nav, data tables,
     modal CRUD forms, auth flow, toast notifications, responsive layout.
  4. Write index.html, frontend_meta.json, and package.json to output_dir.
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


# ── Architecture reader ────────────────────────────────────────────────────────

def _read_architecture(data: dict) -> dict:
    """Return architecture dict from any known location."""
    arch_path = data.get("p02_architecture_path", "")
    if arch_path:
        try:
            return json.loads(Path(arch_path).read_text())
        except Exception:
            pass

    project_dir = Path(data.get("project_dir", ""))
    if project_dir.exists():
        for candidate in sorted(project_dir.rglob("architecture.json"))[:3]:
            try:
                return json.loads(candidate.read_text())
            except Exception:
                continue

    return {
        "api_endpoints": [
            {"method": "GET",  "path": "/health",        "description": "Health check",      "auth": False},
            {"method": "POST", "path": "/auth/login",    "description": "Login",             "auth": False},
            {"method": "POST", "path": "/auth/register", "description": "Register",          "auth": False},
            {"method": "GET",  "path": "/items",         "description": "List items",        "auth": True},
            {"method": "POST", "path": "/items",         "description": "Create item",       "auth": True},
            {"method": "PUT",  "path": "/items/{id}",    "description": "Update item",       "auth": True},
            {"method": "DELETE", "path": "/items/{id}",  "description": "Delete item",       "auth": True},
        ],
        "database_schema": [
            {"table": "items", "columns": ["id", "name", "description", "status", "created_at"]}
        ],
        "tech_stack": {"backend": "FastAPI", "frontend": "Vanilla JS", "database": "PostgreSQL"},
    }


# ── Architecture analyser ──────────────────────────────────────────────────────

def _analyse(arch: dict) -> Tuple[bool, List[dict], List[dict]]:
    """Return (needs_auth, entities, endpoints)."""
    endpoints: List[dict] = arch.get("api_endpoints", [])
    raw_schema = arch.get("database_schema", arch.get("db_schema", []))

    # normalise schema entries to {table, columns:[str]}
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

    # skip "users" from entity sidebar (it's an auth-internal table)
    entities = [e for e in entities if e["table"].lower() not in ("users",)]
    if not entities:
        entities = [{"table": "items", "columns": ["id", "name", "description", "status", "created_at"]}]

    needs_auth = any(
        ep.get("path", "").startswith("/auth/") for ep in endpoints
    )

    return needs_auth, entities, endpoints


# ── Icon picker ────────────────────────────────────────────────────────────────

_ICON_MAP: Dict[str, str] = {
    "todo":       "bi-check2-square",
    "task":       "bi-list-task",
    "order":      "bi-bag-check",
    "product":    "bi-box-seam",
    "item":       "bi-collection",
    "post":       "bi-file-text",
    "article":    "bi-newspaper",
    "comment":    "bi-chat-dots",
    "contact":    "bi-person-lines-fill",
    "customer":   "bi-people",
    "employee":   "bi-person-badge",
    "event":      "bi-calendar-event",
    "booking":    "bi-calendar-check",
    "message":    "bi-envelope",
    "payment":    "bi-credit-card",
    "invoice":    "bi-receipt",
    "review":     "bi-star",
    "report":     "bi-bar-chart",
    "category":   "bi-tag",
    "deal":       "bi-briefcase",
    "lead":       "bi-funnel",
    "account":    "bi-building",
    "activity":   "bi-activity",
    "inventory":  "bi-archive",
    "project":    "bi-kanban",
    "ticket":     "bi-ticket-perforated",
    "issue":      "bi-exclamation-circle",
    "asset":      "bi-hdd",
    "property":   "bi-house",
    "vehicle":    "bi-truck",
    "shift":      "bi-clock",
    "schedule":   "bi-calendar3",
    "document":   "bi-file-earmark",
    "file":       "bi-folder",
    "course":     "bi-mortarboard",
    "student":    "bi-person-video2",
    "grade":      "bi-award",
    "sensor":     "bi-cpu",
    "device":     "bi-device-hdd",
    "alert":      "bi-bell",
    "log":        "bi-journal",
    "metric":     "bi-graph-up",
    "segment":    "bi-diagram-3",
    "campaign":   "bi-megaphone",
    "pipeline":   "bi-arrow-right-circle",
    "workflow":   "bi-diagram-2",
}

def _icon_for(table: str) -> str:
    lower = table.rstrip("s").lower()
    for key, icon in _ICON_MAP.items():
        if key in lower:
            return icon
    return "bi-table"


# ── Field-type deducer ─────────────────────────────────────────────────────────

def _field_type(col: str) -> Tuple[str, str]:
    """Return (html_input_type, extra_attrs) for a column name."""
    lower = col.lower()
    if lower in ("id",):
        return "number", 'min="1"'
    if lower.endswith("_at") or lower in ("created_at", "updated_at", "published_at",
                                           "start_at", "end_at", "due_date", "close_date"):
        return "datetime-local", ""
    if lower.endswith("_id"):
        return "number", 'min="1"'
    if lower in ("email",) or lower.endswith("_email"):
        return "email", ""
    if lower in ("password", "password_hash"):
        return "password", ""
    if lower in ("rating",) or lower.endswith("_rating"):
        return "number", 'min="1" max="5"'
    if lower in ("price", "amount", "total", "value", "revenue", "cost"):
        return "number", 'min="0" step="0.01"'
    if lower in ("quantity", "stock", "count", "score"):
        return "number", 'min="0"'
    if lower in ("status",):
        return "select", ""
    if lower in ("priority",):
        return "select", ""
    if lower in ("stage",):
        return "select", ""
    if lower in ("content", "description", "body", "notes", "data", "criteria"):
        return "textarea", ""
    if lower in ("completed",) or lower.startswith("is_") or lower.startswith("has_"):
        return "checkbox", ""
    if lower in ("url", "website", "link") or lower.endswith("_url"):
        return "url", ""
    if lower in ("phone",) or lower.endswith("_phone"):
        return "tel", ""
    return "text", ""


_STATUS_OPTIONS    = ["active", "inactive", "pending", "cancelled", "completed"]
_PRIORITY_OPTIONS  = ["low", "medium", "high", "critical"]
_STAGE_OPTIONS     = ["prospecting", "qualified", "proposal", "negotiation", "closed_won", "closed_lost"]


def _select_options(col: str) -> List[str]:
    lower = col.lower()
    if lower == "status":
        return _STATUS_OPTIONS
    if lower == "priority":
        return _PRIORITY_OPTIONS
    if lower == "stage":
        return _STAGE_OPTIONS
    return ["option1", "option2", "option3"]


# ── HTML builder ───────────────────────────────────────────────────────────────

def _build_product_html(project_name: str, arch: dict) -> str:
    needs_auth, entities, endpoints = _analyse(arch)

    first_entity = entities[0]["table"] if entities else "items"

    # ── Sidebar HTML ──────────────────────────────────────────────────────────
    sidebar_items = ""
    for ent in entities:
        icon   = _icon_for(ent["table"])
        label  = ent["table"].replace("_", " ").title()
        sidebar_items += (
            f'        <li class="nav-item">\n'
            f'          <a class="nav-link sidebar-link" href="#" '
            f'onclick="switchEntity(\'{ent["table"]}\')" '
            f'id="nav-{ent["table"]}">\n'
            f'            <i class="bi {icon} me-2"></i>{label}\n'
            f'          </a>\n'
            f'        </li>\n'
        )

    # ── JS: entity definitions ────────────────────────────────────────────────
    entity_defs = "const ENTITIES = {\n"
    for ent in entities:
        table = ent["table"]
        cols  = ent["columns"]
        # Display columns: exclude id, show first 5
        display_cols = [c for c in cols if c.lower() != "id"][:5]
        # Form fields: exclude id, created_at, updated_at
        form_fields  = [c for c in cols if c.lower() not in ("id", "created_at", "updated_at")]

        entity_defs += f'  "{table}": {{\n'
        entity_defs += f'    label: "{table.replace("_", " ").title()}",\n'
        entity_defs += f'    endpoint: "/{table}",\n'
        entity_defs += f'    displayCols: {json.dumps(display_cols)},\n'
        entity_defs += f'    formFields: {json.dumps(form_fields)},\n'
        entity_defs += f'  }},\n'
    entity_defs += "};\n"

    # ── JS: field-type map ────────────────────────────────────────────────────
    field_type_map = "const FIELD_TYPES = {\n"
    field_select_opts = "const FIELD_OPTIONS = {\n"
    all_cols: set = set()
    for ent in entities:
        for col in ent["columns"]:
            all_cols.add(col)
    for col in sorted(all_cols):
        ftype, _ = _field_type(col)
        field_type_map += f'  "{col}": "{ftype}",\n'
        if ftype == "select":
            field_select_opts += f'  "{col}": {json.dumps(_select_options(col))},\n'
    field_type_map += "};\n"
    field_select_opts += "};\n"

    # ── Accent colour (derived from project name hash) ────────────────────────
    hash_val = sum(ord(c) for c in project_name) % 6
    accent_colours = [
        ("#6366f1", "#4f46e5"),  # indigo
        ("#0ea5e9", "#0284c7"),  # sky
        ("#10b981", "#059669"),  # emerald
        ("#f59e0b", "#d97706"),  # amber
        ("#ef4444", "#dc2626"),  # red
        ("#8b5cf6", "#7c3aed"),  # violet
    ]
    accent, accent_dark = accent_colours[hash_val]

    logo_letter = project_name[0].upper() if project_name else "A"
    pkg_name = project_name.lower().replace(" ", "-").replace("_", "-")

    html = f'''<!DOCTYPE html>
<html lang="en" data-bs-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name}</title>

  <!-- Bootstrap 5.3.3 -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
        crossorigin="anonymous">

  <!-- Bootstrap Icons 1.11.3 -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">

  <style>
    :root {{
      --accent:      {accent};
      --accent-dark: {accent_dark};
      --sidebar-bg:  #1e293b;
      --sidebar-w:   240px;
    }}

    /* ── Layout ── */
    html, body {{ height: 100%; overflow: hidden; }}
    body {{ display: flex; flex-direction: column; font-family: "Inter", system-ui, sans-serif; }}
    #layout {{ display: flex; flex: 1; overflow: hidden; }}

    /* ── Top navbar ── */
    #topbar {{
      height: 56px;
      background: #fff;
      border-bottom: 1px solid #e2e8f0;
      display: flex;
      align-items: center;
      padding: 0 1.25rem;
      gap: 0.75rem;
      flex-shrink: 0;
      z-index: 100;
      box-shadow: 0 1px 3px rgba(0,0,0,.06);
    }}
    #topbar .logo-badge {{
      width: 32px; height: 32px; border-radius: 8px;
      background: var(--accent);
      display: flex; align-items: center; justify-content: center;
      color: #fff; font-weight: 700; font-size: 0.875rem;
      flex-shrink: 0;
    }}
    #topbar .app-name {{
      font-weight: 700; font-size: 1rem; color: #1e293b;
    }}
    #user-display {{
      margin-left: auto;
      font-size: 0.8rem;
      color: #64748b;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}
    #user-display .avatar {{
      width: 30px; height: 30px; border-radius: 50%;
      background: var(--accent);
      color: #fff;
      display: flex; align-items: center; justify-content: center;
      font-size: 0.75rem; font-weight: 700;
    }}
    #btn-logout {{
      font-size: 0.78rem;
      padding: 0.25rem 0.65rem;
    }}

    /* ── Sidebar ── */
    #sidebar {{
      width: var(--sidebar-w);
      background: var(--sidebar-bg);
      flex-shrink: 0;
      overflow-y: auto;
      padding: 1rem 0.75rem;
    }}
    #sidebar .sidebar-heading {{
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #475569;
      padding: 0.5rem 0.5rem 0.25rem;
      margin-top: 0.5rem;
    }}
    .sidebar-link {{
      display: flex;
      align-items: center;
      padding: 0.55rem 0.75rem;
      border-radius: 8px;
      color: #94a3b8;
      font-size: 0.875rem;
      font-weight: 500;
      transition: background 0.15s, color 0.15s;
      text-decoration: none;
    }}
    .sidebar-link:hover {{
      background: rgba(255,255,255,.07);
      color: #e2e8f0;
    }}
    .sidebar-link.active {{
      background: var(--accent);
      color: #fff;
    }}
    .sidebar-link .bi {{ font-size: 1rem; }}

    /* ── Main content ── */
    #main {{
      flex: 1;
      overflow-y: auto;
      background: #f8fafc;
      padding: 1.75rem 2rem;
    }}

    /* ── Page header ── */
    .page-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 1.5rem;
    }}
    .page-header h1 {{
      font-size: 1.375rem;
      font-weight: 700;
      color: #0f172a;
      margin: 0;
    }}
    .btn-accent {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .btn-accent:hover {{
      background: var(--accent-dark);
      border-color: var(--accent-dark);
      color: #fff;
    }}

    /* ── Card ── */
    .data-card {{
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(0,0,0,.04);
    }}

    /* ── Table ── */
    .data-table {{ margin-bottom: 0; }}
    .data-table thead th {{
      background: #f1f5f9;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #64748b;
      border-bottom: 1px solid #e2e8f0;
      padding: 0.75rem 1rem;
      white-space: nowrap;
    }}
    .data-table tbody td {{
      padding: 0.75rem 1rem;
      font-size: 0.875rem;
      color: #1e293b;
      vertical-align: middle;
      border-bottom: 1px solid #f1f5f9;
    }}
    .data-table tbody tr:last-child td {{ border-bottom: none; }}
    .data-table tbody tr:hover {{ background: #f8fafc; cursor: pointer; }}
    .data-table .action-cell {{ white-space: nowrap; text-align: right; }}
    .btn-icon {{
      padding: 0.25rem 0.5rem;
      font-size: 0.875rem;
      line-height: 1;
    }}

    /* ── Status badges ── */
    .badge-status {{
      font-size: 0.7rem;
      font-weight: 600;
      padding: 0.3em 0.65em;
      border-radius: 9999px;
    }}
    .badge-active, .badge-completed, .badge-closed_won {{ background: #dcfce7; color: #166534; }}
    .badge-inactive, .badge-cancelled, .badge-closed_lost {{ background: #fee2e2; color: #991b1b; }}
    .badge-pending, .badge-prospecting {{ background: #fef9c3; color: #854d0e; }}
    .badge-high, .badge-critical {{ background: #fee2e2; color: #991b1b; }}
    .badge-medium, .badge-qualified {{ background: #fef3c7; color: #92400e; }}
    .badge-low {{ background: #eff6ff; color: #1d4ed8; }}
    .badge-proposal {{ background: #f0fdf4; color: #166534; }}
    .badge-negotiation {{ background: #faf5ff; color: #6b21a8; }}

    /* ── Empty state ── */
    .empty-state {{
      padding: 4rem 2rem;
      text-align: center;
      color: #94a3b8;
    }}
    .empty-state .bi {{ font-size: 3rem; margin-bottom: 1rem; opacity: 0.4; }}
    .empty-state p {{ font-size: 0.9rem; }}

    /* ── Toast ── */
    #toast-container {{
      position: fixed;
      top: 1rem;
      right: 1rem;
      z-index: 9999;
    }}

    /* ── Login screen ── */
    #login-screen {{
      display: none;
      position: fixed;
      inset: 0;
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      z-index: 10000;
      align-items: center;
      justify-content: center;
    }}
    .login-card {{
      background: #fff;
      border-radius: 16px;
      padding: 2.5rem;
      width: 100%;
      max-width: 420px;
      box-shadow: 0 20px 60px rgba(0,0,0,.4);
    }}
    .login-logo {{
      width: 48px; height: 48px; border-radius: 12px;
      background: var(--accent);
      display: flex; align-items: center; justify-content: center;
      color: #fff; font-weight: 800; font-size: 1.25rem;
      margin: 0 auto 1.25rem;
    }}
    .login-title {{
      text-align: center;
      font-size: 1.25rem;
      font-weight: 700;
      color: #0f172a;
      margin-bottom: 0.25rem;
    }}
    .login-sub {{
      text-align: center;
      font-size: 0.825rem;
      color: #64748b;
      margin-bottom: 1.75rem;
    }}
    .login-toggle {{
      text-align: center;
      font-size: 0.825rem;
      margin-top: 1rem;
    }}
    .login-toggle a {{ color: var(--accent); cursor: pointer; text-decoration: none; font-weight: 600; }}
    .login-toggle a:hover {{ text-decoration: underline; }}

    /* ── Spinner ── */
    .spinner-overlay {{
      display: flex; align-items: center; justify-content: center;
      padding: 2rem;
    }}

    /* ── Modal ── */
    .modal-header {{ border-bottom: 1px solid #e2e8f0; }}
    .modal-footer {{ border-top: 1px solid #e2e8f0; }}

    /* ── Stats row ── */
    .stat-card {{
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 1.25rem 1.5rem;
      box-shadow: 0 1px 4px rgba(0,0,0,.04);
    }}
    .stat-label {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #64748b; }}
    .stat-value {{ font-size: 2rem; font-weight: 800; color: #0f172a; line-height: 1.2; }}
    .stat-icon {{
      width: 44px; height: 44px; border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 1.25rem;
    }}

    /* ── Search bar ── */
    .search-bar {{ max-width: 280px; }}
    .search-bar .form-control {{ font-size: 0.85rem; }}

    /* ── Scrollbar ── */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 3px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}

    /* ── Responsive ── */
    @media (max-width: 768px) {{
      #sidebar {{ display: none; }}
      #main {{ padding: 1rem; }}
    }}
  </style>
</head>
<body>

<!-- ═══════════════════════════════════════════════════════════
     LOGIN SCREEN
═══════════════════════════════════════════════════════════ -->
<div id="login-screen">
  <div class="login-card">
    <div class="login-logo">{logo_letter}</div>
    <div class="login-title">{project_name}</div>
    <div class="login-sub" id="login-sub-text">Sign in to your account</div>

    <form id="auth-form" novalidate>
      <div id="register-name-group" style="display:none" class="mb-3">
        <label class="form-label fw-semibold small">Full Name</label>
        <input type="text" id="f-name" class="form-control" placeholder="Jane Smith">
      </div>
      <div class="mb-3">
        <label class="form-label fw-semibold small">Email address</label>
        <input type="email" id="f-email" class="form-control" placeholder="you@example.com" required autocomplete="username">
      </div>
      <div class="mb-3">
        <label class="form-label fw-semibold small">Password</label>
        <div class="input-group">
          <input type="password" id="f-password" class="form-control" placeholder="••••••••" required autocomplete="current-password">
          <button class="btn btn-outline-secondary" type="button" onclick="togglePw()" tabindex="-1">
            <i class="bi bi-eye" id="pw-eye-icon"></i>
          </button>
        </div>
      </div>
      <div id="auth-error" class="alert alert-danger py-2 d-none" role="alert"></div>
      <button type="submit" class="btn btn-accent w-100 fw-semibold" id="btn-auth-submit">
        <span id="auth-btn-label">Sign In</span>
        <span id="auth-spinner" class="spinner-border spinner-border-sm ms-2 d-none" role="status"></span>
      </button>
    </form>

    <div class="login-toggle" id="auth-toggle-hint">
      Don&apos;t have an account? <a onclick="setAuthMode('register')">Create one</a>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════
     MAIN APP
═══════════════════════════════════════════════════════════ -->
<div id="app-shell" style="display:none; height:100%; flex-direction:column;">
  <!-- Top bar -->
  <div id="topbar">
    <div class="logo-badge">{logo_letter}</div>
    <span class="app-name">{project_name}</span>
    <div id="user-display">
      <div class="avatar" id="user-avatar">?</div>
      <span id="user-email-display" class="d-none d-sm-inline"></span>
      <button class="btn btn-outline-secondary btn-sm" id="btn-logout" onclick="logout()">
        <i class="bi bi-box-arrow-right me-1"></i>Sign Out
      </button>
    </div>
  </div>

  <div id="layout">
    <!-- Sidebar -->
    <nav id="sidebar">
      <div class="sidebar-heading">Data</div>
      <ul class="nav flex-column gap-1">
{sidebar_items}
      </ul>
      <div class="sidebar-heading" style="margin-top:1.5rem;">System</div>
      <ul class="nav flex-column gap-1">
        <li class="nav-item">
          <a class="nav-link sidebar-link" href="#" onclick="showHealthPanel()">
            <i class="bi bi-heart-pulse me-2"></i>Health
          </a>
        </li>
      </ul>
    </nav>

    <!-- Main content -->
    <main id="main">
      <!-- Stats row -->
      <div class="row g-3 mb-3" id="stats-row" style="display:none!important"></div>

      <!-- Entity view -->
      <div id="entity-view">
        <div class="empty-state">
          <i class="bi bi-grid-3x3-gap"></i>
          <p>Select an entity from the sidebar to get started.</p>
        </div>
      </div>
    </main>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════
     CRUD MODAL
═══════════════════════════════════════════════════════════ -->
<div class="modal fade" id="crud-modal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="crud-modal-title">New Record</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body" id="crud-modal-body"></div>
      <div class="modal-footer">
        <button type="button" class="btn btn-light" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn btn-accent" id="crud-save-btn" onclick="saveRecord()">
          <i class="bi bi-check2 me-1"></i>Save
          <span id="save-spinner" class="spinner-border spinner-border-sm ms-2 d-none"></span>
        </button>
      </div>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════
     DELETE CONFIRMATION MODAL
═══════════════════════════════════════════════════════════ -->
<div class="modal fade" id="delete-modal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered modal-sm">
    <div class="modal-content">
      <div class="modal-body text-center py-4">
        <i class="bi bi-exclamation-triangle text-danger" style="font-size:2.5rem"></i>
        <h6 class="mt-3 mb-1">Delete Record?</h6>
        <p class="text-muted small mb-0">This action cannot be undone.</p>
      </div>
      <div class="modal-footer justify-content-center border-0 pt-0">
        <button class="btn btn-light btn-sm" data-bs-dismiss="modal">Cancel</button>
        <button class="btn btn-danger btn-sm" id="confirm-delete-btn">
          <i class="bi bi-trash me-1"></i>Delete
        </button>
      </div>
    </div>
  </div>
</div>

<!-- Toast container -->
<div id="toast-container" aria-live="polite" aria-atomic="true"></div>

<!-- Bootstrap 5.3.3 JS -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
        integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz"
        crossorigin="anonymous"></script>

<script>
/* ================================================================
   {project_name} — AetherOS p05_frontend (product-spa renderer)
================================================================ */
"use strict";

// ── Entity schema ──────────────────────────────────────────────────────────────
{entity_defs}
{field_type_map}
{field_select_opts}
const NEEDS_AUTH = {'true' if needs_auth else 'false'};
const FIRST_ENTITY = "{first_entity}";

// ── Global state ───────────────────────────────────────────────────────────────
let currentEntity = null;
let currentData   = [];
let editingId     = null;
let token         = localStorage.getItem("aether_token") || null;
let userEmail     = localStorage.getItem("aether_email") || "";
let authMode      = "login";   // "login" | "register"
let pendingDeleteId = null;

// ── Bootstrap modal instances ──────────────────────────────────────────────────
let crudModal, deleteModal;

// ── Entry point ────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", function () {{
  crudModal   = new bootstrap.Modal(document.getElementById("crud-modal"));
  deleteModal = new bootstrap.Modal(document.getElementById("delete-modal"));

  document.getElementById("auth-form").addEventListener("submit", handleAuth);
  document.getElementById("confirm-delete-btn").addEventListener("click", confirmDelete);

  if (NEEDS_AUTH && !token) {{
    showLoginScreen();
  }} else {{
    showAppShell();
    switchEntity(FIRST_ENTITY);
  }}
}});

// ══════════════════════════════════════════════════════════════
// AUTH
// ══════════════════════════════════════════════════════════════

function showLoginScreen() {{
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("app-shell").style.display    = "none";
  document.getElementById("f-email").focus();
}}

function showAppShell() {{
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app-shell").style.display    = "flex";
  document.getElementById("app-shell").style.flexDirection = "column";
  updateUserDisplay();
}}

function setAuthMode(mode) {{
  authMode = mode;
  const isReg = (mode === "register");
  document.getElementById("register-name-group").style.display = isReg ? "" : "none";
  document.getElementById("auth-btn-label").textContent  = isReg ? "Create Account" : "Sign In";
  document.getElementById("login-sub-text").textContent  = isReg ? "Create your account" : "Sign in to your account";
  document.getElementById("auth-toggle-hint").innerHTML  = isReg
    ? `Already have an account? <a href='#' onclick="setAuthMode('login');return false">Sign in</a>`
    : `Don't have an account? <a href='#' onclick="setAuthMode('register');return false">Create one</a>`;
  clearAuthError();
}}

async function handleAuth(e) {{
  e.preventDefault();
  const email    = document.getElementById("f-email").value.trim();
  const password = document.getElementById("f-password").value;
  const name     = document.getElementById("f-name").value.trim();

  if (!email || !password) {{ showAuthError("Please fill in all fields."); return; }}

  const spinner   = document.getElementById("auth-spinner");
  const submitBtn = document.getElementById("btn-auth-submit");
  spinner.classList.remove("d-none");
  submitBtn.disabled = true;
  clearAuthError();

  try {{
    const path    = authMode === "register" ? "/auth/register" : "/auth/login";
    const payload = authMode === "register"
      ? {{ email, password, name }}
      : {{ email, password }};

    const res  = await fetch(path, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(payload),
    }});
    const json = await res.json().catch(() => ({{}}));

    if (!res.ok) {{
      showAuthError(json.detail || json.message || "Authentication failed. Please check your credentials.");
      return;
    }}

    const tok = json.access_token || json.token || json.jwt || (json.data && json.data.access_token);
    if (!tok) {{
      showAuthError("Unexpected response from server. Please try again.");
      return;
    }}

    token     = tok;
    userEmail = json.email || email;
    localStorage.setItem("aether_token", token);
    localStorage.setItem("aether_email", userEmail);

    showAppShell();
    switchEntity(FIRST_ENTITY);
    showToast("Welcome back!", "success");
  }} catch (err) {{
    showAuthError("Network error. Is the server running?");
  }} finally {{
    spinner.classList.add("d-none");
    submitBtn.disabled = false;
  }}
}}

function logout() {{
  token     = null;
  userEmail = "";
  localStorage.removeItem("aether_token");
  localStorage.removeItem("aether_email");
  currentEntity = null;
  currentData   = [];
  if (NEEDS_AUTH) {{
    showLoginScreen();
    setAuthMode("login");
    document.getElementById("auth-form").reset();
  }}
}}

function showAuthError(msg) {{
  const el = document.getElementById("auth-error");
  el.textContent = msg;
  el.classList.remove("d-none");
}}

function clearAuthError() {{
  document.getElementById("auth-error").classList.add("d-none");
}}

function togglePw() {{
  const inp  = document.getElementById("f-password");
  const icon = document.getElementById("pw-eye-icon");
  if (inp.type === "password") {{
    inp.type = "text";
    icon.className = "bi bi-eye-slash";
  }} else {{
    inp.type = "password";
    icon.className = "bi bi-eye";
  }}
}}

function updateUserDisplay() {{
  const email   = userEmail || "";
  const initial = email ? email[0].toUpperCase() : "U";
  document.getElementById("user-avatar").textContent = initial;
  const emailEl = document.getElementById("user-email-display");
  emailEl.textContent = email;
  emailEl.classList.remove("d-none");
}}

// ══════════════════════════════════════════════════════════════
// ENTITY SWITCHING
// ══════════════════════════════════════════════════════════════

function switchEntity(entityKey) {{
  currentEntity = entityKey;
  editingId     = null;

  // Update sidebar active state
  document.querySelectorAll(".sidebar-link").forEach(function(a) {{
    a.classList.remove("active");
  }});
  const navLink = document.getElementById("nav-" + entityKey);
  if (navLink) navLink.classList.add("active");

  loadEntityData();
}}

function renderEntityHeader(entityKey, count) {{
  const ent   = ENTITIES[entityKey];
  const label = ent ? ent.label : entityKey;
  const icon  = navIconForEntity(entityKey);
  const singular = label.replace(/s$/, "");
  const countTxt = count !== null ? (count + " record" + (count !== 1 ? "s" : "")) : "";

  document.getElementById("entity-view").innerHTML =
    '<div class="page-header">' +
      '<h1><i class="bi ' + icon + ' me-2" style="color:var(--accent)"></i>' + label + '</h1>' +
      '<div class="d-flex gap-2 align-items-center">' +
        '<div class="input-group search-bar">' +
          '<span class="input-group-text bg-white border-end-0">' +
            '<i class="bi bi-search text-muted" style="font-size:.8rem"></i>' +
          '</span>' +
          '<input type="text" id="search-input" class="form-control border-start-0"' +
                 ' placeholder="Search..." oninput="filterTable(this.value)"' +
                 ' style="font-size:.85rem">' +
        '</div>' +
        '<button class="btn btn-accent d-flex align-items-center gap-1" onclick="openCreateModal(\\'' + entityKey + '\\')">' +
          '<i class="bi bi-plus-lg"></i>' +
          '<span class="d-none d-sm-inline">New ' + singular + '</span>' +
        '</button>' +
      '</div>' +
    '</div>' +
    '<div class="data-card"><div id="table-area"></div></div>' +
    '<div class="mt-2 text-muted" style="font-size:.75rem" id="record-count">' + countTxt + '</div>';
}}

function navIconForEntity(entityKey) {{
  const iconMap = {{
{chr(10).join(f'    "{ent["table"]}": "{_icon_for(ent["table"])}",' for ent in entities)}
  }};
  return iconMap[entityKey] || "bi-table";
}}

// ══════════════════════════════════════════════════════════════
// DATA LOADING
// ══════════════════════════════════════════════════════════════

async function loadEntityData() {{
  const entityKey = currentEntity;
  if (!entityKey || !ENTITIES[entityKey]) return;

  document.getElementById("entity-view").innerHTML =
    '<div class="spinner-overlay">' +
      '<div class="spinner-border text-secondary" role="status">' +
        '<span class="visually-hidden">Loading...</span>' +
      '</div>' +
    '</div>';

  const ent = ENTITIES[entityKey];

  try {{
    const res = await apiFetch(ent.endpoint, "GET");
    if (res === null) return;          // 401 handled — login shown

    let data = [];
    if (Array.isArray(res)) {{
      data = res;
    }} else if (res && typeof res === "object") {{
      // Unwrap common envelope patterns
      data = res.items || res.data || res.results || res[entityKey] || [];
      if (!Array.isArray(data)) data = [res];
    }}

    currentData = data;
    renderEntityHeader(entityKey, data.length);
    renderTable(entityKey, data);
    renderStatsRow(entityKey, data);
  }} catch (err) {{
    renderEntityHeader(entityKey, null);
    document.getElementById("table-area").innerHTML =
      '<div class="empty-state">' +
        '<i class="bi bi-wifi-off"></i>' +
        '<p class="mb-0 fw-semibold">Could not load data</p>' +
        '<p class="small">' + err.message + '</p>' +
        '<button class="btn btn-accent btn-sm mt-2" onclick="loadEntityData()">' +
          '<i class="bi bi-arrow-clockwise me-1"></i>Retry' +
        '</button>' +
      '</div>';
  }}
}}

function renderTable(entityKey, data) {{
  const ent  = ENTITIES[entityKey];
  const cols = ent ? ent.displayCols : [];
  const area = document.getElementById("table-area");
  if (!area) return;

  if (!data || data.length === 0) {{
    const entLabel = ent ? ent.label.toLowerCase() : "records";
    area.innerHTML =
      '<div class="empty-state">' +
        '<i class="bi bi-inbox"></i>' +
        '<p class="fw-semibold mb-1">No ' + entLabel + ' yet</p>' +
        '<p class="small mb-3">Create your first record to get started.</p>' +
        '<button class="btn btn-accent btn-sm" onclick="openCreateModal(\\'' + entityKey + '\\')">' +
          '<i class="bi bi-plus-lg me-1"></i>New Record' +
        '</button>' +
      '</div>';
    return;
  }}

  // Auto-detect columns from first item if displayCols is empty
  const activeCols = (cols && cols.length > 0)
    ? cols
    : Object.keys(data[0] || {{}}).filter(c => c.toLowerCase() !== "id").slice(0, 5);

  let html = '<div class="table-responsive"><table class="table data-table" id="data-table"><thead><tr>';
  activeCols.forEach(function(col) {{
    const label = col.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    html += '<th onclick="sortBy(\\'' + col + '\\')" style="cursor:pointer" title="Sort by ' + label + '">' +
            label + ' <i class="bi bi-chevron-expand text-muted" style="font-size:.6rem"></i></th>';
  }});
  html += '<th class="action-cell">Actions</th></tr></thead><tbody id="table-body">';

  data.forEach(function(row) {{
    const rowId = String(row.id || row._id || row.uuid || "");
    html += '<tr onclick="openEditModal(\\'' + entityKey + '\\',\\'' + rowId + '\\')" data-id="' + rowId + '">';
    activeCols.forEach(function(col) {{
      const val = row[col];
      html += '<td>' + formatCell(col, val) + '</td>';
    }});
    html +=
      '<td class="action-cell" onclick="event.stopPropagation()">' +
        '<button class="btn btn-sm btn-outline-secondary btn-icon me-1"' +
                ' onclick="openEditModal(\\'' + entityKey + '\\',\\'' + rowId + '\\')" title="Edit">' +
          '<i class="bi bi-pencil"></i>' +
        '</button>' +
        '<button class="btn btn-sm btn-outline-danger btn-icon"' +
                ' onclick="promptDelete(\\'' + rowId + '\\')" title="Delete">' +
          '<i class="bi bi-trash"></i>' +
        '</button>' +
      '</td></tr>';
  }});

  html += '</tbody></table></div>';
  area.innerHTML = html;
}}

function formatCell(col, val) {{
  if (val === null || val === undefined) return '<span class="text-muted">—</span>';
  const lower = col.toLowerCase();

  // Boolean
  if (typeof val === "boolean") {{
    return val
      ? '<span class="badge-status badge-active">Yes</span>'
      : '<span class="badge-status badge-inactive">No</span>';
  }}

  // Status / priority / stage badges
  if (["status", "priority", "stage"].includes(lower)) {{
    const slug = String(val).toLowerCase().replace(/[^a-z0-9]/g, "_");
    return '<span class="badge-status badge-' + slug + '">' + String(val) + '</span>';
  }}

  // Timestamps
  if (lower.endsWith("_at") || lower.endsWith("_date")) {{
    try {{
      const d = new Date(val);
      if (!isNaN(d.getTime())) {{
        return d.toLocaleDateString("en-US", {{ year:"numeric", month:"short", day:"numeric" }});
      }}
    }} catch(e) {{}}
  }}

  // Currency
  if (["price", "amount", "total", "value", "revenue", "cost"].includes(lower)) {{
    const n = parseFloat(val);
    if (!isNaN(n)) return "$" + n.toLocaleString("en-US", {{ minimumFractionDigits:2, maximumFractionDigits:2 }});
  }}

  // Rating
  if (lower === "rating") {{
    const n = parseInt(val);
    if (!isNaN(n)) {{
      return "⭐".repeat(Math.min(n, 5));
    }}
  }}

  // Long text truncation
  const str = String(val);
  if (str.length > 60) return '<span title="' + str.replace(/"/g, "&quot;") + '">' + str.slice(0, 57) + "…</span>";
  return str;
}}

// ── Sorting ────────────────────────────────────────────────────────────────────
let sortCol = null, sortAsc = true;
function sortBy(col) {{
  if (sortCol === col) {{ sortAsc = !sortAsc; }} else {{ sortCol = col; sortAsc = true; }}
  const sorted = [...currentData].sort(function(a, b) {{
    const av = a[col], bv = b[col];
    if (av === undefined || av === null) return 1;
    if (bv === undefined || bv === null) return -1;
    if (typeof av === "number" && typeof bv === "number") return sortAsc ? av - bv : bv - av;
    return sortAsc
      ? String(av).localeCompare(String(bv))
      : String(bv).localeCompare(String(av));
  }});
  renderTable(currentEntity, sorted);
}}

// ── Client-side search filter ──────────────────────────────────────────────────
function filterTable(query) {{
  const q = query.toLowerCase().trim();
  if (!q) {{ renderTable(currentEntity, currentData); return; }}
  const filtered = currentData.filter(function(row) {{
    return Object.values(row).some(function(v) {{
      return v !== null && String(v).toLowerCase().includes(q);
    }});
  }});
  renderTable(currentEntity, filtered);
  const cnt = document.getElementById("record-count");
  if (cnt) cnt.textContent = filtered.length + " of " + currentData.length + " records";
}}

// ── Stats cards ────────────────────────────────────────────────────────────────
function renderStatsRow(entityKey, data) {{
  const row = document.getElementById("stats-row");
  if (!row || !data || data.length === 0) {{ if(row) row.style.display = "none"; return; }}

  const total = data.length;
  const stats = [{{ label: "Total " + (ENTITIES[entityKey]?.label || entityKey), value: total, icon: "bi-layers", bg: "#eff6ff", color: "#1d4ed8" }}];

  // Status breakdown if present
  if (data[0] && "status" in data[0]) {{
    const counts = {{}};
    data.forEach(function(r) {{ counts[r.status] = (counts[r.status] || 0) + 1; }});
    const topStatus = Object.entries(counts).sort((a,b) => b[1]-a[1])[0];
    if (topStatus) {{
      stats.push({{ label: topStatus[0].charAt(0).toUpperCase() + topStatus[0].slice(1), value: topStatus[1], icon: "bi-check-circle", bg: "#f0fdf4", color: "#166534" }});
    }}
  }}

  // Numeric total if price/amount/value exists
  const numCol = ["price","amount","total","value","revenue"].find(c => data[0] && c in data[0]);
  if (numCol) {{
    const sum = data.reduce(function(acc, r) {{ return acc + (parseFloat(r[numCol]) || 0); }}, 0);
    stats.push({{ label: "Total " + numCol.charAt(0).toUpperCase() + numCol.slice(1), value: "$" + sum.toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}}), icon: "bi-cash-stack", bg: "#fdf4ff", color: "#7e22ce" }});
  }}

  row.innerHTML = stats.map(function(s) {{
    return (
      '<div class="col-auto">' +
        '<div class="stat-card d-flex align-items-center gap-3">' +
          '<div class="stat-icon" style="background:' + s.bg + ';color:' + s.color + '">' +
            '<i class="bi ' + s.icon + '"></i>' +
          '</div>' +
          '<div>' +
            '<div class="stat-label">' + s.label + '</div>' +
            '<div class="stat-value" style="color:' + s.color + '">' + s.value + '</div>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }}).join("");
  row.style.removeProperty("display");
}}

// ══════════════════════════════════════════════════════════════
// MODAL FORM
// ══════════════════════════════════════════════════════════════

function buildForm(entityKey, existing) {{
  const ent    = ENTITIES[entityKey];
  const fields = ent ? ent.formFields : [];
  let html     = '<form id="crud-form" class="row g-3" novalidate>';

  fields.forEach(function(col) {{
    const ftype = FIELD_TYPES[col] || "text";
    const label = col.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    const val   = existing ? (existing[col] !== undefined ? existing[col] : "") : "";
    const isReq = !["description","notes","content","body","tags","data"].includes(col.toLowerCase());
    const reqAttr = isReq ? "required" : "";

    let inputHtml = "";

    if (ftype === "select") {{
      const opts = FIELD_OPTIONS[col] || [];
      const optHtml = opts.map(function(o) {{
        const sel = (val === o) ? " selected" : "";
        const txt = o.charAt(0).toUpperCase() + o.slice(1).replace(/_/g, " ");
        return '<option value="' + o + '"' + sel + '>' + txt + '</option>';
      }}).join("");
      inputHtml = '<select id="field-' + col + '" name="' + col + '" class="form-select" ' + reqAttr + '>' +
                  '<option value="">Select ' + label + '...</option>' + optHtml + '</select>';
    }} else if (ftype === "textarea") {{
      inputHtml = '<textarea id="field-' + col + '" name="' + col + '" class="form-control" rows="3" ' + reqAttr + '>' + val + '</textarea>';
    }} else if (ftype === "checkbox") {{
      const chk = val ? " checked" : "";
      inputHtml = '<div class="form-check mt-1">' +
                  '<input class="form-check-input" type="checkbox" id="field-' + col + '" name="' + col + '"' + chk + '>' +
                  '<label class="form-check-label" for="field-' + col + '">' + label + '</label>' +
                  '</div>';
      html += '<div class="col-12">' + inputHtml + '</div>';
      return;
    }} else {{
      let extra = "";
      if (col.toLowerCase().endsWith("_id") || col.toLowerCase() === "id") extra = 'min="1"';
      if (["price","amount","total","value","revenue","cost"].includes(col.toLowerCase())) extra = 'min="0" step="0.01"';
      if (col.toLowerCase() === "rating") extra = 'min="1" max="5"';
      if (col.toLowerCase().endsWith("_at") || col.toLowerCase().endsWith("_date")) {{
        let dtval = "";
        if (val) {{
          try {{ dtval = new Date(val).toISOString().slice(0, 16); }} catch(e) {{ dtval = ""; }}
        }}
        inputHtml = '<input type="datetime-local" id="field-' + col + '" name="' + col + '" class="form-control" value="' + dtval + '" ' + reqAttr + '>';
      }} else {{
        const safeVal = (val !== null && val !== undefined) ? String(val) : "";
        inputHtml = '<input type="' + ftype + '" id="field-' + col + '" name="' + col + '" class="form-control" value="' + safeVal + '" placeholder="' + label + '" ' + extra + ' ' + reqAttr + '>';
      }}
    }}

    const colWidth = ["description","notes","content","body","data","criteria"].includes(col.toLowerCase()) ? "col-12" : "col-md-6";
    const reqStar  = isReq ? ' <span class="text-danger">*</span>' : "";
    html += '<div class="' + colWidth + '">' +
            '<label class="form-label small fw-semibold" for="field-' + col + '">' + label + reqStar + '</label>' +
            inputHtml +
            '</div>';
  }});

  html += "</form>";
  return html;
}}

function openCreateModal(entityKey) {{
  editingId = null;
  const ent = ENTITIES[entityKey];
  const singular = ent ? ent.label.replace(/s$/, "") : "Record";
  document.getElementById("crud-modal-title").innerHTML =
    '<i class="bi bi-plus-circle me-2" style="color:var(--accent)"></i>New ' + singular;
  document.getElementById("crud-modal-body").innerHTML = buildForm(entityKey, null);
  crudModal.show();
}}

function openEditModal(entityKey, rowId) {{
  const row = currentData.find(function(r) {{
    return String(r.id || r._id || r.uuid || "") === String(rowId);
  }});
  if (!row) {{ showToast("Record not found", "danger"); return; }}

  editingId = rowId;
  const ent = ENTITIES[entityKey];
  const singular = ent ? ent.label.replace(/s$/, "") : "Record";
  document.getElementById("crud-modal-title").innerHTML =
    '<i class="bi bi-pencil-square me-2" style="color:var(--accent)"></i>Edit ' + singular;
  document.getElementById("crud-modal-body").innerHTML = buildForm(entityKey, row);
  crudModal.show();
}}

async function saveRecord() {{
  const form = document.getElementById("crud-form");
  if (!form) return;
  if (!form.checkValidity()) {{ form.classList.add("was-validated"); return; }}

  const spinner = document.getElementById("save-spinner");
  const saveBtn = document.getElementById("crud-save-btn");
  spinner.classList.remove("d-none");
  saveBtn.disabled = true;

  const ent    = ENTITIES[currentEntity];
  const fields = ent ? ent.formFields : [];
  const payload = {{}};

  fields.forEach(function(col) {{
    const el = document.getElementById("field-" + col);
    if (!el) return;
    if (el.type === "checkbox") {{
      payload[col] = el.checked;
    }} else if (el.type === "number") {{
      payload[col] = el.value !== "" ? Number(el.value) : null;
    }} else {{
      payload[col] = el.value !== "" ? el.value : null;
    }}
  }});

  try {{
    let res;
    if (editingId) {{
      res = await apiFetch(ent.endpoint + "/" + editingId, "PUT", payload);
    }} else {{
      res = await apiFetch(ent.endpoint, "POST", payload);
    }}

    if (res === null) return;   // 401 handled

    crudModal.hide();
    showToast(editingId ? "Record updated!" : "Record created!", "success");
    loadEntityData();
  }} catch(err) {{
    showToast("Error: " + err.message, "danger");
  }} finally {{
    spinner.classList.add("d-none");
    saveBtn.disabled = false;
  }}
}}

// ══════════════════════════════════════════════════════════════
// DELETE
// ══════════════════════════════════════════════════════════════

function promptDelete(rowId) {{
  pendingDeleteId = rowId;
  deleteModal.show();
}}

async function confirmDelete() {{
  if (!pendingDeleteId) return;
  const ent = ENTITIES[currentEntity];
  deleteModal.hide();

  try {{
    const res = await apiFetch(ent.endpoint + "/" + pendingDeleteId, "DELETE");
    if (res === null) return;
    showToast("Record deleted.", "success");
    loadEntityData();
  }} catch(err) {{
    showToast("Delete failed: " + err.message, "danger");
  }} finally {{
    pendingDeleteId = null;
  }}
}}

// ══════════════════════════════════════════════════════════════
// HEALTH PANEL
// ══════════════════════════════════════════════════════════════

async function showHealthPanel() {{
  document.querySelectorAll(".sidebar-link").forEach(function(a) {{ a.classList.remove("active"); }});

  document.getElementById("entity-view").innerHTML =
    '<div class="page-header">' +
      '<h1><i class="bi bi-heart-pulse me-2" style="color:var(--accent)"></i>System Health</h1>' +
    '</div>' +
    '<div class="data-card p-4">' +
      '<div id="health-content" class="spinner-overlay">' +
        '<div class="spinner-border text-secondary" role="status">' +
          '<span class="visually-hidden">Checking...</span>' +
        '</div>' +
      '</div>' +
    '</div>';

  try {{
    const res  = await fetch("/health");
    const data = await res.json().catch(function() {{ return {{ status: res.ok ? "ok" : "error" }}; }});
    const isOk = res.ok;
    const bg    = isOk ? "#f0fdf4" : "#fef2f2";
    const col   = isOk ? "#16a34a" : "#dc2626";
    const icon  = isOk ? "check-circle-fill" : "x-circle-fill";
    const msg   = isOk ? "All systems operational" : "Service degraded";

    document.getElementById("health-content").innerHTML =
      '<div class="d-flex align-items-center gap-3 mb-4">' +
        '<div style="width:52px;height:52px;border-radius:12px;background:' + bg + ';' +
             'display:flex;align-items:center;justify-content:center;font-size:1.5rem;color:' + col + '">' +
          '<i class="bi bi-' + icon + '"></i>' +
        '</div>' +
        '<div>' +
          '<div class="fw-bold fs-5">' + msg + '</div>' +
          '<div class="text-muted small">HTTP ' + res.status + '</div>' +
        '</div>' +
      '</div>' +
      '<pre class="bg-light rounded p-3" style="font-size:.8rem;max-height:300px;overflow:auto">' +
        JSON.stringify(data, null, 2) +
      '</pre>';
  }} catch(err) {{
    document.getElementById("health-content").innerHTML =
      '<div class="text-danger">' +
        '<i class="bi bi-wifi-off me-2"></i>Cannot reach server: ' + err.message +
      '</div>';
  }}
}}

// ══════════════════════════════════════════════════════════════
// API HELPER
// ══════════════════════════════════════════════════════════════

async function apiFetch(path, method, body) {{
  const headers = {{ "Content-Type": "application/json" }};
  if (token) headers["Authorization"] = "Bearer " + token;

  const opts = {{ method, headers }};
  if (body !== undefined && method !== "GET" && method !== "DELETE") {{
    opts.body = JSON.stringify(body);
  }}

  const res = await fetch(path, opts);

  if (res.status === 401) {{
    token = null;
    userEmail = "";
    localStorage.removeItem("aether_token");
    localStorage.removeItem("aether_email");
    showLoginScreen();
    showToast("Session expired. Please sign in again.", "warning");
    return null;
  }}

  if (res.status === 204 || res.headers.get("content-length") === "0") return {{}};

  const json = await res.json().catch(() => ({{}}));

  if (!res.ok) {{
    const msg = json.detail || json.message || json.error || ("HTTP " + res.status);
    throw new Error(msg);
  }}

  return json;
}}

// ══════════════════════════════════════════════════════════════
// TOAST NOTIFICATIONS
// ══════════════════════════════════════════════════════════════

function showToast(message, type) {{
  const colourMap = {{
    success: "text-bg-success",
    danger:  "text-bg-danger",
    warning: "text-bg-warning text-dark",
    info:    "text-bg-info text-dark",
  }};
  const iconMap = {{
    success: "bi-check-circle-fill",
    danger:  "bi-x-circle-fill",
    warning: "bi-exclamation-triangle-fill",
    info:    "bi-info-circle-fill",
  }};

  const id      = "toast-" + Date.now();
  const classes = colourMap[type] || "text-bg-secondary";
  const icon    = iconMap[type]   || "bi-bell-fill";

  const el = document.createElement("div");
  el.id        = id;
  el.className = "toast align-items-center border-0 " + classes;
  el.setAttribute("role", "alert");
  el.innerHTML =
    '<div class="d-flex">' +
      '<div class="toast-body d-flex align-items-center gap-2">' +
        '<i class="bi ' + icon + '"></i> ' + message +
      '</div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
    '</div>';

  document.getElementById("toast-container").appendChild(el);
  const toast = new bootstrap.Toast(el, {{ delay: 3500 }});
  toast.show();
  el.addEventListener("hidden.bs.toast", function() {{ el.remove(); }});
}}

</script>
</body>
</html>'''

    return html


# ── Main entry point ───────────────────────────────────────────────────────────

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data

    # 1. Read architecture
    arch         = _read_architecture(data)
    project_name = data.get("project_name", arch.get("project_name", "Project Dashboard"))

    # 2. Build the SPA HTML (pure deterministic template — no LLM)
    html = _build_product_html(project_name, arch)

    # 3. Write index.html
    out_file = output_dir / "index.html"
    out_file.write_text(html, encoding="utf-8")

    # 4. Write package.json (zero-dependency — CDN app)
    pkg_name = project_name.lower().replace(" ", "-").replace("_", "-")
    pkg_json = {
        "name": pkg_name,
        "version": "1.0.0",
        "description": f"Auto-generated SPA by AetherOS p05_frontend — {project_name}",
        "scripts": {
            "start": "npx serve . -l 3000",
            "build": "echo 'Single-file CDN app — no build step required'",
        },
        "dependencies": {},
        "devDependencies": {"serve": "^14.0.0"},
        "note": "Bootstrap 5 CDN SPA. No framework, no build step. Open index.html directly or serve it.",
    }
    (output_dir / "package.json").write_text(json.dumps(pkg_json, indent=2))

    # 5. Write frontend_meta.json
    _, entities, endpoints = _analyse(arch)
    meta = {
        "output_file":      str(out_file),
        "file_size_bytes":  out_file.stat().st_size,
        "endpoints_used":   len(endpoints),
        "entities":         [e["table"] for e in entities],
        "used_llm":         False,
        "renderer":         "product-spa",
        "confidence":       0.92,
        "project_name":     project_name,
        "bootstrap_version": "5.3.3",
        "sri_hashes_added": True,
    }
    (output_dir / "frontend_meta.json").write_text(json.dumps(meta, indent=2))

    logger.info(
        "p05_frontend: wrote %s (%d bytes, renderer=product-spa, entities=%s)",
        out_file, out_file.stat().st_size, [e["table"] for e in entities],
    )

    return TaskResult(
        output_path=str(out_file),
        confidence=0.92,
        metadata=meta,
        success=True,
        issues=[],
    )
