"""The component names a model-written page may import from '@/components/ui/*', read from the generated sources.

The entity-page prompt said "Button, Card, Input, Table, Modal" and nothing else, so the model invented the rest
(AlertDialogFooter, Select props that did not exist) and those pages were rejected or crashed (KAN-252, run 27).
The list is computed from the same generators that write the files, so it cannot drift from what exists.
"""
from __future__ import annotations

import re
from functools import lru_cache

_EXPORT = re.compile(r"^export (?:const|function) ([A-Z]\w*)", re.M)


@lru_cache(maxsize=1)
def ui_catalog() -> str:
    """'Button: Button; Card: Card, CardHeader, ...' for every ui file the generator writes."""
    from aether_os.phases.p05_frontend import code_writer as cw
    from aether_os.phases.p05_frontend.ui_primitives import UI_PRIMITIVES
    sources = {name: getattr(cw, f"generate_ui_{name.lower()}")() for name in
               ("Button", "Input", "Card", "Badge", "Skeleton", "Modal", "Select", "Toast", "Tooltip", "Table")}
    for text, main in UI_PRIMITIVES.values():       # written only when the generator above did not write that file
        if main:
            sources.setdefault(main, text)
    return "; ".join(f"{file}: {', '.join(dict.fromkeys(_EXPORT.findall(text)))}"
                     for file, text in sorted(sources.items()) if _EXPORT.search(text))
