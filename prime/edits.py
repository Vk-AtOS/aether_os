"""Prime — edit a pending request before it is approved (KAN-22).

An approval is bound to the request hash, so an approver approves exactly what they saw.
An edit therefore makes a NEW revision: the amount and the editable parameters change, the
hash is recomputed, and any decision that quotes the old hash is refused (409). The edit
is ledgered first (who, before, after, why). The editor becomes a contributor and can never
decide the request; the rules for a second person, authority, the amount limits and the
INR-only rule are re-checked on the new content.

Only parameters named in EDITABLE_PARAMS can change. Parameters bound to something else
(a Velaris call_hash, a run's spec hash, a webhook id) are not editable: change those by
submitting a new request.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import update

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.core.security.redact import redact_secrets
from aether_os.prime.approvals import ApprovalService, RequestError, _now, compute_hash
from aether_os.prime.authz import ACTION_TYPES, CURRENCY, Action, dead_reason, money_reason
from aether_os.prime.edit_schema import EDITABLE_PARAMS, coerce
from aether_os.prime.limits import get_limits
from aether_os.prime.models import PrimeRequest
from aether_os.prime.repository import _aware_utc, authority

def _new_params(row: PrimeRequest, patch: Dict[str, Any]) -> Dict[str, Any]:
    schema = EDITABLE_PARAMS.get(row.action_type, {})
    unknown = sorted(set(patch) - set(schema))
    if unknown:
        raise RequestError(422, f"not editable for '{row.action_type}': {', '.join(unknown)}")
    new = dict(row.params or {})
    for k, v in patch.items():
        try:
            new[k] = coerce(k, v, *schema[k])
        except ValueError as e:
            raise RequestError(422, str(e)) from None
    return new


def _new_amount(row: PrimeRequest, amount: Optional[Any]) -> Optional[str]:
    if amount is None:
        return row.amount
    if not ACTION_TYPES.get(row.action_type) and row.amount is None:
        raise RequestError(422, f"'{row.action_type}' carries no amount")
    try:
        return str(Decimal(str(amount)))
    except InvalidOperation:
        raise RequestError(422, "amount is not a number") from None


async def edit_request(svc: ApprovalService, request_id: str, uid: str, identities: Iterable[str],
                       org_id: str, quoted_hash: str, reason: str, *, amount: Optional[Any] = None,
                       params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ids = list(identities)
    reason = (reason or "").strip()
    if not reason:
        raise RequestError(422, "a reason is required to edit a request")
    row = await svc._visible(request_id, uid, ids, org_id)
    if quoted_hash != row.request_hash or compute_hash(row) != row.request_hash:
        raise RequestError(409, "the request is not the one you were shown; reload it")
    if row.status != "pending" or row.expires_at <= _now():
        raise RequestError(409, "only a pending request can be edited")
    who = await authority(org_id, uid, row.action_type, row.executor)
    if not who["ok"]:
        raise RequestError(403, f"you cannot edit this: {who['reason']}")
    delegation = await svc._delegations.get(row.delegation_id)
    dead = dead_reason(delegation, _aware_utc(_now())) if delegation else "delegation missing"
    if dead:
        raise RequestError(409, f"cannot edit: {dead}")

    new_params = _new_params(row, params or {})
    new_amount = _new_amount(row, amount)
    if new_params == (row.params or {}) and new_amount == row.amount:
        raise RequestError(422, "nothing changed")
    candidate = Action(id=row.id, type=row.action_type, on_behalf_of=row.on_behalf_of,
                       requested_by=row.requested_by,
                       amount=Decimal(new_amount) if new_amount is not None else None,
                       currency=row.currency or (CURRENCY if new_amount is not None else None),
                       params=new_params)
    bad = money_reason(candidate, (await get_limits(org_id)).payment_ceiling)
    if bad:
        raise RequestError(409, f"cannot edit: {bad}")
    if ACTION_TYPES.get(row.action_type):
        cap = delegation.limits.max_amount if delegation and delegation.limits else None
        if cap is None or candidate.amount > cap:
            raise RequestError(409, f"cannot edit: amount exceeds the delegated limit {cap} {CURRENCY}")

    editors = sorted({*(row.edited_by or ()), uid})
    revised = PrimeRequest(**{c.name: getattr(row, c.name) for c in PrimeRequest.__table__.columns})
    revised.params, revised.amount, revised.revision = new_params, new_amount, row.revision + 1
    revised.currency = candidate.currency
    revised.edited_by = editors
    new_hash = compute_hash(revised)
    changes = {"before": {"amount": row.amount, "params": _shown(row.params)},
               "after": {"amount": new_amount, "params": _shown(new_params)}}
    # Ledger first: an edit must never exist without a record of who made it and why.
    await audit_chain.append(actor=uid, action="prime.approval.edit", payload={
        **svc._ledger(row, status="pending"), "revision": revised.revision, "reason": reason,
        "old_hash": row.request_hash, "new_hash": new_hash, "changes": changes})
    async with get_session_factory()() as session:
        won = (await session.execute(
            update(PrimeRequest)
            .where(PrimeRequest.id == row.id, PrimeRequest.status == "pending",
                   PrimeRequest.request_hash == row.request_hash)    # nobody decided or edited since
            .values(params=new_params, amount=new_amount, currency=candidate.currency,
                    revision=revised.revision, edited_by=editors, request_hash=new_hash))).rowcount
        await session.commit()
    if not won:
        raise RequestError(409, "someone decided or edited this request first; reload it")
    out = await svc._view(await svc._load(row.id), uid, ids)
    out["approvals_reset"] = True
    return out


def _shown(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {k: redact_secrets(v, limit=500) if isinstance(v, str) else v for k, v in (params or {}).items()}
