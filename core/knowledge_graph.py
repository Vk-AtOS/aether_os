"""Knowledge Graph — typed, JSON-backed graph of engineering patterns and fixes.

NOT a vector database. NOT networkx. A simple dict-backed graph with typed
nodes and edges persisted to core/knowledge_graph.json on disk.

Typical use cases
-----------------
  - Phase agents query get_fixes_for("relative_import") to find known solutions.
  - Audit tools record DECISION nodes and REQUIRES edges for traceability.
  - The IR validator can query get_related("seed_unique_violation") to surface
    the fix pattern before the seed generator runs.

Singleton
---------
Call `get_singleton()` to get the shared instance (loaded from
core/knowledge_graph.json on first access, auto-created if missing).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from aether_os.core.knowledge_graph_graph import (
    kg_get_neighbors,
    kg_find_related_patterns,
    kg_get_subsystem_connections,
)

logger = logging.getLogger(__name__)

# Default storage path relative to this file's package root.
_DEFAULT_KG_PATH = Path(__file__).parent / "knowledge_graph.json"

# Persistent directory for domain-specific KG files — survives server restarts.
_KG_DOMAIN_DIR = os.environ.get(
    "AETHER_KG_DIR",
    os.path.join(os.path.expanduser("~"), ".aether_os", "knowledge_graphs")
)
Path(_KG_DOMAIN_DIR).mkdir(parents=True, exist_ok=True)

_SINGLETON: Optional["KnowledgeGraph"] = None


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    ENTITY = "entity"
    DECISION = "decision"
    FIX = "fix"
    CONSTRAINT = "constraint"
    PATTERN = "pattern"
    DOMAIN = "domain"


class EdgeType(str, Enum):
    CAUSES = "causes"
    FIXES = "fixes"
    REQUIRES = "requires"
    CONFLICTS_WITH = "conflicts_with"
    RELATED_TO = "related_to"
    APPLIES_TO = "applies_to"
    # Cross-subsystem edge types (added for graph traversal upgrade)
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    REPAIRED_BY = "repaired_by"
    VALIDATED_BY = "validated_by"
    GENERATES = "generates"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class KGNode:
    id: str
    type: NodeType
    label: str
    properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, NodeType) else self.type,
            "label": self.label,
            "properties": self.properties,
        }

    @staticmethod
    def from_dict(d: dict) -> "KGNode":
        return KGNode(
            id=d["id"],
            type=NodeType(d["type"]),
            label=d["label"],
            properties=d.get("properties", {}),
        )


@dataclass
class KGEdge:
    from_id: str
    to_id: str
    type: EdgeType
    weight: float = 1.0

    def to_dict(self) -> dict:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "type": self.type.value if isinstance(self.type, EdgeType) else self.type,
            "weight": self.weight,
        }

    @staticmethod
    def from_dict(d: dict) -> "KGEdge":
        return KGEdge(
            from_id=d["from_id"],
            to_id=d["to_id"],
            type=EdgeType(d["type"]),
            weight=float(d.get("weight", 1.0)),
        )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class KnowledgeGraph:
    """In-memory knowledge graph backed by a JSON file.

    All mutating methods (add_node, add_edge) keep the in-memory graph in
    sync but do NOT auto-save — call save() explicitly or use the singleton
    which saves on first pre-population.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, KGNode] = {}
        self._edges: List[KGEdge] = []

    # ------------------------------------------------------------------ mutate

    def add_node(self, node: KGNode) -> None:
        """Add or replace a node by id."""
        if node.id in self._nodes:
            logger.debug("[kg] overwriting node id=%s", node.id)
        self._nodes[node.id] = node

    def add_edge(self, edge: KGEdge) -> None:
        """Add an edge.  Duplicate edges (same from/to/type) are silently ignored."""
        for existing in self._edges:
            if (existing.from_id == edge.from_id
                    and existing.to_id == edge.to_id
                    and existing.type == edge.type):
                return
        self._edges.append(edge)

    # ------------------------------------------------------------------ query

    def get_node(self, node_id: str) -> Optional[KGNode]:
        """Return the node with the given id, or None."""
        return self._nodes.get(node_id)

    def get_related(
        self,
        node_id: str,
        edge_type: Optional[EdgeType] = None,
    ) -> List[KGNode]:
        """Return all nodes directly connected FROM node_id.

        If edge_type is given, only edges of that type are followed.
        """
        results: List[KGNode] = []
        for edge in self._edges:
            if edge.from_id != node_id:
                continue
            if edge_type is not None and edge.type != edge_type:
                continue
            target = self._nodes.get(edge.to_id)
            if target is not None:
                results.append(target)
        return results

    def get_fixes_for(self, error_category: str) -> List[KGNode]:
        """Return all FIX nodes reachable from error_category via FIXES edges.

        error_category is matched case-insensitively against node IDs and labels.
        """
        # Find matching source nodes
        candidates: List[str] = []
        needle = error_category.lower()
        for node_id, node in self._nodes.items():
            if needle in node_id.lower() or needle in node.label.lower():
                candidates.append(node_id)

        fixes: List[KGNode] = []
        seen: set[str] = set()
        for cid in candidates:
            for edge in self._edges:
                if edge.from_id == cid and edge.type == EdgeType.FIXES:
                    fix_node = self._nodes.get(edge.to_id)
                    if fix_node and fix_node.id not in seen:
                        fixes.append(fix_node)
                        seen.add(fix_node.id)
        return fixes

    def all_nodes(self) -> List[KGNode]:
        return list(self._nodes.values())

    def all_edges(self) -> List[KGEdge]:
        return list(self._edges)

    # ------------------------------------------------------------------ graph traversal
    # Implementations live in knowledge_graph_graph.py (split to keep this file
    # under the 600-line hard limit).  These wrappers delegate to the pure functions.

    def get_neighbors(self, node_id: str, edge_type: Optional[str] = None) -> List[str]:
        """Return IDs of all nodes directly reachable from node_id via outgoing edges."""
        return kg_get_neighbors(self._edges, node_id, edge_type)

    def find_related_patterns(
        self, entity_name: str, max_depth: int = 2
    ) -> List[dict]:
        """BFS from entity_name node; return properties from all reachable nodes."""
        return kg_find_related_patterns(self._nodes, self._edges, entity_name, max_depth)

    def get_subsystem_connections(self) -> dict:
        """Return a map of subsystem prefix → list of connected node IDs."""
        return kg_get_subsystem_connections(self._nodes, self._edges)

    # ------------------------------------------------------------------ persistence

    def save(self, path: Path) -> None:
        """Persist the graph to a JSON file."""
        try:
            data = {
                "nodes": [n.to_dict() for n in self._nodes.values()],
                "edges": [e.to_dict() for e in self._edges],
            }
            path.write_text(json.dumps(data, indent=2))
            logger.debug("[kg] saved %d nodes / %d edges to %s",
                         len(self._nodes), len(self._edges), path)
        except Exception as e:
            logger.warning("[kg] save failed: %s", e)

    def load(self, path: Path) -> None:
        """Load graph from a JSON file, merging into current state."""
        if not path.exists():
            logger.debug("[kg] no file at %s — starting empty", path)
            return
        try:
            data = json.loads(path.read_text())
            for nd in data.get("nodes", []):
                try:
                    self.add_node(KGNode.from_dict(nd))
                except Exception as e:
                    logger.warning("[kg] skipping malformed node %s: %s", nd.get("id"), e)
            for ed in data.get("edges", []):
                try:
                    self.add_edge(KGEdge.from_dict(ed))
                except Exception as e:
                    logger.warning("[kg] skipping malformed edge %s→%s: %s",
                                   ed.get("from_id"), ed.get("to_id"), e)
            logger.debug("[kg] loaded %d nodes / %d edges from %s",
                         len(self._nodes), len(self._edges), path)
        except Exception as e:
            logger.warning("[kg] load failed for %s: %s", path, e)

    # ------------------------------------------------------------------ domain IR integration

    @classmethod
    def record_from_ir(cls, domain_ir: dict, run_id: str, domain: str) -> "KnowledgeGraph":
        """Create a KnowledgeGraph populated from a completed domain IR.

        Called after p02b completes to persist entity patterns for future retrieval.
        Each entity becomes a DOMAIN node; FK relationships become REQUIRES edges.
        """
        kg = cls()

        # Create a domain-pack node so cross-subsystem edges have a source
        domain_pack_id = f"domain_pack:{domain}:{run_id}"
        kg.add_node(KGNode(
            id=domain_pack_id,
            type=NodeType.DOMAIN,
            label=f"{domain} (run {run_id})",
            properties={"run_id": run_id, "domain": domain},
        ))

        for entity in domain_ir.get("entities", []):
            entity_name = entity.get("name", "")
            if not entity_name:
                continue
            fields = entity.get("fields", []) or []
            field_names = [
                f.get("name") if isinstance(f, dict) else str(f)
                for f in fields
            ]
            relationships = [
                f.get("references")
                for f in fields
                if isinstance(f, dict)
                and f.get("type") == "foreign_key"
                and f.get("references")
            ]
            node_id = f"{run_id}:{entity_name}"
            kg.add_node(KGNode(
                id=node_id,
                type=NodeType.ENTITY,
                label=entity_name,
                properties={
                    "run_id": run_id,
                    "domain": domain,
                    "fields": field_names,
                    "relationships": relationships,
                },
            ))
            # Cross-subsystem: domain_pack → entity (CONTAINS edge)
            kg.add_edge(KGEdge(domain_pack_id, node_id, EdgeType.CONTAINS))
            # Wire FK relationships as REQUIRES edges
            for ref in relationships:
                ref_id = f"{run_id}:{ref}"
                kg.add_edge(KGEdge(node_id, ref_id, EdgeType.REQUIRES))
        return kg

    def save_for_domain(self, domain: str, run_id: str) -> None:
        """Persist entity patterns and run edges to _KG_DOMAIN_DIR/{domain}.json.

        Uses the persistent directory set by AETHER_KG_DIR env var (default:
        ~/.aether_os/knowledge_graphs/).  Appends this run's entity patterns and
        edges to the domain file so future runs can retrieve similar structures
        via load_for_domain().  Edges are stored as plain dicts so the file stays
        JSON-serialisable without importing KGEdge.
        """
        try:
            kg_dir = Path(_KG_DOMAIN_DIR)
            kg_dir.mkdir(parents=True, exist_ok=True)
            safe_domain = domain.lower().replace(" ", "_").replace("/", "_")
            kg_file = kg_dir / f"{safe_domain}.json"
            existing: dict = {}
            if kg_file.exists():
                try:
                    existing = json.loads(kg_file.read_text())
                except Exception as _read_err:
                    logger.warning("[kg] domain file unreadable, starting fresh: %s", _read_err)

            # --- patterns (entity node properties) ---
            patterns = existing.get("patterns", [])
            new_entries = [
                n.properties for n in self._nodes.values()
                if n.properties.get("run_id") == run_id
            ]
            patterns.extend(new_entries)
            patterns = patterns[-50:]  # rolling window

            # --- edges for this run ---
            existing_edges: list = existing.get("edges", [])
            run_node_ids = {
                node_id for node_id, n in self._nodes.items()
                if n.properties.get("run_id") == run_id
            }
            new_edge_dicts = [
                e.to_dict() for e in self._edges
                if e.from_id in run_node_ids or e.to_id in run_node_ids
            ]
            existing_edges.extend(new_edge_dicts)
            existing_edges = existing_edges[-200:]  # cap to avoid unbounded growth

            kg_file.write_text(json.dumps(
                {"domain": domain, "patterns": patterns, "edges": existing_edges},
                indent=2,
            ))
            logger.debug(
                "[kg] saved %d entity patterns + %d edges for domain '%s'",
                len(new_entries), len(new_edge_dicts), domain,
            )

            # Cross-subsystem: add entity → pattern edges in memory
            for entry in new_entries:
                entity_name = entry.get("run_id", run_id) + ":" + (
                    next(
                        (n.label for n in self._nodes.values() if n.properties == entry),
                        "unknown",
                    )
                )
                pattern_node_id = f"pattern:{safe_domain}:{run_id}:{entry.get('run_id', '')}"
                if not self.get_node(pattern_node_id):
                    self.add_node(KGNode(
                        id=pattern_node_id,
                        type=NodeType.PATTERN,
                        label=f"Pattern for {domain} run {run_id}",
                        properties=entry,
                    ))
                self.add_edge(KGEdge(entity_name, pattern_node_id, EdgeType.GENERATES))
        except Exception as e:
            logger.warning("[kg] save_for_domain failed (non-fatal): %s", e)

    @classmethod
    def load_for_domain(cls, domain: str, limit: int = 5) -> list:
        """Load recent entity patterns from similar past runs for a given domain.

        Returns a plain list of entity property dicts so callers don't need to
        import KGNode.  Returns empty list if storage unavailable (fail open).
        Also restores edges from the domain file into the returned KnowledgeGraph
        via the companion load_edges_for_domain() classmethod.
        """
        try:
            kg_dir = Path(_KG_DOMAIN_DIR)
            safe_domain = domain.lower().replace(" ", "_").replace("/", "_")
            kg_file = kg_dir / f"{safe_domain}.json"
            if not kg_file.exists():
                return []
            data = json.loads(kg_file.read_text())
            return data.get("patterns", [])[:limit]
        except Exception as e:
            logger.warning("[kg] load_for_domain failed (non-fatal): %s", e)
            return []

    @classmethod
    def load_edges_for_domain(cls, domain: str) -> "List[KGEdge]":
        """Load persisted edges for a domain from the domain knowledge graph file.

        Returns a list of KGEdge objects restored from the stored edge dicts.
        Malformed edges are skipped with a warning.  Returns empty list on error.
        """
        try:
            kg_dir = Path(_KG_DOMAIN_DIR)
            safe_domain = domain.lower().replace(" ", "_").replace("/", "_")
            kg_file = kg_dir / f"{safe_domain}.json"
            if not kg_file.exists():
                return []
            data = json.loads(kg_file.read_text())
            restored: List[KGEdge] = []
            for ed in data.get("edges", []):
                try:
                    restored.append(KGEdge.from_dict(ed))
                except Exception as _e:
                    logger.warning("[kg] skipping malformed domain edge %s: %s", ed, _e)
            return restored
        except Exception as e:
            logger.warning("[kg] load_edges_for_domain failed (non-fatal): %s", e)
            return []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def get_singleton(path: Path = _DEFAULT_KG_PATH) -> KnowledgeGraph:
    """Return the module-level singleton KnowledgeGraph.

    On first call:
    1. Loads from `path` if the file exists.
    2. Seeds known fix patterns if the file was empty or missing.
    3. Saves the populated graph back to `path`.
    """
    global _SINGLETON
    if _SINGLETON is not None:
        return _SINGLETON

    kg = KnowledgeGraph()
    file_existed = path.exists()
    kg.load(path)

    # Pre-populate with known patterns if file was absent or empty.
    # Import is deferred here to avoid a circular import (knowledge_graph_seeds
    # imports KGNode/KGEdge/etc. from this module).
    if not file_existed or not kg.all_nodes():
        logger.info("[kg] seeding fix patterns into knowledge graph at %s", path)
        from aether_os.core.knowledge_graph_seeds import seed_fix_patterns  # noqa: PLC0415
        seed_fix_patterns(kg)
        try:
            kg.save(path)
        except Exception as e:
            logger.warning("[kg] could not save initial knowledge graph: %s", e)

    _SINGLETON = kg
    return _SINGLETON
