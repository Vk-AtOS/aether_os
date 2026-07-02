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
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default storage path relative to this file's package root.
_DEFAULT_KG_PATH = Path(__file__).parent / "knowledge_graph.json"

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
            # Wire FK relationships as REQUIRES edges
            for ref in relationships:
                ref_id = f"{run_id}:{ref}"
                kg.add_edge(KGEdge(node_id, ref_id, EdgeType.REQUIRES))
        return kg

    def save_for_domain(self, domain: str, run_id: str) -> None:
        """Persist entity patterns to /tmp/aetheros_knowledge_graphs/{domain}.json.

        Appends this run's entity patterns to the existing domain file so future
        runs can retrieve similar entity structures via load_for_domain().
        """
        try:
            kg_dir = Path("/tmp/aetheros_knowledge_graphs")
            kg_dir.mkdir(parents=True, exist_ok=True)
            safe_domain = domain.lower().replace(" ", "_").replace("/", "_")
            kg_file = kg_dir / f"{safe_domain}.json"
            existing: dict = {}
            if kg_file.exists():
                try:
                    existing = json.loads(kg_file.read_text())
                except Exception as _read_err:
                    logger.warning("[kg] domain file unreadable, starting fresh: %s", _read_err)
            patterns = existing.get("patterns", [])
            # Append new entity nodes from this run
            new_entries = [
                n.properties for n in self._nodes.values()
                if n.properties.get("run_id") == run_id
            ]
            patterns.extend(new_entries)
            # Keep at most 50 most recent patterns per domain (rolling window)
            patterns = patterns[-50:]
            kg_file.write_text(json.dumps({"domain": domain, "patterns": patterns}, indent=2))
            logger.debug("[kg] saved %d entity patterns for domain '%s'", len(new_entries), domain)
        except Exception as e:
            logger.warning("[kg] save_for_domain failed (non-fatal): %s", e)

    @classmethod
    def load_for_domain(cls, domain: str, limit: int = 5) -> list:
        """Load recent entity patterns from similar past runs for a given domain.

        Returns a plain list of entity property dicts so callers don't need to
        import KGNode. Returns empty list if storage unavailable (fail open).
        """
        try:
            kg_dir = Path("/tmp/aetheros_knowledge_graphs")
            safe_domain = domain.lower().replace(" ", "_").replace("/", "_")
            kg_file = kg_dir / f"{safe_domain}.json"
            if not kg_file.exists():
                return []
            data = json.loads(kg_file.read_text())
            return data.get("patterns", [])[:limit]
        except Exception as e:
            logger.warning("[kg] load_for_domain failed (non-fatal): %s", e)
            return []


# ---------------------------------------------------------------------------
# Pre-populated fix patterns
# ---------------------------------------------------------------------------

