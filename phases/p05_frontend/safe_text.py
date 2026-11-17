"""Text from a spec (project name, tagline, service names) is written into HTML, JSX, JSON and JS strings of the
generated frontend. One function keeps it inert in all of them (KAN-168): the name `x</title><script>...` used to
become a script in index.html."""
from __future__ import annotations

import re

_DROP = re.compile(r"[<>{}\\`$\x00-\x1f\x7f]")


def safe_display_name(value: object, default: str = "App", max_len: int = 80) -> str:
    """Keep the readable part of a name. `<>{}\\`$` and control characters are dropped, quotes become typographic
    quotes and `&` becomes "and", so the result is safe inside JSX text, HTML attributes, JSON and single- or
    double-quoted JS strings alike."""
    text = str(value or "")
    text = text.replace("'", "’").replace('"', "”").replace("&", " and ")
    text = _DROP.sub("", text)
    return re.sub(r"\s+", " ", text).strip()[:max_len] or default


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def check_entity_names(entities: list) -> list:
    """Table, entity and column names become TSX identifiers, object keys and route paths in the generated frontend
    (KAN-69 G5), so each must be a plain identifier: the same rule p04a applies on the backend side. Returns the
    problems (empty = fine); the caller refuses the spec, nothing is escaped."""
    errors: list = []

    def bad(kind: str, value: object) -> None:
        if not (isinstance(value, str) and _IDENT.match(value)):
            errors.append(f"unsafe_name: {kind} {str(value)[:40]!r} is not a plain identifier")

    for e in entities or []:
        if not isinstance(e, dict):
            errors.append("unsafe_name: an entity is not an object")
            continue
        for key in ("table", "name"):
            if e.get(key) not in (None, ""):
                bad(f"{key} name", e[key])
        for col in (e.get("columns") or e.get("fields") or e.get("attributes") or []):
            name = col.get("name", col.get("column")) if isinstance(col, dict) else col
            if name not in (None, ""):
                bad("column name", name)
    return errors
