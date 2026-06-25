"""
Redis-based caching for AST index and call graphs.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import redis

# Redis URL from environment variable
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Initialize Redis client
_redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# TTL for cache entries (1 hour)
CACHE_TTL = 3600


def cache_ast_index(repo_name: str, index_dict: dict[str, dict]) -> None:
    """
    Store AST index in Redis with 1hr TTL.
    """
    key = f"ast_index:{repo_name}"
    _redis_client.set(key, json.dumps(index_dict), ex=CACHE_TTL)


def get_ast_index(repo_name: str) -> Optional[dict[str, dict]]:
    """
    Retrieve AST index from Redis or return None.
    """
    key = f"ast_index:{repo_name}"
    data = _redis_client.get(key)
    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None
    return None


def cache_call_graph(repo_name: str, graph_dict: dict[str, Any]) -> None:
    """
    Store call graph in Redis with 1hr TTL.
    """
    key = f"call_graph:{repo_name}"
    _redis_client.set(key, json.dumps(graph_dict), ex=CACHE_TTL)


def get_call_graph(repo_name: str) -> Optional[dict[str, Any]]:
    """
    Retrieve call graph from Redis or return None.
    """
    key = f"call_graph:{repo_name}"
    data = _redis_client.get(key)
    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None
    return None
