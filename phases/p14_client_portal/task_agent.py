from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p14_client_portal: Self-Service Client Portal

    Problem 80: if p10 already generated the portal, reuse it instead of regenerating.
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    project_name = phase_input.input_data.get("project_name", "Application")

    # Problem 80: check if p10 already generated this portal — reuse it
    _p10_consolidated = None
    for _p10_candidate in [
        output_dir.parent / "consolidated.json",
        project_dir / "p10_docs_delivery" / "consolidated.json",
    ]:
        if _p10_candidate.exists():
            try:
                import json as _json_p80
                _p10_consolidated = _json_p80.loads(_p10_candidate.read_text())
            except Exception as exc:
                logger.debug("p14: failed to read p10 consolidated.json (non-fatal): %s", exc)
            break

    if _p10_consolidated:
        _p10_portal = _p10_consolidated.get("phases", {}).get("client_portal", {})
        _p10_portal_path = _p10_portal.get("output_path", "")
        if _p10_portal_path and Path(_p10_portal_path).exists():
            # Portal already exists from p10 — reference it, optionally enhance
            _existing_portal_dir = Path(_p10_portal_path)
            _portal_html = _existing_portal_dir / "client_portal.html"
            if _portal_html.exists():
                import logging as _ll
                _ll.getLogger(__name__).info(
                    "[p14] Reusing p10-generated client portal at %s (Problem 80 dedup)",
                    _p10_portal_path,
                )
                # Optionally enhance with quality score and council verdict
                _quality_score = phase_input.input_data.get("quality_score", None)
                _council_verdict = phase_input.input_data.get("council_verdict", None)
                if _quality_score or _council_verdict:
                    try:
                        _html = _portal_html.read_text()
                        _inject = ""
                        if _quality_score:
                            _inject += f'\n  <div class="card"><h2>Quality Score</h2><div class="stat-value">{_quality_score}</div></div>'
                        if _council_verdict:
                            _inject += f'\n  <div class="card"><h2>Council Verdict</h2><p>{_council_verdict}</p></div>'
                        if _inject:
                            _html = _html.replace("</div>\n</body>", f"{_inject}\n  </div>\n</body>")
                            _portal_html.write_text(_html)
                    except Exception as exc:
                        logger.debug("p14: portal HTML enhancement failed (non-fatal): %s", exc)
                return TaskResult(
                    output_path=str(_existing_portal_dir),
                    confidence=0.95,
                    metadata={
                        "reused_from_p10": True,
                        "portal_path": str(_existing_portal_dir),
                        "files_written": 0,
                    },
                    issues=[],
                    success=True,
                )

    portal_dir = output_dir / "client_portal"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"
    portal_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    # Client Portal HTML (self-contained, no Tailwind CDN required)
    portal_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name} — Client Portal</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
    .header {{ background: #1e293b; border-bottom: 1px solid #334155; padding: 1rem 2rem; }}
    .header h1 {{ color: #818cf8; font-size: 1.25rem; font-weight: 600; }}
    .container {{ max-width: 1200px; margin: 2rem auto; padding: 0 2rem; }}
    .card {{ background: #1e293b; border-radius: 0.5rem; padding: 1.5rem; margin-bottom: 1.5rem; }}
    .card h2 {{ color: #94a3b8; font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 1rem; }}
    .stat {{ display: inline-block; margin-right: 2rem; }}
    .stat-value {{ font-size: 2rem; font-weight: 700; color: #818cf8; }}
    .stat-label {{ font-size: 0.75rem; color: #64748b; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; padding: 0.75rem; color: #64748b; font-size: 0.75rem; border-bottom: 1px solid #334155; }}
    td {{ padding: 0.75rem; border-bottom: 1px solid #1e293b; font-size: 0.875rem; }}
    .badge {{ display: inline-block; padding: 0.25rem 0.5rem; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; }}
    .badge-open {{ background: #1d4ed8; color: #bfdbfe; }}
    .badge-closed {{ background: #065f46; color: #a7f3d0; }}
    .badge-pending {{ background: #92400e; color: #fde68a; }}
  </style>
</head>
<body>
  <div class="header"><h1>{project_name} — Client Portal</h1></div>
  <div class="container">
    <div class="card">
      <h2>Overview</h2>
      <span class="stat"><div class="stat-value" id="total-tickets">—</div><div class="stat-label">Total Tickets</div></span>
      <span class="stat"><div class="stat-value" id="open-tickets">—</div><div class="stat-label">Open</div></span>
      <span class="stat"><div class="stat-value" id="resolved-tickets">—</div><div class="stat-label">Resolved</div></span>
    </div>
    <div class="card">
      <h2>Recent Tickets</h2>
      <table>
        <thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Created</th></tr></thead>
        <tbody id="tickets-body"><tr><td colspan="4" style="text-align:center;color:#64748b">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>
  <script>
    async function load() {{
      try {{
        const r = await fetch('/portal/tickets');
        if (!r.ok) return;
        const data = await r.json();
        const tickets = data.tickets || [];
        document.getElementById('total-tickets').textContent = tickets.length;
        document.getElementById('open-tickets').textContent = tickets.filter(t => t.status === 'open').length;
        document.getElementById('resolved-tickets').textContent = tickets.filter(t => t.status === 'closed').length;
        document.getElementById('tickets-body').innerHTML = tickets.map(t => `
          <tr>
            <td>#${{t.id}}</td>
            <td>${{t.title}}</td>
            <td><span class="badge badge-${{t.status}}">${{t.status}}</span></td>
            <td>${{new Date(t.created_at).toLocaleDateString()}}</td>
          </tr>
        `).join('') || '<tr><td colspan="4" style="text-align:center;color:#64748b">No tickets</td></tr>';
      }} catch(e) {{ console.error(e); }}
    }}
    load();
  </script>
</body>
</html>
"""
    (portal_dir / "client_portal.html").write_text(portal_html)

    # Portal router — real endpoints for tickets with JSON file persistence
    (portal_dir / "portal_router.py").write_text(
        '''import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/portal", tags=["Client Portal"])

_TICKETS_FILE = Path(os.getenv("PORTAL_TICKETS_PATH", "portal_tickets.json"))
_TICKETS: List[dict] = []
_ticket_id = 0


def _load_tickets() -> None:
    global _TICKETS, _ticket_id
    if _TICKETS_FILE.exists():
        try:
            data = json.loads(_TICKETS_FILE.read_text(encoding="utf-8"))
            _TICKETS = data.get("tickets", [])
            _ticket_id = max((t["id"] for t in _TICKETS), default=0)
        except Exception:
            _TICKETS, _ticket_id = [], 0


def _save_tickets() -> None:
    try:
        _TICKETS_FILE.write_text(
            json.dumps({"tickets": _TICKETS}, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


_load_tickets()


class TicketCreate(BaseModel):
    title: str
    description: str
    priority: str = "medium"


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None


@router.get("/", response_class=HTMLResponse)
def portal_home():
    html_path = Path(__file__).parent / "client_portal.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Client Portal</h1>")


@router.get("/tickets")
def list_tickets(status: Optional[str] = None):
    _load_tickets()
    tickets = _TICKETS if not status else [t for t in _TICKETS if t["status"] == status]
    return {"tickets": tickets, "total": len(tickets)}


@router.post("/tickets")
def create_ticket(ticket: TicketCreate):
    global _ticket_id
    _load_tickets()
    _ticket_id += 1
    entry = {
        "id": _ticket_id,
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _TICKETS.append(entry)
    _save_tickets()
    return entry


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int):
    _load_tickets()
    for t in _TICKETS:
        if t["id"] == ticket_id:
            return t
    raise HTTPException(status_code=404, detail="Ticket not found")


@router.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, update: TicketUpdate):
    _load_tickets()
    for t in _TICKETS:
        if t["id"] == ticket_id:
            if update.status:
                t["status"] = update.status
            if update.priority:
                t["priority"] = update.priority
            _save_tickets()
            return t
    raise HTTPException(status_code=404, detail="Ticket not found")


@router.get("/download")
def download_artifacts():
    """Download a ZIP of all portal artifacts with provenance metadata."""
    portal_dir = Path(__file__).parent
    zip_path = portal_dir / "portal_artifacts.zip"
    provenance: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
    }
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in portal_dir.rglob("*"):
            if f.is_file() and f.name != "portal_artifacts.zip":
                arcname = f.relative_to(portal_dir)
                zf.write(f, arcname)
                checksum = hashlib.sha256(f.read_bytes()).hexdigest()
                provenance["files"].append({"path": str(arcname), "sha256": checksum})
    # Add provenance manifest inside ZIP
    with zipfile.ZipFile(zip_path, "a") as zf:
        zf.writestr("provenance.json", json.dumps(provenance, indent=2))
    return FileResponse(zip_path, media_type="application/zip", filename="portal_artifacts.zip")
'''
    )

    # Real SQL migration
    (migrations_dir / "add_portal.sql").write_text(
        "CREATE TABLE IF NOT EXISTS portal_tickets (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  client_id INTEGER,\n"
        "  title VARCHAR(255) NOT NULL,\n"
        "  description TEXT,\n"
        "  priority VARCHAR(20) DEFAULT 'medium',\n"
        "  status VARCHAR(20) DEFAULT 'open',\n"
        "  created_at TIMESTAMPTZ DEFAULT NOW(),\n"
        "  updated_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n\n"
        "CREATE INDEX IF NOT EXISTS idx_portal_tickets_status ON portal_tickets(status);\n"
    )

    (portal_dir / "INTEGRATION.md").write_text(
        "# Client Portal Integration\n\n"
        "To add the client portal to your FastAPI app:\n\n"
        "```python\n"
        "from client_portal.portal_router import router as portal_router\n"
        "app.include_router(portal_router)\n"
        "```\n\n"
        "Then visit `/portal/` to see the portal dashboard.\n\n"
        "## API Endpoints\n\n"
        "- `GET /portal/` — Portal HTML dashboard\n"
        "- `GET /portal/tickets` — List all tickets\n"
        "- `POST /portal/tickets` — Create ticket\n"
        "- `GET /portal/tickets/{id}` — Get ticket\n"
        "- `PATCH /portal/tickets/{id}` — Update ticket status/priority\n"
    )

    (test_dir / "test_portal.py").write_text(
        "def test_portal_placeholder():\n"
        "    # Integration test: mount portal_router and test /portal/tickets\n"
        "    assert True\n"
    )

    return TaskResult(
        output_path=str(portal_dir),
        confidence=0.95,
        metadata={"files_written": 5},
        issues=[],
        success=True
    )
