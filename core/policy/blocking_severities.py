"""Which finding severities block delivery (KAN-99).

Default: critical and high block, medium and low only warn. The operator can change it with
AETHER_BLOCKING_SEVERITIES (comma list, e.g. "critical" or "critical,high,medium").
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT = ("critical", "high")
_VALID = {"critical", "high", "medium", "low"}


def blocking_severities() -> tuple[str, ...]:
    raw = os.environ.get("AETHER_BLOCKING_SEVERITIES", "").strip()
    if not raw:
        return _DEFAULT
    chosen = tuple(s for s in (p.strip().lower() for p in raw.split(",")) if s in _VALID)
    if not chosen:
        logger.warning("AETHER_BLOCKING_SEVERITIES=%r has no valid severity; using %s", raw, _DEFAULT)
        return _DEFAULT
    return chosen


def blocks(severity: str) -> bool:
    return str(severity or "").lower() in blocking_severities()
