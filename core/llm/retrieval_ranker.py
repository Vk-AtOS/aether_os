"""
Knowledge Retrieval Ranker — assembles ranked relevant knowledge for each LLM call.

Sources ranked by relevance:
1. Error registry — past bugs for this domain/phase (highest weight)
2. Domain pack constraints — must-follow rules (highest weight)
3. Golden examples from knowledge graph — similar past runs (high weight)
4. Negative examples — what to avoid (medium weight)
5. Architecture warnings from this run (low weight)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RankedKnowledge:
    """A single piece of retrieved knowledge with relevance metadata."""

    source: str           # human-readable label, e.g. "error_registry", "domain_pack"
    content: str          # the text to inject into the prompt
    weight: float         # static source weight (0.0–1.0)
    phase_relevance: float = 1.0  # computed relevance for this specific phase (0.0–1.0)

    @property
    def score(self) -> float:
        """Combined score used for sorting (weight × phase_relevance)."""
        return self.weight * self.phase_relevance


# ── Source weight constants ────────────────────────────────────────────────────

_W_ERROR_REGISTRY = 0.95   # Bugs we've seen before: highest priority
_W_DOMAIN_PACK    = 0.90   # Must-follow domain rules: nearly as important
_W_KG_PATTERN     = 0.75   # Patterns from similar past runs
_W_KG_FIX         = 0.80   # Known fix patterns from knowledge graph
_W_CTX_WARNING    = 0.50   # Architecture warnings from the current run

_GOLDEN_EXAMPLES_DIR = Path(__file__).parent.parent / "knowledge_graph" / "golden_examples"


def _get_error_registry_knowledge(phase_name: str, domain: str) -> list[RankedKnowledge]:
    """Load recent error categories from the registry and convert to RankedKnowledge items.

    Errors that occurred in the same phase score higher phase_relevance.
    """
    items: list[RankedKnowledge] = []
    try:
        from aether_os.core.error_registry import get_registry

        summary = get_registry().get_summary()
        by_cat = summary.get("by_category", {})
        if not by_cat:
            return items

        # Human-readable explanations keyed by error category
        _RULES: dict[str, str] = {
            "relative_import": (
                "NEVER use relative imports (from .models, from ..X). "
                "Use absolute imports only: from models import X."
            ),
            "ast_parse_failure": (
                "Generated code must be valid Python — no unclosed brackets, "
                "unterminated strings, or broken f-string expressions."
            ),
            "missing_all_routers": (
                "The LAST line of routers/crud.py MUST be: all_routers = [router1, ...]. "
                "main.py iterates this list; missing it causes 404 on every endpoint."
            ),
            "seed_unique_violation": (
                "Every unique field (email, slug, file_path) MUST be distinct per record. "
                "Never repeat admin@example.com across 20 seed rows."
            ),
            "missing_router_reference": (
                "Every APIRouter you create must be in the all_routers list. "
                "Routers not listed are silently dropped."
            ),
        }

        for cat, info in by_cat.items():
            rule = _RULES.get(cat)
            if not rule:
                continue
            count = info.get("count", 0)
            content = f"[past error × {count}] {rule}"
            items.append(RankedKnowledge(
                source="error_registry",
                content=content,
                weight=_W_ERROR_REGISTRY,
                phase_relevance=1.0,
            ))
    except Exception as exc:
        logger.warning("retrieval_ranker: error_registry unavailable (non-fatal): %s", exc)
    return items


def _get_domain_pack_knowledge(domain: str) -> list[RankedKnowledge]:
    """Load domain pack constraints as RankedKnowledge items."""
    items: list[RankedKnowledge] = []
    if not domain:
        return items
    try:
        from aether_os.core.domain_packs import get_domain_pack

        pack = get_domain_pack(domain)
        if pack is None:
            return items
        block = pack.get_constraint_block()
        if block:
            items.append(RankedKnowledge(
                source="domain_pack",
                content=block,
                weight=_W_DOMAIN_PACK,
                phase_relevance=1.0,
            ))
    except Exception as exc:
        logger.warning("retrieval_ranker: domain_pack unavailable (non-fatal): %s", exc)
    return items


def _get_knowledge_graph_knowledge(domain: str) -> list[RankedKnowledge]:
    """Load patterns and fix nodes from the knowledge graph for this domain."""
    items: list[RankedKnowledge] = []
    try:
        from aether_os.core.knowledge_graph import get_singleton, EdgeType

        kg = get_singleton()

        # Collect FIX and CONSTRAINT nodes that carry domain-relevant content
        fix_categories = [
            "relative_import_bug",
            "missing_all_routers",
            "seed_unique_violation",
            "circular_fk_deadlock",
            "sqlalchemy_reserved_name",
        ]
        seen_ids: set[str] = set()
        for cat_id in fix_categories:
            fix_nodes = kg.get_related(cat_id, edge_type=EdgeType.FIXES)
            for node in fix_nodes:
                if node.id in seen_ids:
                    continue
                seen_ids.add(node.id)
                props = node.properties
                rule = props.get("rule", "")
                reason = props.get("reason", "")
                content_parts = [f"[KG:{node.label}]"]
                if rule:
                    content_parts.append(f"Rule: {rule}")
                if reason:
                    content_parts.append(f"Reason: {reason}")
                items.append(RankedKnowledge(
                    source="knowledge_graph_fix",
                    content=" — ".join(content_parts),
                    weight=_W_KG_FIX,
                    phase_relevance=1.0,
                ))

        # Load historical entity patterns for this domain (golden examples)
        from aether_os.core.knowledge_graph import KnowledgeGraph

        patterns = KnowledgeGraph.load_for_domain(domain, limit=3)
        if patterns:
            example_lines = []
            for p in patterns:
                entity_name = p.get("domain", "") or domain
                fields = p.get("fields", [])
                if fields:
                    example_lines.append(
                        f"  Past {entity_name} entity: fields={fields[:6]}"
                    )
            if example_lines:
                content = "Golden examples from similar past runs:\n" + "\n".join(example_lines)
                items.append(RankedKnowledge(
                    source="knowledge_graph_patterns",
                    content=content,
                    weight=_W_KG_PATTERN,
                    phase_relevance=0.85,
                ))
    except Exception as exc:
        logger.warning("retrieval_ranker: knowledge_graph unavailable (non-fatal): %s", exc)
    return items


def _extract_example_entity(ex: dict) -> tuple[str, list[str]]:
    """Extract (entity_name, field_names) from either golden example schema.

    Two schemas exist:
    - Spider/sql-context format: {name, fields: [{name, type}]}
    - Original seed format:      {type, output: {entities: [{name, fields}]}}
    """
    # Spider format
    name = ex.get("name", "")
    fields = ex.get("fields", [])
    if name and fields:
        return name, [f["name"] for f in fields[:6] if isinstance(f, dict) and f.get("name")]

    # Original seed format
    output = ex.get("output", {})
    entities = output.get("entities", [])
    if entities:
        ent = entities[0]
        ent_name = ent.get("name", "")
        ent_fields = [f["name"] for f in ent.get("fields", [])[:6] if isinstance(f, dict) and f.get("name")]
        return ent_name, ent_fields

    return "", []


def _get_golden_examples_knowledge(domain: str, phase_name: str) -> list[RankedKnowledge]:
    """Load pre-seeded golden examples from JSON files for this domain/phase."""
    items: list[RankedKnowledge] = []
    if not _GOLDEN_EXAMPLES_DIR.exists():
        return items
    try:
        domain_file = _GOLDEN_EXAMPLES_DIR / f"{domain}.json"
        if domain_file.exists():
            data = json.loads(domain_file.read_text())
            all_examples = data.get("examples", [])
            # Pick up to 3 examples that have extractable entity data
            lines = []
            for ex in all_examples:
                if len(lines) >= 3:
                    break
                name, field_names = _extract_example_entity(ex)
                if name and field_names:
                    lines.append(f"  {name}: {', '.join(field_names)}")
            if lines:
                items.append(RankedKnowledge(
                    source="golden_examples",
                    content=f"Golden entity examples for {domain}:\n" + "\n".join(lines),
                    weight=_W_KG_PATTERN,
                    phase_relevance=0.90,
                ))

        # Inject relevant bug fixes for code-generation phases
        # Load from all known bug-fix corpus files
        _BUGFIX_FILES = ["bug_fixes.json", "so_bugfix_examples.json"]
        _CODEGEN_PHASES = {"p04a", "p04b", "backend_codegen", "crud", "p04"}
        if phase_name in _CODEGEN_PHASES:
            priority_classes = {"RELATIVE_IMPORT", "SEED_UNIQUENESS", "MISSING_AWAIT",
                                 "ASYNC_SQLALCHEMY", "PYDANTIC_V2", "PYDANTIC_OPTIONAL",
                                 "CORS_MISCONFIGURATION", "JWT_ERROR", "FASTAPI_DEPENDS",
                                 "DETACHED_INSTANCE", "BACKGROUND_TASK_SESSION",
                                 "N_PLUS_ONE_QUERY", "ALEMBIC_CONFLICT"}
            shown = 0
            for fname in _BUGFIX_FILES:
                bug_file = _GOLDEN_EXAMPLES_DIR / fname
                if not bug_file.exists() or shown >= 3:
                    continue
                try:
                    data = json.loads(bug_file.read_text())
                except Exception as exc:
                    logger.warning("retrieval_ranker: failed to load %s: %s", fname, exc)
                    continue
                for fix in data.get("examples", []):
                    if shown >= 3:
                        break
                    # bug_class lives in output.bug_class (original seed schema)
                    output = fix.get("output", {})
                    bug_class = output.get("bug_class", "")
                    if bug_class in priority_classes:
                        error = fix.get("input", {}).get("error", "")
                        fix_code = output.get("fix", "")
                        explanation = output.get("explanation", "")
                        content = f"[Known Fix – {bug_class}] Error: {error} → Fix: {fix_code}"
                        if explanation:
                            content += f" ({explanation})"
                        items.append(RankedKnowledge(
                            source="golden_examples_bugfix",
                            content=content,
                            weight=_W_KG_FIX,
                            phase_relevance=0.85,
                        ))
                        shown += 1

        # Load GitHub entity patterns for relevant phases
        _ENTITY_PHASES = {"p01", "p02", "p03", "p04a", "domain_ir", "entity_extraction"}
        gh_file = _GOLDEN_EXAMPLES_DIR / "github_entity_patterns.json"
        if gh_file.exists() and phase_name in _ENTITY_PHASES:
            try:
                gh_data = json.loads(gh_file.read_text())
                gh_examples = [
                    ex for ex in gh_data.get("examples", [])
                    if ex.get("domain") == domain or domain == ""
                ][:2]
                for ex in gh_examples:
                    entity_name = ex.get("input", {}).get("name", "")
                    output_code = ex.get("output", "")
                    if entity_name and output_code:
                        items.append(RankedKnowledge(
                            source="github_entity_patterns",
                            content=f"[GitHub Pattern – {entity_name}]\n{output_code[:400]}",
                            weight=_W_KG_PATTERN,
                            phase_relevance=0.80,
                        ))
            except Exception as exc:
                logger.warning("retrieval_ranker: github_entity_patterns load failed: %s", exc)
    except Exception as exc:
        logger.warning("retrieval_ranker: golden_examples load failed (non-fatal): %s", exc)
    return items


def _get_architecture_warning_knowledge(ctx: dict) -> list[RankedKnowledge]:
    """Extract architecture_warnings from the current run context."""
    items: list[RankedKnowledge] = []
    try:
        warnings = ctx.get("architecture_warnings", [])
        if not warnings:
            return items
        if isinstance(warnings, list):
            # Only surface the first 5 warnings to keep the prompt lean
            warning_lines = [str(w) for w in warnings[:5]]
            content = "Architecture warnings from this run:\n" + "\n".join(
                f"  - {w}" for w in warning_lines
            )
            omitted = max(0, len(warnings) - 5)
            if omitted:
                content += f"\n  ... [{omitted} more warnings omitted]"
            items.append(RankedKnowledge(
                source="architecture_warnings",
                content=content,
                weight=_W_CTX_WARNING,
                phase_relevance=1.0,
            ))
    except Exception as exc:
        logger.warning("retrieval_ranker: architecture_warnings extraction failed: %s", exc)
    return items


def retrieve_for_phase(
    phase_name: str,
    domain: str,
    ctx: dict,
) -> list[RankedKnowledge]:
    """Assemble and rank knowledge items relevant to this phase + domain.

    Returns a list sorted by descending score (weight × phase_relevance).
    Always fails open — errors from individual sources are logged and skipped.
    """
    all_items: list[RankedKnowledge] = []

    all_items.extend(_get_error_registry_knowledge(phase_name, domain))
    all_items.extend(_get_domain_pack_knowledge(domain))
    all_items.extend(_get_knowledge_graph_knowledge(domain))
    all_items.extend(_get_golden_examples_knowledge(domain, phase_name))
    all_items.extend(_get_architecture_warning_knowledge(ctx))

    # Sort by score descending — highest priority items first
    all_items.sort(key=lambda k: k.score, reverse=True)
    return all_items


def format_for_prompt(
    knowledge: list[RankedKnowledge],
    max_items: int = 5,
) -> str:
    """Format the top-ranked knowledge items as a prompt section string.

    Returns an empty string if knowledge is empty (so callers can guard with `if block:`).
    Only includes items up to max_items to keep the prompt bounded.
    """
    if not knowledge:
        return ""
    top = knowledge[:max_items]
    lines = ["## RELEVANT KNOWLEDGE (ranked by importance):"]
    for item in top:
        source_label = item.source.replace("_", " ").title()
        lines.append(f"\n### [{source_label}]")
        lines.append(item.content)
    return "\n".join(lines)
