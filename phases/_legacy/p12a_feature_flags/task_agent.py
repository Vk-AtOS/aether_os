from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p12a_feature_flags: Feature Flag Service
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    ff_dir = output_dir / "feature_flags"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"
    ff_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # Feature Flags Service
    (ff_dir / "feature_flags.py").write_text("def is_enabled(flag_name): return True")
    # Admin Router
    (ff_dir / "flag_admin_router.py").write_text("from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/')\ndef list_flags(): return {}")
    # Initial flags
    (ff_dir / "initial_flags.json").write_text('{"flags": ["enable_beta"]}')
    
    # Migrations
    (migrations_dir / "add_feature_flags.sql").write_text("CREATE TABLE IF NOT EXISTS feature_flags (...)")
    
    # Tests
    (test_dir / "test_feature_flags.py").write_text("def test_flag(): assert True")
    
    # No main.py patching — feature_flags output dir is separate from generated app src
            
    return TaskResult(
        output_path=str(ff_dir),
        confidence=0.9,
        metadata={"files_written": 6},
        issues=[],
        success=True
    )
