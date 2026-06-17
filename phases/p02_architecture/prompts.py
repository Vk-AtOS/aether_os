"""P02 Architecture — prompt strings and templates.

Contains: the LLM prompt builder for architecture generation and
the spec noun extractor used to validate entity coverage.
"""
from __future__ import annotations
import json
import re
from typing import List


def build_arch_prompt(
    requirements: str,
    stack_hint: str,
    profile_name: str,
    preferred_db: str,
    suggested_tech_stack: dict,
    required_patterns: list,
    security_requirements: list,
    example_entities: list,
    similar_context: str = "",
    memory_hint: str = "",
) -> str:
    """Build the LLM prompt for architecture generation."""
    return (
        f"Design a complete software architecture for the following requirements.\n\n"
        f"=== FULL REQUIREMENTS (read carefully) ===\n{requirements}\n"
        f"=== END REQUIREMENTS ===\n\n"
        f"CRITICAL INSTRUCTIONS:\n"
        f"1. Extract ALL entity names from the spec above.\n"
        f"2. Define a database table for EACH entity with appropriate columns and FK relationships.\n"
        f"3. Define API endpoints for each entity's CRUD operations PLUS domain-specific operations.\n"
        f"4. Validate that every must-have feature in the spec is represented in the architecture output.\n"
        f"5. Do NOT generate only a generic 'items' entity — the schema must reflect the actual domain.\n\n"
        f"Domain: {profile_name}\n"
        f"Preferred Database: {preferred_db}\n"
        f"Suggested Stack: {json.dumps(suggested_tech_stack)}\n"
        f"Mandatory Patterns: {', '.join(required_patterns)}\n"
        f"Security: {', '.join(security_requirements)}\n"
        f"Example Entities to consider: {', '.join(example_entities)}\n"
        f"{stack_hint}"
        f"{similar_context}"
        f"{memory_hint}"
        f"\nFocus on: tech stack choices, database schema, API endpoints, security."
    )


def extract_spec_nouns(text: str) -> List[str]:
    """Extract distinct candidate entity nouns from spec must-have features."""
    # Grab lines that look like requirements/features
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    nouns: List[str] = []
    _stop = {"the", "and", "for", "are", "with", "that", "this", "from", "have",
             "will", "can", "but", "not", "build", "create", "make", "using",
             "api", "app", "rest", "web", "system", "service", "python", "fastapi",
             "django", "must", "should", "able", "each", "every", "user", "users",
             "data", "based", "support", "include", "provide"}
    for line in lines[:40]:
        words = re.findall(r'\b([A-Za-z]{4,})\b', line)
        for w in words:
            lw = w.lower()
            if lw not in _stop:
                nouns.append(lw.rstrip("s"))  # rough singular
    # Deduplicate preserving order
    seen: set = set()
    result = []
    for n in nouns:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result[:20]
