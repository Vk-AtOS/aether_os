"""
Tests for KnowledgeGraph class.
"""

from __future__ import annotations

import os
import json
import pytest
from src.knowledge.graph import KnowledgeGraph


def test_add_and_retrieve_node():
    """Test adding and retrieving a node."""
    graph = KnowledgeGraph()
    graph.add_node("file1.py", "file", {"path": "/app/file1.py"})
    
    assert "file1.py" in graph._graph.nodes
    assert graph._graph.nodes["file1.py"]["type"] == "file"
    assert graph._graph.nodes["file1.py"]["metadata"]["path"] == "/app/file1.py"


def test_add_and_retrieve_edge():
    """Test adding and retrieving an edge."""
    graph = KnowledgeGraph()
    graph.add_node("func1", "function")
    graph.add_node("func2", "function")
    graph.add_edge("func1", "func2", "calls", {"weight": 1})
    
    assert graph._graph.has_edge("func1", "func2")
    assert graph._graph.edges["func1", "func2"]["type"] == "calls"
    assert graph._graph.edges["func1", "func2"]["metadata"]["weight"] == 1


def test_get_related_entities_depth():
    """Test depth-based traversal."""
    graph = KnowledgeGraph()
    graph.add_node("A", "type")
    graph.add_node("B", "type")
    graph.add_node("C", "type")
    graph.add_node("D", "type")
    
    graph.add_edge("A", "B", "rel")
    graph.add_edge("B", "C", "rel")
    graph.add_edge("C", "D", "rel")
    
    # Depth 1: should see B
    related_1 = graph.get_related_entities("A", depth=1)
    assert len(related_1) == 1
    assert related_1[0]["id"] == "B"
    
    # Depth 2: should see B, C
    related_2 = graph.get_related_entities("A", depth=2)
    assert len(related_2) == 2
    ids = [r["id"] for r in related_2]
    assert "B" in ids
    assert "C" in ids


def test_get_fix_history():
    """Test fix history traversal."""
    graph = KnowledgeGraph()
    err_sig = "ValueError: test"
    graph.add_node(err_sig, "error")
    graph.add_node("fix1", "fix", {"diff": "..."})
    graph.add_node("fix2", "fix", {"diff": "..."})
    
    graph.add_edge(err_sig, "fix1", "fixed_by")
    graph.add_edge(err_sig, "fix2", "fixed_by")
    graph.add_edge(err_sig, "other", "related_to") # Should not be included
    graph.add_node("other", "function")
    
    history = graph.get_fix_history(err_sig)
    assert len(history) == 2
    ids = [h["id"] for h in history]
    assert "fix1" in ids
    assert "fix2" in ids


def test_find_similar_errors():
    """Test partial match for error signatures."""
    graph = KnowledgeGraph()
    graph.add_node("ValueError: line 1", "error")
    graph.add_node("ValueError: line 2", "error")
    graph.add_node("TypeError: line 1", "error")
    
    similar = graph.find_similar_errors("ValueError")
    assert len(similar) == 2
    ids = [s["id"] for s in similar]
    assert "ValueError: line 1" in ids
    assert "ValueError: line 2" in ids


def test_export_subgraph_is_serializable():
    """Test that exported subgraph is JSON serializable."""
    graph = KnowledgeGraph()
    graph.add_node("A", "type")
    graph.add_node("B", "type")
    graph.add_edge("A", "B", "rel")
    
    subgraph_data = graph.export_subgraph("A", depth=1)
    # This should not raise
    json_str = json.dumps(subgraph_data)
    assert "nodes" in subgraph_data
    # NetworkX serializes edges as "links" or "edges" depending on version
    assert "links" in subgraph_data or "edges" in subgraph_data


def test_persist_and_load(tmp_path):
    """Test persistence using pickle."""
    graph_path = tmp_path / "graph.gpickle"
    graph = KnowledgeGraph()
    graph.add_node("persist_me", "type")
    
    graph.persist(str(graph_path))
    assert os.path.exists(graph_path)
    
    new_graph = KnowledgeGraph()
    new_graph.load(str(graph_path))
    assert "persist_me" in new_graph._graph.nodes


def test_stats_returns_correct_counts():
    """Test graph statistics."""
    graph = KnowledgeGraph()
    graph.add_node("A", "type")
    graph.add_node("B", "type")
    graph.add_edge("A", "B", "rel")
    
    stats = graph.stats()
    assert stats["node_count"] == 2
    assert stats["edge_count"] == 1
    assert len(stats["top_5_connected"]) == 2


def test_empty_graph_returns_safe_defaults():
    """Test behavior on empty or missing data."""
    graph = KnowledgeGraph()
    
    assert graph.get_related_entities("nonexistent") == []
    assert graph.get_fix_history("nonexistent") == []
    assert graph.find_similar_errors("nonexistent") == []
    assert graph.export_subgraph("nonexistent") == {"nodes": [], "links": []}
    
    stats = graph.stats()
    assert stats["node_count"] == 0
    assert stats["edge_count"] == 0
    assert stats["top_5_connected"] == []
