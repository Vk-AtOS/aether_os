"""
STUB PHASE: p12a_feature_flags generates a JSON-file-backed feature flag system.
This is NOT production-grade. For production, use GrowthBook, LaunchDarkly, or Unleash.
The generated feature_flags.json provides local development toggles only.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p12a_feature_flags: Feature Flag Service (JSON-file-backed stub).
    """
    logger.warning(
        "p12a_feature_flags: generating JSON stub (not production-grade). "
        "For production feature flags use GrowthBook, LaunchDarkly, or Unleash."
    )
    ff_dir = output_dir / "feature_flags"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"
    ff_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    (ff_dir / "__init__.py").write_text("")

    # Feature flag service (standalone, JSON-file-backed persistence with file locking)
    (ff_dir / "feature_flags.py").write_text(
        '''import json
import os
import sys
from pathlib import Path

_FLAGS_FILE = Path(os.getenv("FEATURE_FLAGS_PATH", "feature_flags.json"))
_FLAGS: dict = {}


def _load() -> None:
    """Load flags from JSON file into in-memory dict (with file locking)."""
    global _FLAGS
    if not _FLAGS_FILE.exists():
        return
    try:
        if sys.platform != "win32":
            import fcntl
            with open(_FLAGS_FILE, "r", encoding="utf-8") as _f:
                fcntl.flock(_f, fcntl.LOCK_SH)
                try:
                    _FLAGS = json.load(_f)
                finally:
                    fcntl.flock(_f, fcntl.LOCK_UN)
        else:
            _FLAGS = json.loads(_FLAGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        _FLAGS = {}


def _save() -> None:
    """Persist in-memory flags to JSON file (with exclusive file locking)."""
    try:
        if sys.platform != "win32":
            import fcntl
            _FLAGS_FILE.touch(exist_ok=True)
            with open(_FLAGS_FILE, "r+", encoding="utf-8") as _f:
                fcntl.flock(_f, fcntl.LOCK_EX)
                try:
                    _f.seek(0)
                    _f.write(json.dumps(_FLAGS, indent=2))
                    _f.truncate()
                finally:
                    fcntl.flock(_f, fcntl.LOCK_UN)
        else:
            _FLAGS_FILE.write_text(json.dumps(_FLAGS, indent=2), encoding="utf-8")
    except Exception:
        pass


# Load on import
_load()


def enable(flag: str) -> None:
    _load()
    _FLAGS[flag] = True
    _save()


def disable(flag: str) -> None:
    _load()
    _FLAGS[flag] = False
    _save()


def is_enabled(flag: str) -> bool:
    """Check if a feature flag is enabled. Reads from env var FEATURE_<FLAG_UPPER> first."""
    env_key = f"FEATURE_{flag.upper()}"
    env_val = os.getenv(env_key)
    if env_val is not None:
        return env_val.lower() in ("1", "true", "yes")
    _load()  # refresh from disk in case another process updated it
    return _FLAGS.get(flag, False)
'''
    )

    # Admin router (standalone — not injected into main.py)
    (ff_dir / "flag_admin_router.py").write_text(
        '''from fastapi import APIRouter, HTTPException
from .feature_flags import _FLAGS, enable, disable, is_enabled

router = APIRouter(prefix="/flags", tags=["Feature Flags"])

@router.get("/")
def list_flags():
    return {"flags": _FLAGS}

@router.post("/{flag}/enable")
def enable_flag(flag: str):
    enable(flag)
    return {"flag": flag, "enabled": True}

@router.post("/{flag}/disable")
def disable_flag(flag: str):
    disable(flag)
    return {"flag": flag, "enabled": False}

@router.get("/{flag}")
def get_flag(flag: str):
    return {"flag": flag, "enabled": is_enabled(flag)}
'''
    )

    (ff_dir / "initial_flags.json").write_text(
        '{"enable_beta": false, "dark_mode": true, "new_dashboard": false}\n'
    )

    # Migration with real SQL
    (migrations_dir / "add_feature_flags.sql").write_text(
        "CREATE TABLE IF NOT EXISTS feature_flags (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  name VARCHAR(100) UNIQUE NOT NULL,\n"
        "  enabled BOOLEAN NOT NULL DEFAULT FALSE,\n"
        "  description TEXT,\n"
        "  created_at TIMESTAMPTZ DEFAULT NOW(),\n"
        "  updated_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n"
    )

    # Integration instructions (README for the consumer)
    (ff_dir / "INTEGRATION.md").write_text(
        "# Feature Flags Integration\n\n"
        "To add feature flags to your FastAPI app:\n\n"
        "```python\n"
        "from feature_flags.flag_admin_router import router as flags_router\n"
        "app.include_router(flags_router)\n"
        "```\n\n"
        "Or check flags inline:\n\n"
        "```python\n"
        "from feature_flags.feature_flags import is_enabled\n"
        "if is_enabled('new_dashboard'):\n"
        "    ...\n"
        "```\n\n"
        "Set env vars to override: `FEATURE_NEW_DASHBOARD=true`\n"
    )

    (test_dir / "test_feature_flags.py").write_text(
        "import sys, os\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))\n"
        "from feature_flags.feature_flags import enable, disable, is_enabled\n\n"
        "def test_flag_disabled_by_default():\n"
        "    assert not is_enabled('nonexistent_flag')\n\n"
        "def test_enable_disable():\n"
        "    enable('test_flag')\n"
        "    assert is_enabled('test_flag')\n"
        "    disable('test_flag')\n"
        "    assert not is_enabled('test_flag')\n\n"
        "def test_env_override(monkeypatch):\n"
        "    monkeypatch.setenv('FEATURE_MY_FLAG', 'true')\n"
        "    assert is_enabled('my_flag')\n"
    )

    return TaskResult(
        output_path=str(ff_dir),
        confidence=0.9,
        metadata={"files_written": 6},
        issues=[],
        success=True
    )
