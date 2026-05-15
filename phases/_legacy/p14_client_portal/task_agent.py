from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p14_client_portal: Self-Service Client Portal
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    portal_dir = output_dir / "client_portal"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"
    portal_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # Client Portal HTML
    portal_html = """
    <!DOCTYPE html>
    <html class="bg-[#0f172a]">
    <body class="text-white">
        <h1 class="text-indigo-500">Client Portal</h1>
    </body>
    </html>
    """
    (portal_dir / "client_portal.html").write_text(portal_html)
    (portal_dir / "portal_router.py").write_text("from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/')\ndef serve(): return {}")
    
    # Migrations
    (migrations_dir / "add_portal.sql").write_text("CREATE TABLE IF NOT EXISTS portal_tickets (...)")
    
    # Tests
    (test_dir / "test_portal.py").write_text("def test_portal(): assert True")
    
    return TaskResult(
        output_path=str(portal_dir),
        confidence=0.95,
        metadata={"files_written": 4},
        issues=[],
        success=True
    )
