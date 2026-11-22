"""One normalisation of the spec's entity list, shared by every codegen phase (KAN-209).

The architecture step lists entities as class names ("Task"), table names ("users") or dicts. p04a, p07a and p07b
each handled that differently (a bare string crashed p04a's generators with "'str' object has no attribute 'get'",
and using the label as the class name gave `models.users` / `/api/projectss`, production acceptance run 13).
Every phase now calls normalise_entities once and gets {"name": "User", "table": "users", ...} dicts.
"""
from __future__ import annotations

import os
import re
from typing import Any

ENV_FLAG = "CODEGEN_TEMPLATES_FIRST"


def templates_first_enabled() -> bool:
    """CODEGEN_TEMPLATES_FIRST (default on): fixed-shape files come from deterministic generators, never a model.
    Set to 0/false/off to run the previous path for comparison."""
    return os.environ.get(ENV_FLAG, "1").strip().lower() not in ("0", "false", "off", "no", "")


def _singular(word: str) -> str:
    w = word.lower()
    if w.endswith("ies") and len(w) > 3:
        return word[:-3] + "y"
    if w.endswith(("sses", "uses", "xes", "ches", "shes", "zes")):
        return word[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def entity_from_label(label: str) -> dict:
    """A bare entity label as the generators expect it: class name singular PascalCase, table plural snake_case.

    The architecture step lists either class names ("Task") or table names ("users"). Using the label as the class name
    produced `models.users` / `userss_router` in p07b's fallback and `/api/projectss` in p07a's tests (production
    acceptance run 13, 22 Nov 2026): the fallback broke a backend s03 had validated, and the CRUD tests hit 404.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])", label) if w]
    if not words:
        return {"name": "Item", "table": "items"}
    words[-1] = _singular(words[-1])
    name = "".join(w[:1].upper() + w[1:].lower() for w in words)
    last = words[-1].lower()
    plural = last[:-1] + "ies" if last.endswith("y") and last[-2:-1] not in "aeiou" else (
        last + "es" if last.endswith(("s", "x", "ch", "sh", "z")) else last + "s")
    table = "_".join([w.lower() for w in words[:-1]] + [plural])
    return {"name": name, "table": table}


def normalise_entities(raw: Any, drop_auth_user: bool = False) -> list:
    """Entities as dicts. Dicts pass through unchanged (a missing table is derived from the name); bare labels become
    {"name", "table"}; duplicates by class name and anything else are dropped.
    drop_auth_user: also drop "User". The generated backend always has its own users table (auth); an entity named
    User made models.py declare it twice and the app failed to import ("Table 'users' is already defined")."""
    if not isinstance(raw, list):
        return []
    out: list = []
    seen: set = set()
    for e in raw:
        if isinstance(e, str) and e.strip():
            e = entity_from_label(e.strip())
        elif isinstance(e, dict) and e.get("name"):
            if not e.get("table"):
                e = {**e, "table": entity_from_label(str(e["name"]))["table"]}
        else:
            continue
        if e["name"] in seen or (drop_auth_user and e["name"] == "User"):
            continue
        seen.add(e["name"])
        out.append(e)
    return out
