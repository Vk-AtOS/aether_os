"""Names from the model-written IR that p04b turns into file names and Python source (KAN-69 G6).

A workflow entity becomes `workflows/<entity>_sm.py` and a class name, a notification event becomes
`templates/emails/<event>.html`. `../../x` would write outside the run directory and a quote would close a string in
the generated source, so such a spec is refused, never escaped (same rule as p04a's check_identifiers).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def check_logic_names(ir: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for wf in ir.get("workflows") or []:
        entity = wf.get("entity", "Entity") if isinstance(wf, dict) else None
        if not (isinstance(entity, str) and _IDENT.match(entity)):
            errors.append(f"unsafe_name: workflow entity {str(entity)[:40]!r} is not a plain identifier")
    for notif in ir.get("notifications") or []:
        event = notif.get("event", "notification") if isinstance(notif, dict) else None
        if not (isinstance(event, str) and _IDENT.match(event)):
            errors.append(f"unsafe_name: notification event {str(event)[:40]!r} is not a plain identifier")
    return errors


def write_inside(base: Path, name: str, text: str) -> None:
    """Write base/name; refuse a target that resolves outside `base`."""
    target = (base / name).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ValueError(f"refusing to write outside {base}: {name!r}")
    target.write_text(text)
