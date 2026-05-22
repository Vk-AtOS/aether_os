from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p11b_error_tracking: Sentry + Structured Logging
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    error_dir = output_dir / "error_tracking"
    test_dir = output_dir / "tests"
    error_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    # Sentry setup snippet (standalone, not relative import)
    sentry_setup = '''import sentry_sdk

def init_sentry(dsn: str = "", environment: str = "production"):
    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=0.1,
        )
'''
    (error_dir / "sentry_setup.py").write_text(sentry_setup)

    # Structured logging config
    logging_config = '''import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name,
        }
        return json.dumps(log_record)

def setup_logging(level: str = "INFO"):
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=getattr(logging, level, logging.INFO), handlers=[handler])
'''
    (error_dir / "logging_config.py").write_text(logging_config)

    # Error middleware (correct async def)
    error_middleware = '''from fastapi import Request
import logging

logger = logging.getLogger(__name__)

async def error_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error("Unhandled exception: %s %s — %s", request.method, request.url.path, exc)
        raise
'''
    (error_dir / "error_middleware.py").write_text(error_middleware)

    # Env example
    (error_dir / ".env.error_tracking").write_text("SENTRY_DSN=\nLOG_LEVEL=INFO\n")

    # Tests
    (test_dir / "test_error_tracking.py").write_text(
        "def test_logging_config():\n    from error_tracking.logging_config import setup_logging\n    setup_logging()\n"
    )

    # Inject Sentry into main.py (best-effort, inline try/except — no relative import)
    _src_dir = project_dir / "src"
    _main_py = _src_dir / "main.py" if (_src_dir / "main.py").exists() else project_dir / "main.py"
    issues = []
    if _main_py.exists():
        try:
            content = _main_py.read_text()
            if "sentry_sdk" not in content and "app = FastAPI(" in content:
                _sentry_snippet = (
                    "\ntry:\n"
                    "    import sentry_sdk as _sentry\n"
                    "    import os as _os\n"
                    "    _dsn = _os.getenv('SENTRY_DSN', '')\n"
                    "    if _dsn:\n"
                    "        _sentry.init(dsn=_dsn, traces_sample_rate=0.1)\n"
                    "except ImportError:\n"
                    "    pass\n"
                )
                _insert_pos = content.find("app = FastAPI(")
                if _insert_pos >= 0:
                    content = content[:_insert_pos] + _sentry_snippet + content[_insert_pos:]
                    _main_py.write_text(content)
        except Exception as exc:
            issues.append(f"Sentry injection skipped: {exc}")

    return TaskResult(
        output_path=str(error_dir),
        confidence=0.95,
        metadata={"files_written": 5},
        issues=issues,
        success=True
    )
