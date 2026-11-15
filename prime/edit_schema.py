"""Prime — what may be edited on a pending request, per action type (KAN-22).

Only parameters named here can change. Parameters bound to something else (a Velaris
call_hash, a run's spec hash, a webhook id) are not editable: submit a new request instead.
"""
from __future__ import annotations

from typing import Any, Dict

from aether_os.prime.authz import ACTION_TYPES, CURRENCY

# action type -> editable parameter -> (python type, bound). int bound = (min, max); str bound = max length.
EDITABLE_PARAMS: Dict[str, Dict[str, tuple]] = {
    "leave.approve": {"days": (int, (1, 365)), "note": (str, 500)},
    "invoice.approve": {"note": (str, 500), "invoice_ref": (str, 100)},
    "expense.approve": {"note": (str, 500), "expense_ref": (str, 100)},
    "payment.execute": {"note": (str, 500), "reference": (str, 100)},
    "deploy.staging": {"note": (str, 500)},
}


def editable_fields(action_type: str) -> Dict[str, Any]:
    """The edit schema shown to the dashboard: field -> type and bound; `amount` for money."""
    out: Dict[str, Any] = {k: {"type": t.__name__, "bound": b} for k, (t, b) in
                           EDITABLE_PARAMS.get(action_type, {}).items()}
    if ACTION_TYPES.get(action_type):
        out["amount"] = {"type": "decimal", "currency": CURRENCY}
    return out


def coerce(name: str, value: Any, kind: type, bound: Any) -> Any:
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, int) or not bound[0] <= value <= bound[1]:
            raise ValueError(f"'{name}' must be a whole number from {bound[0]} to {bound[1]}")
    elif not isinstance(value, str) or len(value) > bound:
        raise ValueError(f"'{name}' must be text of at most {bound} characters")
    return value


