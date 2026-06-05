"""
AetherOS — Memory Router
POST /memory/search
GET /memory/graph
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["memory"])


def _current_user():
    return Depends(get_current_user)


@router.post("/memory/search")
async def memory_search(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """
    Similarity search over past runs for the current org.
    Returns top-k matches with similarity scores and context hints.
    Body: { query: str, top_k?: int }
    """
    query = (req.get("query") or "").strip()
    top_k = min(int(req.get("top_k", 5)), 10)
    if not query:
        raise HTTPException(status_code=422, detail="query is required")
    org_id = user.get("org_id", "default")
    try:
        from aether_os.core.services.memory_service import get_memory_service
        ms = get_memory_service()
        matches = await ms._find_similar_runs(org_id=org_id, raw_input=query, top_k=top_k)
        # Normalise field names for the frontend SimilarRunCard component
        normalised = []
        for m in matches:
            normalised.append({
                "run_id":     m.get("run_id", ""),
                "project":    m.get("project_name", m.get("project", "Unnamed")),
                "similarity": round(float(m.get("similarity", 0.0)), 3),
                "domain":     m.get("domain", ""),
                "hint":       m.get("winning_approach", m.get("hint", "")),
            })
        return {"matches": normalised, "query": query}
    except Exception as exc:
        logger.warning("memory_search failed: %s", exc)
        return {"matches": [], "query": query}


@router.get("/memory/graph")
async def memory_graph(
    limit: int = 50,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return memory store data in graph format for visualisation (nodes + edges)."""
    org_id = user.get("org_id", "default")
    try:
        from aether_os.core.memory.store import get_memory_store
        store = get_memory_store()
        stats = store.stats()
        records = store.retrieve_sync("", k=min(limit, 100))

        nodes = []
        edges = []
        task_type_idx: Dict[str, str] = {}

        # Task-type cluster nodes
        for task_type, count in stats.get("by_task_type", {}).items():
            nid = f"task:{task_type}"
            task_type_idx[task_type] = nid
            nodes.append({"id": nid, "label": task_type, "type": "task_type", "count": count})

        # Memory record leaf nodes
        for r in records:
            nid = f"mem:{r.id}"
            nodes.append({
                "id": nid,
                "label": (r.input_text[:40] + "…") if len(r.input_text) > 40 else r.input_text,
                "type": "memory",
                "success_count": r.success_count,
                "task_type": r.task_type,
            })
            parent = task_type_idx.get(r.task_type)
            if parent:
                edges.append({"source": parent, "target": nid, "weight": r.success_count})

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": stats,
        }
    except Exception as exc:
        logger.warning("memory_graph failed: %s", exc)
        return {"nodes": [], "edges": [], "stats": {}}
