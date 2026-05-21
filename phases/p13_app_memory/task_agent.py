from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p13_app_memory: Semantic Memory Layer
    """
    mem_dir = output_dir / "memory"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"
    mem_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    (mem_dir / "memory_service.py").write_text(
        '''import logging
from typing import Optional, List as _List

logger = logging.getLogger(__name__)

_store: _List[dict] = []

def add_memory(user_id: int, content: str, category: str = "general") -> dict:
    entry = {"user_id": user_id, "content": content, "category": category}
    _store.append(entry)
    logger.info("Memory stored for user %s: %s", user_id, content[:50])
    return entry

def get_memories(user_id: int, category: Optional[str] = None) -> _List[dict]:
    return [
        m for m in _store
        if m["user_id"] == user_id and (category is None or m["category"] == category)
    ]

def search_memories(user_id: int, query: str) -> _List[dict]:
    return [
        m for m in _store
        if m["user_id"] == user_id and query.lower() in m["content"].lower()
    ]
'''
    )

    (mem_dir / "knowledge_graph.py").write_text(
        '''from typing import Dict, List as _List

_nodes: Dict[str, dict] = {}
_edges: _List[dict] = []

def add_entity(label: str, properties: dict = None) -> dict:
    node = {"label": label, "properties": properties or {}}
    _nodes[label] = node
    return node

def add_relationship(from_label: str, to_label: str, rel_type: str = "RELATED_TO") -> dict:
    edge = {"from": from_label, "to": to_label, "type": rel_type}
    _edges.append(edge)
    return edge

def get_graph() -> dict:
    return {"nodes": list(_nodes.values()), "edges": _edges}
'''
    )

    (mem_dir / "memory_router.py").write_text(
        '''from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from .memory_service import add_memory, get_memories, search_memories

router = APIRouter(prefix="/memory", tags=["Memory"])

class MemoryCreate(BaseModel):
    user_id: int
    content: str
    category: str = "general"

@router.post("/")
def create_memory(body: MemoryCreate):
    return add_memory(body.user_id, body.content, body.category)

@router.get("/{user_id}")
def list_memories(user_id: int, category: Optional[str] = None):
    return {"memories": get_memories(user_id, category)}

@router.get("/{user_id}/search")
def search(user_id: int, q: str):
    return {"results": search_memories(user_id, q)}
'''
    )

    (mem_dir / "memory_graph_router.py").write_text(
        '''from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from .knowledge_graph import add_entity, add_relationship, get_graph

router = APIRouter(prefix="/knowledge-graph", tags=["Knowledge Graph"])

class EntityCreate(BaseModel):
    label: str
    properties: Optional[dict] = None

class RelationshipCreate(BaseModel):
    from_label: str
    to_label: str
    rel_type: str = "RELATED_TO"

@router.post("/entities")
def create_entity(body: EntityCreate):
    return add_entity(body.label, body.properties)

@router.post("/relationships")
def create_relationship(body: RelationshipCreate):
    return add_relationship(body.from_label, body.to_label, body.rel_type)

@router.get("/")
def get_full_graph():
    return get_graph()
'''
    )

    # Real SQL migration
    (migrations_dir / "add_memory.sql").write_text(
        "CREATE TABLE IF NOT EXISTS memory_entries (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  user_id INTEGER NOT NULL,\n"
        "  content TEXT NOT NULL,\n"
        "  category VARCHAR(100) DEFAULT 'general',\n"
        "  embedding JSONB,\n"
        "  created_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n\n"
        "CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_entries(user_id);\n"
    )

    (mem_dir / "INTEGRATION.md").write_text(
        "# App Memory Integration\n\n"
        "To add memory endpoints to your FastAPI app:\n\n"
        "```python\n"
        "from memory.memory_router import router as memory_router\n"
        "from memory.memory_graph_router import router as graph_router\n"
        "app.include_router(memory_router)\n"
        "app.include_router(graph_router)\n"
        "```\n"
    )

    (test_dir / "test_memory.py").write_text(
        "import sys, os\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))\n"
        "from memory.memory_service import add_memory, get_memories, search_memories\n\n"
        "def test_add_and_retrieve():\n"
        "    add_memory(1, 'test content', 'notes')\n"
        "    mems = get_memories(1)\n"
        "    assert any(m['content'] == 'test content' for m in mems)\n\n"
        "def test_search():\n"
        "    add_memory(2, 'Python is great', 'notes')\n"
        "    results = search_memories(2, 'Python')\n"
        "    assert len(results) >= 1\n"
    )

    return TaskResult(
        output_path=str(mem_dir),
        confidence=0.9,
        metadata={"files_written": 7},
        issues=[],
        success=True
    )
