#!/usr/bin/env python3.11
"""Convert public SQL datasets into AetherOS golden examples format.

Source: b-mc2/sql-create-context (HuggingFace, 78K rows, no auth required).
Each row has a `context` field with one or more CREATE TABLE statements.
We parse the tables, map SQL types to SQLAlchemy types, infer domain from
table/column names, deduplicate by table name, and merge into
core/knowledge_graph/golden_examples/*.json.

Usage:
    python3.11 scripts/spider_to_golden_examples.py
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

OUTPUT_DIR = Path("core/knowledge_graph/golden_examples")

_JUNK_RE = re.compile(r'^Table\d+$', re.IGNORECASE)

# SQL type → SQLAlchemy type
_TYPE_MAP: dict[str, str] = {
    "integer":   "Integer",
    "int":       "Integer",
    "bigint":    "Integer",
    "smallint":  "Integer",
    "tinyint":   "Integer",
    "number":    "Integer",
    "numeric":   "Float",
    "decimal":   "Float",
    "real":      "Float",
    "float":     "Float",
    "double":    "Float",
    "text":      "String",
    "varchar":   "String",
    "char":      "String",
    "string":    "String",
    "nvarchar":  "String",
    "boolean":   "Boolean",
    "bool":      "Boolean",
    "date":      "Date",
    "time":      "Time",
    "datetime":  "DateTime",
    "timestamp": "DateTime",
    "json":      "JSON",
    "jsonb":     "JSON",
    "blob":      "LargeBinary",
}

# Domain keyword rules (first match wins)
_DOMAIN_RULES: list[tuple[list[str], str]] = [
    (["hospital", "patient", "doctor", "medical", "clinic", "health", "nurse",
      "drug", "pharmacy", "diagnos", "treatment", "prescription"],
     "healthcare"),
    (["product", "order", "cart", "inventory", "store", "shop", "sale",
      "retail", "ecomm", "catalog", "shipment", "warehouse"],
     "ecommerce"),
    (["bank", "account", "transaction", "fund", "financ", "invest", "loan",
      "credit", "payment", "wallet", "ledger", "balance", "transfer"],
     "fintech"),
    (["employee", "department", "payroll", "staff", "salary", "attendance",
      "leave", "hr", "recruit", "hire"],
     "erp"),
    (["election", "government", "city", "county", "nation", "state", "voter",
      "congress", "policy", "permit", "official"],
     "government"),
    (["restaurant", "food", "menu", "recipe", "dish", "ingredient", "chef",
      "cuisine", "meal", "drink"],
     "marketplace"),
    (["student", "course", "class", "school", "university", "college",
      "professor", "grade", "enroll", "teach", "semester"],
     "saas"),
    (["flight", "airline", "airport", "travel", "hotel", "booking",
      "reservation", "ticket", "cruise", "tour"],
     "marketplace"),
    (["vendor", "seller", "buyer", "listing", "bid", "auction",
      "marketplace", "gig", "freelan"],
     "marketplace"),
    (["supply", "manufactur", "logistics", "procure", "mrp", "bom",
      "assembly", "component"],
     "traditional_erp"),
    (["ai", "model", "ml", "predict", "train", "infer", "embed",
      "vector", "agent", "pipeline", "feature"],
     "ai_integrated"),
]


def _infer_domain(table_name: str, col_names: list[str]) -> str:
    text = (table_name + " " + " ".join(col_names)).lower()
    for keywords, domain in _DOMAIN_RULES:
        if any(k in text for k in keywords):
            return domain
    return "saas"


def _sa_type(sql_type: str) -> str:
    base = sql_type.lower().split("(")[0].strip()
    return _TYPE_MAP.get(base, "String")


def _pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


# ── CREATE TABLE parser ───────────────────────────────────────────────────────

_CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?(\w+)[`\"\]]?\s*\((.+?)\)",
    re.IGNORECASE | re.DOTALL,
)
_PK_RE = re.compile(r"\bPRIMARY\s+KEY\b", re.IGNORECASE)
_FK_RE = re.compile(r"\bREFERENCES\b", re.IGNORECASE)
_CONSTRAINT_RE = re.compile(
    r"^\s*(CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|INDEX)",
    re.IGNORECASE,
)


def _parse_create_tables(sql: str) -> list[dict]:
    """Return list of {name, fields} dicts parsed from CREATE TABLE statements."""
    tables = []
    for m in _CREATE_RE.finditer(sql):
        table_name = m.group(1)
        body = m.group(2)

        fields = []
        for line in body.split(","):
            line = line.strip()
            if not line or _CONSTRAINT_RE.match(line):
                continue
            # Column definition: name type [constraints...]
            parts = line.split()
            if len(parts) < 2:
                continue
            col_name = parts[0].strip("`\"[]")
            col_type = parts[1]
            if col_name.upper() in ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "INDEX", "KEY"):
                continue
            fields.append({
                "name":        col_name,
                "type":        _sa_type(col_type),
                "primary_key": _PK_RE.search(line) is not None,
                "foreign_key": _FK_RE.search(line) is not None,
            })

        if len(fields) >= 2:
            tables.append({"name": table_name, "fields": fields})

    return tables


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading b-mc2/sql-create-context from HuggingFace (~78K rows)...")
    from datasets import load_dataset  # noqa: PLC0415

    ds = load_dataset("b-mc2/sql-create-context", split="train")
    print(f"  {len(ds)} rows loaded")

    # ── Parse and deduplicate by table name ───────────────────────────────────
    seen_tables: dict[str, dict] = {}
    for row in ds:
        context: str = row.get("context", "")
        if not context:
            continue
        for table in _parse_create_tables(context):
            name = table["name"]
            if name.upper() in ("HEAD", "REF", "LOG", "DATA", "TEMP", "TMP"):
                continue  # skip generic names that pollute results
            if name not in seen_tables:
                seen_tables[name] = table

    print(f"  {len(seen_tables)} unique tables extracted")

    # ── Group by inferred domain ───────────────────────────────────────────────
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for tbl_name, table in seen_tables.items():
        col_names = [f["name"] for f in table["fields"]]
        domain = _infer_domain(tbl_name, col_names)
        by_domain[domain].append({
            "name":   _pascal(tbl_name),
            "domain": domain,
            "source": "sql-create-context",
            "fields": table["fields"],
        })

    # ── Merge into existing JSON files ────────────────────────────────────────
    total_new = 0
    for domain, new_examples in sorted(by_domain.items()):
        domain_file = OUTPUT_DIR / f"{domain}.json"
        if domain_file.exists():
            existing = json.loads(domain_file.read_text())
        else:
            existing = {"domain": domain, "examples": []}

        existing_names = {e["name"] for e in existing.get("examples", []) if "name" in e}
        added = 0
        for ex in new_examples:
            if _JUNK_RE.match(ex["name"]):
                continue  # skip Wikipedia auto-named tables
            if ex["name"] not in existing_names:
                existing.setdefault("examples", []).append(ex)
                existing_names.add(ex["name"])
                added += 1

        domain_file.write_text(json.dumps(existing, indent=2))
        total = len(existing["examples"])
        print(f"  {domain}.json: +{added} new  (total {total})")
        total_new += added

    # ── Grand total ───────────────────────────────────────────────────────────
    grand_total = sum(
        len(json.loads(f.read_text()).get("examples", []))
        for f in OUTPUT_DIR.glob("*.json")
    )
    print(f"\nDone. +{total_new} examples added from sql-create-context.")
    print(f"Grand total across all golden example files: {grand_total}")


if __name__ == "__main__":
    main()
