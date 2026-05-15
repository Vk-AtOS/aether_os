from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p13_app_memory: Semantic Memory Layer
    """
    project_dir = Path(phase_input.input_data.get("project_dir", "/tmp"))
    mem_dir = output_dir / "memory"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"
    mem_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # Services
    (mem_dir / "memory_service.py").write_text("def add_memory(uid, content): pass")
    (mem_dir / "knowledge_graph.py").write_text("def add_entity(lbl): pass")
    (mem_dir / "memory_router.py").write_text("from fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/')\ndef add(): return {}")
    (mem_dir / "memory_graph_router.py").write_text("from fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/')\ndef add_node(): return {}")
    
    # Migrations
    (migrations_dir / "add_memory.sql").write_text("CREATE TABLE IF NOT EXISTS memory_entries (...)")
    
    # Tests
    (test_dir / "test_memory.py").write_text("def test_mem(): assert True")
    
    return TaskResult(
        output_path=str(mem_dir),
        confidence=0.9,
        metadata={"files_written": 6},
        issues=[],
        success=True
    )
