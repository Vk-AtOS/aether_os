"""Parse an RFC 7644 PatchOp body the way Okta and Microsoft Entra actually send it.

Okta:  {"op": "replace", "value": {"active": false}}            (no path, value is an object)
Entra: {"op": "Replace", "path": "active", "value": "False"}    (capitalised op, boolean as a string)
"""
from __future__ import annotations

from typing import Any, Iterator, List, Tuple

PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
_OPS = {"add", "replace", "remove"}


class ScimError(Exception):
    """Rendered by the app-level handler as an RFC 7644 3.12 error body (top level, not under "detail")."""

    def __init__(self, status: int, detail: str, scim_type: str = "") -> None:
        super().__init__(detail)
        self.status = status
        self.body = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"], "status": str(status),
                     "detail": detail, **({"scimType": scim_type} if scim_type else {})}


def scim_error(status: int, detail: str, scim_type: str = "") -> ScimError:
    return ScimError(status, detail, scim_type)


def operations(body: Any) -> List[Tuple[str, str, Any]]:
    """[(op, path-or-"", value)] with op lower-cased; 400 for a malformed request."""
    if not isinstance(body, dict) or not isinstance(body.get("Operations"), list) or not body["Operations"]:
        raise scim_error(400, "Operations is required", "invalidSyntax")
    out = []
    for item in body["Operations"]:
        op = str((item or {}).get("op", "")).lower() if isinstance(item, dict) else ""
        if op not in _OPS:
            raise scim_error(400, f"Unsupported op {item.get('op') if isinstance(item, dict) else item!r}", "invalidSyntax")
        out.append((op, str(item.get("path") or ""), item.get("value")))
    return out


def attribute_changes(ops: List[Tuple[str, str, Any]]) -> Iterator[Tuple[str, str, Any]]:
    """Flatten no-path object values into (op, attribute, value), attribute lower-cased."""
    for op, path, value in ops:
        if not path and isinstance(value, dict):
            for key, v in value.items():
                yield op, key.lower(), v
        else:
            yield op, path.lower(), value


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise scim_error(400, f"Expected a boolean, got {value!r}", "invalidValue")
