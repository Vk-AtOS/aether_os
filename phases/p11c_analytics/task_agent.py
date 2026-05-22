from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p11c_analytics: Event Tracking + Analytics Pipeline
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    analytics_dir = output_dir / "analytics"
    migrations_dir = output_dir / "migrations"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)

    # Analytics service
    (analytics_dir / "analytics_service.py").write_text(
        '''import logging
logger = logging.getLogger(__name__)

def track(event: str, data: dict = None, user_id: int = None):
    """Fire-and-forget event tracking."""
    logger.info("ANALYTICS event=%s user_id=%s data=%s", event, user_id, data or {})
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

    # Analytics dashboard placeholder
    (analytics_dir / "analytics_dashboard.html").write_text(
        "<!doctype html><html><body><h1>Analytics Dashboard</h1>"
        "<p>Connect your analytics_events table to visualise data.</p></body></html>"
    )

    (analytics_dir / "analytics_insights.json").write_text(
        '{"insights": ["Track funnel effectiveness", "Monitor error rates", "Measure p95 latency"]}'
    )

    # DB migration
    (migrations_dir / "add_analytics_events.sql").write_text(
        "CREATE TABLE IF NOT EXISTS analytics_events (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  event VARCHAR(100) NOT NULL,\n"
        "  user_id INTEGER,\n"
        "  data JSONB,\n"
        "  created_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n"
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
                if _end_nl > 0:
                    content = content[:_end_nl + 1] + _middleware_snippet + content[_end_nl + 1:]
                    _main_py.write_text(content)
        except Exception as exc:
            issues.append(f"Analytics middleware injection skipped: {exc}")

    return TaskResult(
        output_path=str(analytics_dir),
        confidence=0.9,
        metadata={"files_written": 6},
        issues=issues,
        success=True
    )
