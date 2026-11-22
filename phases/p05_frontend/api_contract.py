"""P05: deterministic post-check that a model-written entity page reads the backend's list shape.

The backend list endpoints return {items, total, page, page_size, limit} (PaginatedResponse). Models keep inventing
`{ data: T[]; total }` response types and render `data?.data.map(...)`; each page type-checks against its own wrong
type, so tsc cannot catch it and the page crashes at runtime (run 20: ProjectPage, TaskPage). This module rewrites the
known wrong spellings to `.items`, and reports pages it cannot make safe so the caller falls back to the template page.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# `data: Project[]; total` inside a type literal or interface: the paginated body with the wrong row field name.
_BAD_LIST_FIELD = re.compile(r"\bdata(\??\s*:\s*[A-Za-z_][\w.<>]*\[\]\s*[;,]?\s*total\b)")
_DATA_DATA = re.compile(r"\.data(\?)?\.data\b")
# `tasksData?.data.map(` where tasksData is the list response (only rewritten when the page declared the wrong type).
_RESPONSE_DATA_USE = re.compile(r"(\w)(\?)?\.data(\??)\.(map|length|filter|find|slice|some|every|reduce|forEach|flatMap)\b")
_LOCAL_LIST_TYPE = re.compile(r"\b(?:interface|type)\s+\w*(?:List|Paginat)\w*(?:Response)?\b[^{=]*[={]\s*\{?[^}]*\bdata\??\s*:", re.S)


def _has_wrong_declared_type(code: str) -> bool:
    return bool(_BAD_LIST_FIELD.search(code))


def enforce_list_contract(code: str, page_name: str = "") -> Optional[str]:
    """Return code that reads `.items`, or None when the page still assumes a `.data` list and must be regenerated."""
    fixed = code
    declared_wrong = _has_wrong_declared_type(fixed)
    fixed = _BAD_LIST_FIELD.sub(r"items\1", fixed)
    fixed = _DATA_DATA.sub(lambda m: f".data{m.group(1) or ''}.items", fixed)
    if declared_wrong:
        # An axios `res.data` array is legitimate elsewhere, so only touch `x.data.map` when this page used the wrong type.
        fixed = _RESPONSE_DATA_USE.sub(lambda m: f"{m.group(1)}{m.group(2) or ''}.items", fixed)
    if _DATA_DATA.search(fixed) or _LOCAL_LIST_TYPE.search(fixed):
        logger.warning("p05: %s still assumes a `.data` list after contract fix; falling back to template", page_name)
        return None
    if fixed != code:
        logger.info("p05: %s rewritten to the backend list shape (.items)", page_name)
    return fixed
