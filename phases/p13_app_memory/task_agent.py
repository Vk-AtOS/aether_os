"""
p13_app_memory generates a semantic memory service with tiered backend selection:
  1. ChromaDB  — if chromadb package is importable (best semantic similarity)
  2. pgvector  — if PGVECTOR_ENABLED=true and psycopg2 is available
  3. JSON file — fallback for zero-dependency local development

All three backends expose the same interface:
  add_memory(user_id, content, category)
  get_memories(user_id, category=None)
  search_memories(user_id, query)
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Generates a full semantic memory service for the built app.

    Backend: ChromaDB (best; if importable) → pgvector (if PGVECTOR_ENABLED=true)
    → JSON file (zero-dependency fallback). All three expose the same interface:
    add_memory(), get_memories(), search_memories().
    """
    logger.info(
        "p13_app_memory: generating memory service with ChromaDB → pgvector → JSON fallback"
    )
    mem_dir = output_dir / "memory"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"
    mem_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    (mem_dir / "__init__.py").write_text("")

    (mem_dir / "memory_service.py").write_text(
        '''"""
Semantic memory service with tiered backend selection:
  1. ChromaDB  — best semantic similarity; used if chromadb is importable
  2. pgvector  — SQL-native embeddings; used if PGVECTOR_ENABLED=true
  3. JSON file — zero-dependency fallback for local development

All backends expose the same interface:
  add_memory(user_id, content, category) -> dict
  get_memories(user_id, category=None)   -> list[dict]
  search_memories(user_id, query, limit) -> list[dict]
"""
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, List as _List

logger = logging.getLogger(__name__)

_COLLECTION_NAME = os.getenv("MEMORY_COLLECTION", "app_memory")
_STORE_FILE = Path(os.getenv("MEMORY_STORE_PATH", "memory_store.json"))
_PGVECTOR_ENABLED = os.getenv("PGVECTOR_ENABLED", "false").lower() == "true"
_DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Backend selection ──────────────────────────────────────────────────────

def _try_chromadb():
    """Return a ChromaDB collection or None if chromadb is unavailable."""
    try:
        import chromadb  # noqa: PLC0415
        _persist = os.getenv("CHROMA_PERSIST_DIR", ".chroma")
        _client = chromadb.PersistentClient(path=_persist)
        return _client.get_or_create_collection(_COLLECTION_NAME)
    except ImportError:
        return None
    except Exception as _exc:
        logger.warning("ChromaDB init failed, trying next backend: %s", _exc)
        return None


def _try_pgvector():
    """Return a psycopg2 connection or None if pgvector is unavailable."""
    if not _PGVECTOR_ENABLED or not _DATABASE_URL:
        return None
    try:
        import psycopg2  # noqa: PLC0415
        conn = psycopg2.connect(_DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS memory_entries ("
                "  id SERIAL PRIMARY KEY,"
                "  user_id VARCHAR(64) NOT NULL,"
                "  content TEXT NOT NULL,"
                "  category VARCHAR(100) DEFAULT \'general\',"
                "  embedding vector(1536),"
                "  created_at TIMESTAMPTZ DEFAULT NOW()"
                ")"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_user ON memory_entries(user_id)"
            )
        conn.commit()
        return conn
    except ImportError:
        return None
    except Exception as _exc:
        logger.warning("pgvector init failed, falling back to JSON: %s", _exc)
        return None


_chroma = _try_chromadb()
_pg_conn = None if _chroma else _try_pgvector()

if _chroma is not None:
    _backend_type = "chromadb"
elif _pg_conn is not None:
    _backend_type = "pgvector"
else:
    _backend_type = "json"

logger.info("Memory backend: %s", _backend_type)

# ── ChromaDB backend ───────────────────────────────────────────────────────

def _chroma_add(user_id: str, content: str, category: str) -> dict:
    # sha256, not hash(): the builtin is randomised per process, so the same memory got a new id
    # (no dedup) after every restart.
    _id = f"{user_id}_{hashlib.sha256(content.encode()).hexdigest()[:24]}"
    _chroma.upsert(
        ids=[_id],
        documents=[content],
        metadatas=[{"user_id": user_id, "category": category}],
    )
    return {"user_id": user_id, "content": content, "category": category, "id": _id}


def _chroma_get(user_id: str, category: Optional[str]) -> _List[dict]:
    _where = {"user_id": user_id}
    if category:
        _where["category"] = category
    try:
        res = _chroma.get(where=_where, include=["documents", "metadatas"])
        return [
            {"user_id": user_id, "content": doc, "category": meta.get("category", "general")}
            for doc, meta in zip(res["documents"], res["metadatas"])
        ]
    except Exception as _exc:
        logger.warning("ChromaDB get failed: %s", _exc)
        return []


def _chroma_search(user_id: str, query: str, limit: int) -> _List[dict]:
    try:
        res = _chroma.query(
            query_texts=[query],
            n_results=limit,
            where={"user_id": user_id},
            include=["documents", "metadatas"],
        )
        return [
            {"user_id": user_id, "content": doc, "category": meta.get("category", "general")}
            for doc, meta in zip(res["documents"][0], res["metadatas"][0])
        ]
    except Exception as _exc:
        logger.warning("ChromaDB search failed: %s", _exc)
        return []

# ── pgvector backend ───────────────────────────────────────────────────────

def _pg_add(user_id: str, content: str, category: str) -> dict:
    try:
        with _pg_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO memory_entries (user_id, content, category) VALUES (%s, %s, %s) RETURNING id",
                (user_id, content, category),
            )
            row_id = cur.fetchone()[0]
        _pg_conn.commit()
        return {"id": row_id, "user_id": user_id, "content": content, "category": category}
    except Exception as _exc:
        logger.warning("pgvector add failed: %s", _exc)
        _pg_conn.rollback()
        return {"user_id": user_id, "content": content, "category": category}


def _pg_get(user_id: str, category: Optional[str]) -> _List[dict]:
    try:
        with _pg_conn.cursor() as cur:
            if category:
                cur.execute(
                    "SELECT user_id, content, category FROM memory_entries WHERE user_id=%s AND category=%s ORDER BY created_at DESC",
                    (user_id, category),
                )
            else:
                cur.execute(
                    "SELECT user_id, content, category FROM memory_entries WHERE user_id=%s ORDER BY created_at DESC",
                    (user_id,),
                )
            rows = cur.fetchall()
        return [{"user_id": r[0], "content": r[1], "category": r[2]} for r in rows]
    except Exception as _exc:
        logger.warning("pgvector get failed: %s", _exc)
        return []


def _pg_search(user_id: str, query: str, limit: int) -> _List[dict]:
    try:
        with _pg_conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, content, category FROM memory_entries "
                "WHERE user_id=%s AND content ILIKE %s ORDER BY created_at DESC LIMIT %s",
                (user_id, f"%{query}%", limit),
            )
            rows = cur.fetchall()
        return [{"user_id": r[0], "content": r[1], "category": r[2]} for r in rows]
    except Exception as _exc:
        logger.warning("pgvector search failed: %s", _exc)
        return []

# ── JSON file backend ──────────────────────────────────────────────────────

_store: _List[dict] = []


def _json_load() -> None:
    global _store
    if not _STORE_FILE.exists():
        return
    try:
        if sys.platform != "win32":
            import fcntl
            with open(_STORE_FILE, "r", encoding="utf-8") as _f:
                fcntl.flock(_f, fcntl.LOCK_SH)
                try:
                    _store = json.load(_f)
                finally:
                    fcntl.flock(_f, fcntl.LOCK_UN)
        else:
            _store = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except Exception as _exc:
        logger.warning("Memory JSON load failed, starting empty: %s", _exc)
        _store = []


def _json_save() -> None:
    try:
        if sys.platform != "win32":
            import fcntl
            _STORE_FILE.touch(exist_ok=True)
            with open(_STORE_FILE, "r+", encoding="utf-8") as _f:
                fcntl.flock(_f, fcntl.LOCK_EX)
                try:
                    _f.seek(0)
                    _f.write(json.dumps(_store, indent=2))
                    _f.truncate()
                finally:
                    fcntl.flock(_f, fcntl.LOCK_UN)
        else:
            _STORE_FILE.write_text(json.dumps(_store, indent=2), encoding="utf-8")
    except Exception as _exc:
        logger.warning("Memory JSON save failed: %s", _exc)


if _backend_type == "json":
    _json_load()

# ── Public interface ───────────────────────────────────────────────────────

def add_memory(user_id: str, content: str, category: str = "general") -> dict:
    """Store a memory entry. Routes to the active backend."""
    if _backend_type == "chromadb":
        entry = _chroma_add(user_id, content, category)
    elif _backend_type == "pgvector":
        entry = _pg_add(user_id, content, category)
    else:
        _json_load()
        entry = {"user_id": user_id, "content": content, "category": category}
        _store.append(entry)
        _json_save()
    logger.info("Memory stored (%s) for user %s: %s", _backend_type, user_id, content[:50])
    return entry


def get_memories(user_id: str, category: Optional[str] = None) -> _List[dict]:
    """Return all memories for a user, optionally filtered by category."""
    if _backend_type == "chromadb":
        return _chroma_get(user_id, category)
    if _backend_type == "pgvector":
        return _pg_get(user_id, category)
    _json_load()
    return [
        m for m in _store
        if m["user_id"] == user_id and (category is None or m["category"] == category)
    ]


def search_memories(user_id: str, query: str, limit: int = 5) -> _List[dict]:
    """Search memories by semantic similarity (ChromaDB) or substring (pgvector/JSON)."""
    if _backend_type == "chromadb":
        return _chroma_search(user_id, query, limit)
    if _backend_type == "pgvector":
        return _pg_search(user_id, query, limit)
    _json_load()
    return [
        m for m in _store
        if m["user_id"] == user_id and query.lower() in m["content"].lower()
    ][:limit]
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
        '''from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from .memory_service import add_memory, get_memories, search_memories

try:  # the generated backend's auth dependency (src/auth.py)
    from src.auth import get_current_user
except ImportError:
    try:
        from auth import get_current_user
    except ImportError:
        async def get_current_user():
            # Fail closed: memories are personal data and must never be served unauthenticated.
            raise HTTPException(status_code=503, detail="memory disabled: auth.get_current_user not found")

router = APIRouter(prefix="/memory", tags=["Memory"])

class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    category: str = Field(default="general", max_length=100)

# The owner is always the signed-in user from the token, never an id sent by the client (IDOR).
@router.post("/")
def create_memory(body: MemoryCreate, user: dict = Depends(get_current_user)):
    return add_memory(str(user["id"]), body.content, body.category)

@router.get("/")
def list_memories(category: Optional[str] = None, user: dict = Depends(get_current_user)):
    return {"memories": get_memories(str(user["id"]), category)}

@router.get("/search")
def search(q: str, user: dict = Depends(get_current_user)):
    return {"results": search_memories(str(user["id"]), q)}
'''
    )

    (mem_dir / "memory_graph_router.py").write_text(
        '''from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from .knowledge_graph import add_entity, add_relationship, get_graph

try:  # the graph is shared by all users, so only admins may read or change it
    from src.auth import require_admin
except ImportError:
    try:
        from auth import require_admin
    except ImportError:
        async def require_admin():
            raise HTTPException(status_code=503, detail="knowledge graph disabled: auth.require_admin not found")

router = APIRouter(prefix="/knowledge-graph", tags=["Knowledge Graph"], dependencies=[Depends(require_admin)])

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
        "  user_id VARCHAR(64) NOT NULL,\n"
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