def _seed_fix_patterns(kg: KnowledgeGraph) -> None:
    """Write known fix patterns into the graph.

    These represent engineering lessons from previous sessions:
    - relative_import_bug  → absolute_imports_constraint
    - missing_all_routers  → all_routers_export_rule
    - seed_unique_violation → unique_field_pattern_constraint
    """
    nodes = [
        KGNode(
            id="relative_import_bug",
            type=NodeType.FIX,
            label="Relative import inside phase agent causes ImportError at runtime",
            properties={
                "symptom": "ImportError: attempted relative import beyond top-level package",
                "phase": "p04a, p04b, p05",
                "first_seen": "Session-AY",
            },
        ),
        KGNode(
            id="absolute_imports_constraint",
            type=NodeType.CONSTRAINT,
            label="Always use absolute imports (aether_os.core.x) inside phase agents",
            properties={
                "rule": "from aether_os.X import Y — never from ..X import Y",
                "reason": "Phase agents are loaded dynamically; relative imports fail",
            },
        ),
        KGNode(
            id="missing_all_routers",
            type=NodeType.FIX,
            label="Generated app has no routers/__init__.py — imports fail at startup",
            properties={
                "symptom": "ModuleNotFoundError: No module named 'src.routers'",
                "phase": "p04a",
                "first_seen": "Session-AN",
            },
        ),
        KGNode(
            id="all_routers_export_rule",
            type=NodeType.CONSTRAINT,
            label="Every generated routers/ directory must have __init__.py exporting all routers",
            properties={
                "rule": "p04a must write routers/__init__.py with from .X import router",
                "reason": "FastAPI app.include_router requires importable router objects",
            },
        ),
        KGNode(
            id="seed_unique_violation",
            type=NodeType.FIX,
            label="Seed data hits UNIQUE constraint because email/username not unique per row",
            properties={
                "symptom": "sqlalchemy.exc.IntegrityError: UNIQUE constraint failed: users.email",
                "phase": "p04a seed.py",
                "first_seen": "Session-BF",
            },
        ),
        KGNode(
            id="unique_field_pattern_constraint",
            type=NodeType.CONSTRAINT,
            label="Seed generator must use unique values for email/username fields",
            properties={
                "rule": "For each entity row i, use email=f'user{i}@example.com'",
                "reason": "Duplicate emails in seed data cause IntegrityError on first run",
            },
        ),
        # Additional patterns from session history
        KGNode(
            id="circular_fk_deadlock",
            type=NodeType.FIX,
            label="Circular FK reference causes seed data deadlock",
            properties={
                "symptom": "Cannot insert row: FK constraint fails in both directions",
                "phase": "p02b, p04a seed.py",
                "first_seen": "Item 1 — domain IR validator",
            },
        ),
        KGNode(
            id="nullable_fk_break_cycle",
            type=NodeType.CONSTRAINT,
            label="Break circular FK cycles by making one side nullable",
            properties={
                "rule": "If A→B and B→A, make B.a_id nullable=True so A can be inserted first",
                "reason": "Nullable FK allows deferred insertion order resolution",
            },
        ),
        KGNode(
            id="sqlalchemy_reserved_name",
            type=NodeType.FIX,
            label="Entity named Base/Session/Model conflicts with SQLAlchemy internals",
            properties={
                "symptom": "AttributeError or mysterious ORM behaviour at startup",
                "phase": "p02b, p04a models.py",
                "first_seen": "Item 1 — domain IR validator D4",
            },
        ),
        KGNode(
            id="rename_reserved_entity",
            type=NodeType.CONSTRAINT,
            label="Rename entities that conflict with SQLAlchemy reserved names",
            properties={
                "rule": "Never name an entity Base, Session, Model, Query, or metadata",
                "reason": "SQLAlchemy imports these names into the ORM namespace",
            },
        ),
    ]

    edges = [
        KGEdge("relative_import_bug", "absolute_imports_constraint", EdgeType.FIXES),
        KGEdge("missing_all_routers", "all_routers_export_rule", EdgeType.FIXES),
        KGEdge("seed_unique_violation", "unique_field_pattern_constraint", EdgeType.FIXES),
        KGEdge("circular_fk_deadlock", "nullable_fk_break_cycle", EdgeType.FIXES),
        KGEdge("sqlalchemy_reserved_name", "rename_reserved_entity", EdgeType.FIXES),
        # Cross-links
        KGEdge("seed_unique_violation", "circular_fk_deadlock", EdgeType.RELATED_TO),
        KGEdge("circular_fk_deadlock", "seed_unique_violation", EdgeType.RELATED_TO),
        KGEdge("absolute_imports_constraint", "all_routers_export_rule", EdgeType.RELATED_TO),
    ]

    for node in nodes:
        kg.add_node(node)
    for edge in edges:
        kg.add_edge(edge)


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

    # Pre-populate with known patterns if file was absent or empty
    if not file_existed or not kg.all_nodes():
        logger.info("[kg] seeding fix patterns into knowledge graph at %s", path)
        _seed_fix_patterns(kg)
        try:
            kg.save(path)
        except Exception as e:
            logger.warning("[kg] could not save initial knowledge graph: %s", e)

    _SINGLETON = kg
    return _SINGLETON
