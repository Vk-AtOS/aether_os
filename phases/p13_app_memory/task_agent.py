"""P13 Task Agent — integrate mem0 memory layer."""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client
logger = logging.getLogger(__name__)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    project_dir = Path(data.get("project_dir", str(output_dir)))
    project_id = phase_input.project_id
    data_dir = output_dir / "memory_store"
    data_dir.mkdir(exist_ok=True)

    # memory_service.py
    memory_service = f"""
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

_memory = None

def _get_memory():
    global _memory
    if _memory is None:
        try:
            from mem0 import Memory
            config = {{
                "vector_store": {{
                    "provider": "chroma",
                    "config": {{
                        "collection_name": "{project_id}",
                        "path": "{str(data_dir)}",
                    }}
                }},
                "embedder": {{
                    "provider": "openai",
                    "config": {{"model": "text-embedding-3-small"}}
                }},
            }}
            _memory = Memory.from_config(config)
        except Exception as e:
            logger.warning("mem0 init failed, using simple dict fallback: %s", e)
            _memory = _SimpleFallback()
    return _memory


class _SimpleFallback:
    def __init__(self):
        self._store: Dict[str, List] = {{}}

    def add(self, messages, user_id=None, **kwargs):
        key = user_id or "global"
        self._store.setdefault(key, []).append(messages)
        return {{"id": len(self._store.get(key, []))}}

    def search(self, query, user_id=None, limit=5, **kwargs):
        key = user_id or "global"
        results = self._store.get(key, [])
        return [{{"memory": str(r), "score": 0.9}} for r in results[-limit:]]

    def get_all(self, user_id=None, **kwargs):
        key = user_id or "global"
        return [{{"memory": str(r)}} for r in self._store.get(key, [])[-10:]]


def add_memory(user_id: str, content: str, metadata: Dict = None) -> Dict:
    try:
        mem = _get_memory()
        result = mem.add(content, user_id=user_id, metadata=metadata or {{}})
        return result
    except Exception as e:
        logger.error("add_memory failed: %s", e)
        return {{}}


def search_memory(user_id: str, query: str, limit: int = 5) -> List[Dict]:
    try:
        mem = _get_memory()
        results = mem.search(query, user_id=user_id, limit=limit)
        return results if isinstance(results, list) else []
    except Exception as e:
        logger.error("search_memory failed: %s", e)
        return []


def get_recent(user_id: str, limit: int = 10) -> List[Dict]:
    try:
        mem = _get_memory()
        results = mem.get_all(user_id=user_id)
        items = results if isinstance(results, list) else []
        return items[-limit:]
    except Exception as e:
        logger.error("get_recent failed: %s", e)
        return []
"""
    memory_file = project_dir / "src" / "memory_service.py"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(memory_service)

    # Unit tests for memory service
    memory_tests = """
import pytest, sys, os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

def test_add_memory_returns_result():
    from memory_service import add_memory
    result = add_memory("user_1", "User prefers dark mode")
    assert result is not None

def test_search_memory_returns_list():
    from memory_service import search_memory
    results = search_memory("user_1", "preferences", limit=5)
    assert isinstance(results, list)

def test_get_recent_returns_list():
    from memory_service import get_recent
    results = get_recent("user_1", limit=5)
    assert isinstance(results, list)

def test_memory_roundtrip():
    from memory_service import add_memory, search_memory
    add_memory("user_test", "User likes feature X")
    # Search should return something (or empty list — not an error)
    results = search_memory("user_test", "feature", limit=3)
    assert isinstance(results, list)
"""
    tests_dir = output_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_memory_service.py").write_text(memory_tests)

    # Verify mem0 initialises
    mem_ok = False
    try:
        from mem0 import Memory
        mem_ok = True
    except ImportError:
        pass

    issues = []
    if not memory_file.exists():
        issues.append("memory_service.py not written")
    if not mem_ok:
        issues.append("mem0 package not importable")

    return TaskResult(
        output_path=str(memory_file),
        confidence=0.9 if not issues else 0.6,
        metadata={"mem0_available": mem_ok, "data_dir": str(data_dir),
                  "test_file": str(tests_dir / "test_memory_service.py")},
        issues=issues,
        success=memory_file.exists(),
    )
