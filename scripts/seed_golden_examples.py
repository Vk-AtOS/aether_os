"""Seed golden examples into core/knowledge_graph/golden_examples/.

Standalone script — no aether_os imports required.
Run: python3 scripts/seed_golden_examples.py

Domain data and builder helpers live in seed_golden_helpers.py (split to
keep each file under the 600-line project limit).
"""
from __future__ import annotations
import json
from pathlib import Path

# Domain builders live across two companion modules (split to keep all files
# under the 600-line project limit).
from seed_golden_helpers import (
    _file,
    build_ecommerce,
    build_healthcare,
    build_fintech,
    build_saas,
    build_ai_integrated,
    build_sqla_examples,
    NOW,
)
from seed_golden_extra import build_compact_domains, build_bug_examples

OUT = Path(__file__).parent.parent / "core" / "knowledge_graph" / "golden_examples"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    print("Writing golden examples...")

    ecommerce = build_ecommerce()
    healthcare = build_healthcare()
    fintech = build_fintech()
    saas = build_saas()
    ai_integrated = build_ai_integrated()
    marketplace, erp, government, traditional_erp = build_compact_domains()

    _file(OUT, "ecommerce", ecommerce)
    _file(OUT, "healthcare", healthcare)
    _file(OUT, "fintech", fintech)
    _file(OUT, "saas", saas)
    _file(OUT, "ai_integrated", ai_integrated)
    _file(OUT, "marketplace", marketplace)
    _file(OUT, "erp", erp)
    _file(OUT, "government", government)
    _file(OUT, "traditional_erp", traditional_erp)

    sqla = build_sqla_examples()
    (OUT / "sqlalchemy_models.json").write_text(json.dumps(sqla, indent=2))
    print(f"  sqlalchemy_models.json: {len(sqla['examples'])} examples")

    bug_examples = build_bug_examples()
    bugs_file = {
        "domain": "cross_domain",
        "version": "1.0",
        "generated_at": NOW,
        "examples": bug_examples,
    }
    (OUT / "bug_fixes.json").write_text(json.dumps(bugs_file, indent=2))
    print(f"  bug_fixes.json: {len(bug_examples)} examples")

    total = (
        sum(len(d) for d in [ecommerce, healthcare, fintech, saas, ai_integrated,
                              marketplace, erp, government, traditional_erp])
        + len(sqla["examples"])
        + len(bug_examples)
    )
    print(f"\nDone. Total examples: {total}")


if __name__ == "__main__":
    main()
