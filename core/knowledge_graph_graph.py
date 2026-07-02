"""Graph traversal helpers for KnowledgeGraph.

Extracted from knowledge_graph.py to keep that file under 600 lines.
All functions here operate on the raw _nodes / _edges structures and are
imported as methods on KnowledgeGraph via delegation wrappers.

Public API (called via KnowledgeGraph instance methods):
  - kg_get_neighbors(edges, node_id, edge_type) -> list[str]
  - kg_find_related_patterns(nodes, edges, entity_name, max_depth) -> list[dict]
  - kg_get_subsystem_connections(nodes, edges) -> dict[str, list[str]]
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from aether_os.core.knowledge_graph import KGEdge, KGNode, EdgeType


# ---------------------------------------------------------------------------
# Pure graph traversal functions (no KnowledgeGraph import)
# ---------------------------------------------------------------------------

def kg_get_neighbors(
    edges: "List[KGEdge]",
    node_id: str,
    edge_type: "Optional[str | EdgeType]" = None,
) -> List[str]:
    """Return IDs of all nodes directly reachable from node_id via outgoing edges.

    If edge_type is given (string value or EdgeType enum), only edges of that type
    are followed.  Returns an empty list if node_id has no outgoing edges.
    """
    results: List[str] = []
    for edge in edges:
        if edge.from_id != node_id:
            continue
        if edge_type is not None:
            # Support both string and EdgeType enum
            edge_type_val = getattr(edge_type, "value", edge_type)
            actual_val = getattr(edge.type, "value", edge.type)
            if actual_val != edge_type_val:
                continue
        if edge.to_id not in results:
            results.append(edge.to_id)
    return results


def kg_find_related_patterns(
    nodes: "Dict[str, KGNode]",
    edges: "List[KGEdge]",
    entity_name: str,
    max_depth: int = 2,
) -> List[dict]:
    """BFS from entity_name; return properties dicts from all reachable nodes.

    Searches for any node whose id or label contains entity_name (case-insensitive).
    Traverses outgoing edges up to max_depth hops.  Returns a flat list of property
    dicts so callers can reason about related patterns without importing KGNode.
    """
    needle = entity_name.lower()
    start_ids: List[str] = [
        nid for nid, node in nodes.items()
        if needle in nid.lower() or needle in node.label.lower()
    ]

    visited: set[str] = set(start_ids)
    frontier: List[str] = list(start_ids)
    patterns: List[dict] = []

    for _ in range(max_depth):
        next_frontier: List[str] = []
        for node_id in frontier:
            node = nodes.get(node_id)
            if node and node.properties:
                patterns.append({"node_id": node_id, "label": node.label, **node.properties})
            for neighbor_id in kg_get_neighbors(edges, node_id):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    next_frontier.append(neighbor_id)
        frontier = next_frontier
        if not frontier:
            break

    return patterns


def kg_get_subsystem_connections(
    nodes: "Dict[str, KGNode]",
    edges: "List[KGEdge]",
) -> dict:
    """Return a map of subsystem prefix → list of connected node IDs.

    Subsystems are identified by node-id prefix convention:
      domain_pack:*  → domain packs
      validator:*    → validator nodes
      repair:*       → repair nodes
      phase:*        → phase nodes
      (everything else with ':' is treated as entity nodes)

    Returns dict[str, list[str]].
    """
    subsystem_prefixes = ("domain_pack", "validator", "repair", "phase")
    connections: dict = {prefix: [] for prefix in subsystem_prefixes}
    connections["entity"] = []

    for edge in edges:
        from_node = nodes.get(edge.from_id)
        to_node = nodes.get(edge.to_id)
        if from_node is None or to_node is None:
            continue
        for prefix in subsystem_prefixes:
            if edge.from_id.startswith(prefix + ":"):
                if edge.to_id not in connections[prefix]:
                    connections[prefix].append(edge.to_id)
        # Entity nodes use run_id:EntityName convention (has ":" but no known prefix)
        if ":" in edge.from_id and not any(
            edge.from_id.startswith(p + ":") for p in subsystem_prefixes
        ):
            if edge.to_id not in connections["entity"]:
                connections["entity"].append(edge.to_id)

    return connections
