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
