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


_NON_IDENT = re.compile(r"[^a-z0-9]+")
# Path syntax or a code-injection shape in an event name looks like an injected spec, not a sentence: leave it for the
# check to refuse. A quoted value in a condition ("Task.status != 'done'", production run 18) is a sentence.
_HOSTILE = re.compile(r"[/\\`]|\.\.|['\"]\s*[);]|;\s*(?:import|from|exec|eval)\b|__\w+__")


def _event_identifier(text: str) -> str:
    slug = _NON_IDENT.sub("_", text.lower()).strip("_")[:63].rstrip("_")
    if slug and slug[0].isdigit():
        slug = f"event_{slug}"[:63]
    return slug


def normalise_event_names(ir: Dict[str, Any]) -> List[tuple]:
    """Turn notification events the model wrote as sentences into identifiers, keeping the sentence as `trigger`.

    The model describes events as conditions ("Task.assignee_id changed from null to user", "Daily cron:
    Task.due_date < CURRENT_DATE"); check_logic_names rightly refused those, so production acceptance run 16
    (22 Nov 2026) got no notifications at all (KAN-218). The slug keeps only [a-z0-9_], so the file-name and source
    safety of check_logic_names is unchanged; names with path or code syntax are not renamed and are refused there. Returns
    the (old, new) renames.
    """
    renamed: List[tuple] = []
    seen: set = set()
    for notif in ir.get("notifications") or []:
        if not isinstance(notif, dict):
            continue
        event = notif.get("event", "notification")
        if not isinstance(event, str):
            continue
        if _HOSTILE.search(event):
            seen.add(event)
            continue
        name = event if _IDENT.match(event) else _event_identifier(event)
        base, n = name, 2
        while name and name in seen:
            name = f"{base[:60]}_{n}"
            n += 1
        if name and name != event:
            notif.setdefault("trigger", event)
            notif["event"] = name
            renamed.append((event, name))
        seen.add(name)
    return renamed


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
