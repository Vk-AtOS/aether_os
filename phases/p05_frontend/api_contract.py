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


# `queryFn: () => apiClient.get(...)` resolves to the axios RESPONSE, so the page's `data.items` is undefined and the page
# crashes (production run 21: ProjectPage fetched users this way). The typed helpers already end in .then(r => r.data).
_RAW_QUERY_CALL = re.compile(r"queryFn\s*:\s*(?:async\s*)?\(\s*\)\s*=>\s*apiClient\.(get|post)\(")
# `tasksData?.items.length`: the optional chain stops before .items, so an undefined body crashes the page.
_ITEMS_UNGUARDED = re.compile(r"\?\.items\.(?=[A-Za-z_])")


def _close_paren(code: str, open_idx: int) -> int:
    """Index just past the parenthesis matching code[open_idx] == '(' (string literals skipped), or -1."""
    depth, i, quote = 0, open_idx, None
    while i < len(code):
        c = code[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def unwrap_raw_query_calls(code: str) -> str:
    """Append .then(r => r.data) to raw apiClient calls used directly as a react-query queryFn."""
    out, pos = [], 0
    for m in _RAW_QUERY_CALL.finditer(code):
        end = _close_paren(code, m.end() - 1)
        if end < 0 or end <= pos:
            continue
        if code[end:end + 6].startswith(".then"):
            continue
        out.append(code[pos:end])
        out.append(".then(r => r.data)")
        pos = end
    out.append(code[pos:])
    return "".join(out)


def _has_wrong_declared_type(code: str) -> bool:
    return bool(_BAD_LIST_FIELD.search(code))


def enforce_list_contract(code: str, page_name: str = "") -> Optional[str]:
    """Return code that reads `.items`, or None when the page still assumes a `.data` list and must be regenerated."""
    fixed = unwrap_raw_query_calls(code)
    fixed = _ITEMS_UNGUARDED.sub("?.items?.", fixed)
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
