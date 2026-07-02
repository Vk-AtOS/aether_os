"""Knowledge graph integration — called after p02b completes domain IR extraction.

Provides two public functions:
  - save_ir_to_knowledge_graph(accumulated_context) — persist domain IR entities
  - get_similar_entity_patterns(domain, limit)      — retrieve past entity patterns

Both are non-fatal: any storage error is logged as a warning and the pipeline continues.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def save_ir_to_knowledge_graph(accumulated_context: dict) -> None:
    """Persist domain IR entities to the knowledge graph for future similar-run retrieval.

    Should be called after p02b completes and domain_ir is available in accumulated_context.
    Writes entity patterns to /tmp/aetheros_knowledge_graphs/{domain}.json so they can be
    retrieved by get_similar_entity_patterns() in future runs for the same domain.
    """
    try:
        from aether_os.core.knowledge_graph import KnowledgeGraph

        domain_ir = accumulated_context.get("domain_ir", {})
        if not domain_ir:
            logger.debug("knowledge_graph_integration: no domain_ir in context — skipping")
            return

        run_id = str(accumulated_context.get("run_id", "unknown"))
        domain = str(accumulated_context.get("domain", "general"))

        kg = KnowledgeGraph.record_from_ir(domain_ir, run_id, domain)
        kg.save_for_domain(domain, run_id)

        accumulated_context["knowledge_graph_saved"] = True
        entity_count = len(domain_ir.get("entities", []))
        logger.info(
            "knowledge_graph: saved %d entities for domain '%s' (run_id=%s)",
            entity_count,
            domain,
            run_id,
        )
    except Exception as e:
        logger.warning("knowledge_graph integration failed (non-fatal): %s", e)


def get_similar_entity_patterns(domain: str, limit: int = 3) -> list:
    """Retrieve entity patterns from similar past runs for use in p00b/p01.

    Returns a list of entity property dicts (each has 'name', 'fields', 'relationships').
    Returns empty list if no patterns exist or if storage is unavailable (fail open).
    """
    try:
        from aether_os.core.knowledge_graph import KnowledgeGraph

        patterns = KnowledgeGraph.load_for_domain(domain, limit=limit)
        logger.debug(
            "knowledge_graph: retrieved %d entity patterns for domain '%s'",
            len(patterns),
            domain,
        )
        return patterns
    except Exception as e:
        logger.warning("knowledge_graph: pattern retrieval failed (non-fatal): %s", e)
        return []
