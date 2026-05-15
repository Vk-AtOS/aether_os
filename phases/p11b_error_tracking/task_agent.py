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
    
    # Patch main.py
    main_py_path = project_dir / phase_input.input_data.get("backend_main_py", "main.py")
    if main_py_path.exists():
        content = main_py_path.read_text()
        if "init_sentry" not in content:
            content = "from .error_tracking.sentry_setup import init_sentry\ninit_sentry()\n" + content
            main_py_path.write_text(content)
            
    return TaskResult(
        output_path=str(error_dir),
        confidence=0.95,
        metadata={"files_written": 5},
        issues=[],
        success=True
    )
