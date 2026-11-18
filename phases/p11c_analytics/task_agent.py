from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p11c_analytics: Event Tracking + Analytics Pipeline
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    analytics_dir = output_dir / "analytics"
    migrations_dir = output_dir / "migrations"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)

    # Analytics service with PostHog support
    (analytics_dir / "analytics_service.py").write_text(
        '''import logging
import os

try:
    import posthog as _ph
except ImportError:  # optional: events are only logged without it
    _ph = None

logger = logging.getLogger(__name__)

_POSTHOG_KEY = os.getenv("POSTHOG_API_KEY", "")
_posthog = None


def _get_posthog():
    """Lazy-init PostHog client if API key is set."""
    global _posthog
    if _posthog is not None:
        return _posthog
    if _POSTHOG_KEY:
        if _ph is None:
            logger.warning("posthog package not installed — events logged only")
        else:
            _ph.api_key = _POSTHOG_KEY
            _ph.host = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
            _posthog = _ph
    return _posthog


def track(event: str, data: dict = None, user_id: int = None):
    """Fire-and-forget event tracking. Uses PostHog if POSTHOG_API_KEY is set."""
    props = data or {}
    ph = _get_posthog()
    if ph:
        try:
            distinct_id = str(user_id) if user_id else "anonymous"
            ph.capture(distinct_id, event=event, properties=props)
        except Exception as exc:
            logger.warning("PostHog capture failed: %s", exc)
    logger.info("ANALYTICS event=%s user_id=%s data=%s", event, user_id, props)
'''
    )

    # Analytics events constants
    (analytics_dir / "analytics_events.py").write_text(
        '''PAGE_VIEW = "page_view"
BUTTON_CLICK = "button_click"
FORM_SUBMIT = "form_submit"
ERROR = "error"
USER_SIGNUP = "user_signup"
USER_LOGIN = "user_login"
'''
    )

    # Analytics middleware (async def — correct)
    (analytics_dir / "analytics_middleware.py").write_text(
        '''from fastapi import Request
import time
import logging

logger = logging.getLogger(__name__)

async def analytics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "REQUEST method=%s path=%s status=%s duration_ms=%d",
        request.method, request.url.path, response.status_code, duration_ms,
    )
    return response
'''
    )

    # Analytics dashboard — real-time event viewer backed by /analytics/events
    (analytics_dir / "analytics_dashboard.html").write_text(
        '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Analytics Dashboard</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,sans-serif;background:#0f0f17;color:#e2e8f0;min-height:100vh;padding:24px}
  h1{font-size:1.5rem;font-weight:700;color:#fff;margin-bottom:24px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:32px}
  .card{background:#1a1a2e;border:1px solid #2d2d4e;border-radius:12px;padding:20px}
  .card h2{font-size:.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}
  .card p{font-size:2rem;font-weight:700;color:#7c3aed}
  .table-wrap{background:#1a1a2e;border:1px solid #2d2d4e;border-radius:12px;overflow:hidden}
  table{width:100%;border-collapse:collapse}
  th{background:#111128;color:#94a3b8;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:12px 16px;text-align:left}
  td{padding:12px 16px;border-top:1px solid #2d2d4e;font-size:.875rem;color:#cbd5e1}
  tr:hover td{background:#1e1e35}
  .badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.7rem;font-weight:600;background:#7c3aed22;color:#a78bfa}
  #status{font-size:.8rem;color:#64748b;margin-bottom:16px}
</style>
</head>
<body>
<h1>Analytics Dashboard</h1>
<p id="status">Loading…</p>
<div class="cards">
  <div class="card"><h2>Total Events (24h)</h2><p id="total">—</p></div>
  <div class="card"><h2>Unique Users (24h)</h2><p id="users">—</p></div>
  <div class="card"><h2>Avg Latency (ms)</h2><p id="latency">—</p></div>
  <div class="card"><h2>Error Rate</h2><p id="errors">—</p></div>
</div>
<div class="table-wrap">
  <table>
    <thead><tr><th>Time</th><th>Event</th><th>User</th><th>Path</th><th>Latency</th></tr></thead>
    <tbody id="events"><tr><td colspan="5" style="text-align:center;color:#64748b;padding:32px">Loading events…</td></tr></tbody>
  </table>
</div>
<script>
const API = window.location.origin;
async function load() {
  try {
    const token = localStorage.getItem("access_token") || "";
    const r = await fetch(API + "/api/analytics/events?limit=50", {headers: {Authorization: "Bearer " + token}});
    if (r.status === 401 || r.status === 403) throw new Error("sign in as an admin to see analytics");
    if (!r.ok) throw new Error(r.statusText);
    const data = await r.json();
    const events = data.events || data || [];
    document.getElementById("total").textContent = data.total_24h ?? events.length;
    document.getElementById("users").textContent = data.unique_users_24h ?? "—";
    document.getElementById("latency").textContent = data.avg_latency_ms ? data.avg_latency_ms.toFixed(0) : "—";
    document.getElementById("errors").textContent = data.error_rate != null ? (data.error_rate * 100).toFixed(1) + "%" : "—";
    const tbody = document.getElementById("events");
    if (!events.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#64748b;padding:32px">No events recorded yet</td></tr>';
    } else {
      tbody.innerHTML = events.map(e => {
        const t = new Date(e.created_at || e.ts).toLocaleTimeString();
        return `<tr><td>${t}</td><td><span class="badge">${e.event||e.name||"—"}</span></td><td>${e.user_id||"anon"}</td><td>${(e.data?.path||e.path||"—")}</td><td>${e.data?.duration_ms ?? e.latency_ms ?? "—"}ms</td></tr>`;
      }).join("");
    }
    document.getElementById("status").textContent = "Last updated: " + new Date().toLocaleTimeString();
  } catch(err) {
    document.getElementById("status").textContent = "Could not load events: " + err.message;
  }
}
load();
setInterval(load, 30000);
</script>
</body>
</html>'''
    )

    (analytics_dir / "analytics_insights.json").write_text(
        '{"insights": ["Track funnel effectiveness", "Monitor error rates", "Measure p95 latency"]}'
    )

    # Analytics API router — serves /analytics/events for the dashboard
    (analytics_dir / "analytics_router.py").write_text(
        '''"""Analytics API — event ingestion and query endpoints."""
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

try:
    import posthog as _ph
except ImportError:  # optional: events are only stored without it
    _ph = None
# The generated backend's own modules. main.py puts src/ on sys.path and imports them by their plain
# names, so those are tried first: importing "src.database" as well would build a second engine.
try:  # the session factory (get_db is a FastAPI dependency, not a context manager)
    from database import AsyncSessionLocal
except ImportError:
    from src.database import AsyncSessionLocal
try:
    from auth import get_current_user, require_admin
except ImportError:
    from src.auth import get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])
_MAX_DATA_BYTES = 8192


@router.post("/track")
async def track_event(body: Dict[str, Any], user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """Ingest a single analytics event for the signed-in user."""
    event = str(body.get("event") or "")[:100]
    # Who sent it comes from the token: a user_id in the body would let anyone write events as someone else.
    user_id = str(user.get("id") or "")
    org_id = str(user.get("org_id") or "")
    data = body.get("data") or {}
    if not event:
        return {"status": "ignored", "reason": "no event name"}
    if not isinstance(data, dict) or len(__import__("json").dumps(data)) > _MAX_DATA_BYTES:
        raise HTTPException(status_code=413, detail="event data must be a JSON object of at most 8 KB")
    try:
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            await db.execute(
                # CAST(...): the ":d::jsonb" form is not a bind parameter for SQLAlchemy, so no event was ever stored
                text("INSERT INTO analytics_events (event, user_id, org_id, data) VALUES (:e, :u, :o, CAST(:d AS jsonb))"),
                {"e": event, "u": user_id, "o": org_id, "d": __import__("json").dumps(data)},
            )
            await db.commit()
    except Exception as exc:
        logger.warning("Analytics DB write failed: %s", exc)
    # Also forward to PostHog if configured
    posthog_key = os.getenv("POSTHOG_API_KEY", "")
    if posthog_key and _ph is not None:
        try:
            _ph.api_key = posthog_key
            _ph.capture(str(user_id or "anon"), event=event, properties=data)
        except Exception as e:
            logger.warning("p11c_analytics: PostHog capture failed (non-critical): %s", e)
    return {"status": "ok"}


@router.get("/events")
async def list_events(
    limit: int = Query(50, ge=1, le=500),
    event: Optional[str] = Query(None),
    admin: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Recent events and summary statistics of the admin's own organisation (admin only)."""
    org_id = str(admin.get("org_id") or "")
    import json as _json
    try:
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            # Recent events
            where = "WHERE org_id = :o" + (" AND event = :e" if event else "")
            params: Dict[str, Any] = {"limit": limit, "o": org_id}
            if event:
                params["e"] = event
            rows = (await db.execute(
                text(f"SELECT id, event, user_id, data, created_at FROM analytics_events {where} ORDER BY created_at DESC LIMIT :limit"),
                params,
            )).fetchall()

            # 24h summary
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)  # a datetime: asyncpg rejects an ISO string
            stats = (await db.execute(
                text("SELECT COUNT(*) as total, COUNT(DISTINCT user_id) as users, "
                     "AVG((data->>'duration_ms')::float) as avg_ms, "
                     "SUM(CASE WHEN event = \'error\' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as err_rate "
                     "FROM analytics_events WHERE org_id = :o AND created_at > :c"),
                {"c": cutoff, "o": org_id},
            )).fetchone()

        events_out = [
            {
                "id": r[0],
                "event": r[1],
                "user_id": r[2],
                "data": r[3] if isinstance(r[3], dict) else (_json.loads(r[3]) if r[3] else {}),
                "created_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ]
        return {
            "events": events_out,
            "total_24h": int(stats[0] or 0),
            "unique_users_24h": int(stats[1] or 0),
            "avg_latency_ms": round(float(stats[2]), 1) if stats[2] else None,
            "error_rate": round(float(stats[3]), 4) if stats[3] else 0.0,
        }
    except Exception as exc:
        logger.error("Analytics query failed: %s", exc)
        return {"events": [], "total_24h": 0, "unique_users_24h": 0, "avg_latency_ms": None, "error_rate": 0.0}
'''
    )

    # DB migration
    (migrations_dir / "add_analytics_events.sql").write_text(
        "CREATE TABLE IF NOT EXISTS analytics_events (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  event VARCHAR(100) NOT NULL,\n"
        "  user_id VARCHAR(64),\n"
        "  org_id VARCHAR(64) NOT NULL DEFAULT '',\n"
        "  data JSONB,\n"
        "  created_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n"
        "ALTER TABLE analytics_events ADD COLUMN IF NOT EXISTS org_id VARCHAR(64) NOT NULL DEFAULT '';\n"
        "ALTER TABLE analytics_events ALTER COLUMN user_id TYPE VARCHAR(64);\n"
        "CREATE INDEX IF NOT EXISTS ix_analytics_events_org_created ON analytics_events (org_id, created_at DESC);\n"
    )

    # Inject request-timing middleware into main.py (best-effort, no relative import)
    _src_dir = project_dir / "src"
    _main_py = _src_dir / "main.py" if (_src_dir / "main.py").exists() else project_dir / "main.py"
    issues = []
    if _main_py.exists():
        try:
            content = _main_py.read_text()
            if "analytics_middleware" not in content and "app = FastAPI(" in content:
                _middleware_snippet = (
                    "\ntry:\n"
                    "    import time as _time, logging as _logging\n"
                    "    _analytics_logger = _logging.getLogger('analytics')\n"
                    "    @app.middleware('http')\n"
                    "    async def _analytics_mw(request, call_next):\n"
                    "        _t0 = _time.perf_counter()\n"
                    "        _resp = await call_next(request)\n"
                    "        _ms = int((_time.perf_counter() - _t0) * 1000)\n"
                    "        _analytics_logger.info('%s %s %s %dms', request.method, request.url.path, _resp.status_code, _ms)\n"
                    "        return _resp\n"
                    "except Exception:\n"
                    "    pass\n"
                )
                # Find the closing ) of app = FastAPI(...) using bracket depth counting
                _start = content.find("app = FastAPI(")
                _depth, _end_pos = 0, _start
                for _i, _ch in enumerate(content[_start:], _start):
                    if _ch == "(":
                        _depth += 1
                    elif _ch == ")":
                        _depth -= 1
                        if _depth == 0:
                            _end_pos = _i
                            break
                _end_nl = content.find("\n", _end_pos)
                if _end_nl >= 0:
                    content = content[:_end_nl + 1] + _middleware_snippet + content[_end_nl + 1:]
                    _main_py.write_text(content)
        except Exception as exc:
            logger.warning("p11c_analytics: Analytics middleware injection failed: %s", exc)
            issues.append(f"Analytics middleware injection skipped: {exc}")

    return TaskResult(
        output_path=str(analytics_dir),
        confidence=0.9,
        metadata={"files_written": 7},
        issues=issues,
        success=True
    )
