"""Prime — the full context of one approval request: what an approver needs to decide.

Built only from stored facts and the tables in prime/authz.py (no model, no I/O of its own
beyond the ledger read). Personal data in the parameters is pseudonymised unless the viewer
holds a role that may see it; credentials are masked everywhere.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from aether_os.core.audit import subjects
from aether_os.core.security.redact import redact_secrets
from aether_os.prime.authz import (
    ACTION_TYPES, AUTHORITY, CURRENCY, EXECUTOR_AUTHORITY, EXTERNAL_EFFECT, HARD_PAYMENT_CEILING,
    NEVER, OWNER_ADMIN, AutonomyLevel, Delegation, needs_second_person,
)
from aether_os.prime.ledger_view import by_request
from aether_os.prime.limits import get_limits
from aether_os.prime.models import PrimeRequest

# Parameter names that carry personal data, and what kind. Matching is on the lower-cased key.
PERSONAL_KEYS: Dict[str, str] = {
    "employee": "identity", "employee_id": "identity", "employee_name": "identity", "name": "identity",
    "email": "contact", "phone": "contact", "mobile": "contact",
    "pan": "identity", "aadhaar": "identity", "passport": "identity",
    "bank_account": "bank", "account_number": "bank", "ifsc": "bank", "salary": "pay",
    "diagnosis": "health", "medical": "health", "candidate": "candidate",
}
# Roles that may see those values in clear (the same roles that hold authority over the money
# and leave actions in AUTHORITY).
MAY_SEE_PERSONAL = OWNER_ADMIN
logger = logging.getLogger(__name__)
_SHOWN_LEDGER_KEYS = ("status", "reason", "answer", "idempotency_key", "execution")


async def pseudonym(org_id: str, value: Any) -> str:
    """Stable label for a value inside one organisation (keyed HMAC, core/audit/subjects.py).
    If the key cannot be had nothing about the value is shown."""
    try:
        return await subjects.label(org_id, value)
    except Exception as e:
        logger.warning("prime: pseudonym key unavailable for %s: %s", org_id, type(e).__name__)
        return subjects.WITHHELD


def risk_class(action_type: str, executor: str, amount: Optional[Decimal]) -> str:
    """critical: never approvable; high: money or an effect outside AetherOS; standard otherwise."""
    if action_type in NEVER or action_type not in ACTION_TYPES:
        return "critical"
    if needs_second_person(action_type, executor):
        return "high"
    return "standard"


async def data_touched(org_id: str, params: Dict[str, Any], can_see: bool) -> List[Dict[str, Any]]:
    """Which personal-data fields the request carries; values only when `can_see`."""
    out = []
    for key in sorted(params):
        kind = PERSONAL_KEYS.get(str(key).lower())
        if kind:
            value = redact_secrets(params[key], limit=200) if can_see else await pseudonym(org_id, params[key])
            out.append({"field": key, "kind": kind, "value": value, "pseudonymised": not can_see})
    return out


async def mask_params(org_id: str, params: Dict[str, Any], pseudonymise: bool) -> Dict[str, Any]:
    """params as shown: credential-looking text masked for everyone, personal-data values
    replaced by their pseudonym for viewers who may not see them. Display only: the request
    hash is over the stored params."""
    out: Dict[str, Any] = {}
    for k, v in params.items():
        if pseudonymise and str(k).lower() in PERSONAL_KEYS:
            out[k] = await pseudonym(org_id, v)
        else:
            out[k] = redact_secrets(v, limit=2000) if isinstance(v, str) else v
    return out


def eligible_roles(action_type: str, executor: str) -> List[str]:
    roles = AUTHORITY.get(action_type, frozenset())
    if executor in EXECUTOR_AUTHORITY:
        roles = roles & EXECUTOR_AUTHORITY[executor]
    else:
        roles = frozenset()
    return sorted(roles)


def _policy(row: PrimeRequest, delegation: Optional[Delegation]) -> Dict[str, Any]:
    """Why approval was needed, from the delegation's autonomy level and the authority tables."""
    level = None
    if delegation is not None:
        level = {"level": int(delegation.autonomy), "name": AutonomyLevel(delegation.autonomy).name}
    return {
        "source": "prime.authz",
        "outcome": row.outcome, "reason": row.reason,
        "autonomy": level,
        "in_delegation_scope": bool(delegation and row.action_type in delegation.scope),
        "second_person_required": needs_second_person(row.action_type, row.executor),
        "external_effect": row.executor in EXTERNAL_EFFECT,
    }


async def _money(row: PrimeRequest, delegation: Optional[Delegation]) -> Optional[Dict[str, Any]]:
    if row.amount is None:
        return None
    amount = Decimal(row.amount)
    org = (await get_limits(row.org_id)).payment_ceiling
    cap = delegation.limits.max_amount if delegation and delegation.limits else None
    return {"amount": row.amount, "currency": row.currency or CURRENCY,
            "delegation_limit": str(cap) if cap is not None else None,
            "within_delegation_limit": cap is not None and amount <= cap,
            "org_payment_ceiling": str(org), "hard_ceiling": str(HARD_PAYMENT_CEILING),
            "counted_against": "delegation" if cap is not None else "org_payment_ceiling"}


def _timeline(entries: List[Dict[str, Any]], can_see: bool) -> List[Dict[str, Any]]:
    out = []
    for e in entries:
        p = e["payload"]
        item = {"seq": e["seq"], "timestamp": e["timestamp"], "actor": e["actor"], "action": e["action"]}
        item.update({k: redact_secrets(p[k], limit=300) for k in _SHOWN_LEDGER_KEYS
                     if k in p and isinstance(p[k], (str, int, float, bool))})
        if can_see and p.get("authority"):
            item["authority"] = p["authority"]
        out.append(item)
    return out


async def build(row: PrimeRequest, delegation: Optional[Delegation], viewer_role: Optional[str]) -> Dict[str, Any]:
    can_see = viewer_role in MAY_SEE_PERSONAL
    return {
        "risk_class": risk_class(row.action_type, row.executor, None),
        "policy": _policy(row, delegation),
        "money": await _money(row, delegation),
        "data_touched": await data_touched(row.org_id, row.params or {}, can_see),
        "eligible_roles": eligible_roles(row.action_type, row.executor),
        "ledger": _timeline(await by_request(row.org_id, row.id), can_see),
        "revision": getattr(row, "revision", 0) or 0,
    }
