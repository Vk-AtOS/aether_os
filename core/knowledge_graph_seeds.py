"""Pre-populated fix patterns for the AetherOS knowledge graph.

Extracted from knowledge_graph.py to keep that module under the 600-line limit.
Call seed_fix_patterns(kg) after creating a fresh KnowledgeGraph instance.
"""
from __future__ import annotations

from aether_os.core.knowledge_graph import EdgeType, KGEdge, KGNode, KnowledgeGraph, NodeType


def seed_fix_patterns(kg: KnowledgeGraph) -> None:
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
