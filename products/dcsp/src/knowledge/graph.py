"""
Knowledge graph layer for DCSP using NetworkX.
"""

from __future__ import annotations

import os
import pickle
import networkx as nx
from typing import Any, Dict, List


class KnowledgeGraph:
    """NetworkX-based knowledge graph for tracking entities and relationships."""

    def __init__(self) -> None:
        self._graph = nx.DiGraph()

    def add_node(self, node_id: str, node_type: str, metadata: dict | None = None) -> None:
        """Add a node with type and metadata."""
        self._graph.add_node(node_id, type=node_type, metadata=metadata or {})

    def add_edge(self, source: str, target: str, edge_type: str, metadata: dict | None = None) -> None:
        """Add a directed edge between nodes."""
        if not self._graph.has_node(source) or not self._graph.has_node(target):
            return
        self._graph.add_edge(source, target, type=edge_type, metadata=metadata or {})

    def get_related_entities(self, node_id: str, depth: int = 2) -> list[dict]:
        """BFS from node_id up to depth hops."""
        if not self._graph.has_node(node_id):
            return []

        related = []
        # BFS to find nodes within depth
        # nx.bfs_edges returns (u, v) pairs
        nodes_at_depth = nx.single_source_shortest_path_length(self._graph, node_id, cutoff=depth)
        
        for nid, dist in nodes_at_depth.items():
            if nid == node_id:
                continue
            data = self._graph.nodes[nid]
            related.append({
                "id": nid,
                "type": data.get("type", "unknown"),
                "metadata": data.get("metadata", {})
            })
        return related

    def get_fix_history(self, error_signature: str) -> list[dict]:
        """Traverse "fixed_by" edges to return fix nodes."""
        if not self._graph.has_node(error_signature):
            return []

        fixes = []
        for _, target, data in self._graph.out_edges(error_signature, data=True):
            if data.get("type") == "fixed_by":
                node_data = self._graph.nodes[target]
                fixes.append({
                    "id": target,
                    "type": node_data.get("type", "unknown"),
                    "metadata": node_data.get("metadata", {})
                })
        return fixes

    def find_similar_errors(self, error_signature: str) -> list[dict]:
        """Finds error nodes whose signature partially matches."""
        matches = []
        for nid, data in self._graph.nodes(data=True):
            if data.get("type") == "error" and error_signature in nid and nid != error_signature:
                matches.append({
                    "id": nid,
                    "type": "error",
                    "metadata": data.get("metadata", {})
                })
        return matches

    def export_subgraph(self, node_id: str, depth: int = 2) -> dict:
        """Returns JSON-serializable adjacency dict of subgraph."""
        if not self._graph.has_node(node_id):
            return {"nodes": [], "links": []}

        nodes_at_depth = nx.single_source_shortest_path_length(self._graph, node_id, cutoff=depth)
        subgraph = self._graph.subgraph(nodes_at_depth.keys())
        
        return nx.node_link_data(subgraph)

    def persist(self, path: str = "data/knowledge_graph.gpickle") -> None:
        """Saves graph using pickle."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump(self._graph, f)

    def load(self, path: str = "data/knowledge_graph.gpickle") -> None:
        """Loads graph using pickle."""
        if not os.path.exists(path):
            self._graph = nx.DiGraph()
            return
        with open(path, 'rb') as f:
            self._graph = pickle.load(f)

    def stats(self) -> dict:
        """Returns graph statistics."""
        node_count = self._graph.number_of_nodes()
        edge_count = self._graph.number_of_edges()
        
        # Top 5 connected by degree
        degrees = sorted(self._graph.degree(), key=lambda x: x[1], reverse=True)[:5]
        top_5 = [{"id": nid, "degree": deg} for nid, deg in degrees]

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "top_5_connected": top_5
        }
