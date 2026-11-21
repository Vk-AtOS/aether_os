"""Drop model-written IR items that have no usable name (seen with a real model, AWS testbed, 21 Nov 2026).

A notification without an "event" (or a workflow without an "entity") cannot become a template or a state machine,
and p04b's safe-name check rightly refuses the WHOLE spec when it meets one (phases/p04b_business_logic/safe_names.py).
An empty name is an incomplete item, not an attack, so it is dropped here with a warning; any non-empty name still goes
to p04b's check unchanged, so a name like "../x" is still refused there, never cleaned up.
"""
from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)


def drop_unnamed(items: Any, key: str, kind: str) -> List[Any]:
    """Items whose `key` is missing or blank are dropped (logged); everything else is returned as it was."""
    kept: List[Any] = []
    for item in items or []:
        if isinstance(item, dict) and not str(item.get(key) or "").strip():
            logger.warning("domain IR: dropping a %s without a %s: %.120s", kind, key, item)
            continue
        kept.append(item)
    return kept
