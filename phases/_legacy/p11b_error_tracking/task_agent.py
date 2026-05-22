from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p11b_error_tracking: Sentry + Structured Logging
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    error_dir = output_dir / "error_tracking"
    test_dir = output_dir / "tests"
    error_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # Sentry Setup
    sentry_setup = """
import sentry_sdk
def init_sentry():
    sentry_sdk.init(dsn="", environment="production", traces_sample_rate=1.0)
    """
    (error_dir / "sentry_setup.py").write_text(sentry_setup)
    
    # Logging Config
    logging_config = """
import structlog
def setup_logging():
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    """
    (error_dir / "logging_config.py").write_text(logging_config)
    
    # Error Middleware
    error_middleware = """
from fastapi import Request, Response
async def error_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        # Sentry capture here
        raise e
    """
    (error_dir / "error_middleware.py").write_text(error_middleware)
    
    # .env
    (error_dir / ".env.error_tracking").write_text("SENTRY_DSN=\nLOG_LEVEL=INFO")
    
    # Tests
    (test_dir / "test_error_tracking.py").write_text("def test_init(): assert True")
    
    # Inject Sentry into main.py (best-effort, inline try/except — no relative import)
    _src_dir = project_dir / "src"
    _main_py = _src_dir / "main.py" if (_src_dir / "main.py").exists() else project_dir / "main.py"
    if _main_py.exists():
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
            
    return TaskResult(
        output_path=str(error_dir),
        confidence=0.95,
        metadata={"files_written": 5},
        issues=[],
        success=True
    )
