"""Prime — approval requests: record, show to the right people, decide, execute once.

Flow: submit() asks PrimeService.decide(). NEEDS_APPROVAL and ROUTE_TO_DEPUTY become
a pending request for the owner or the delegation's deputy; EXECUTE outcomes are
recorded as approved by Prime and executed straight away. Every step is in the ledger.

Each request has a hash over everything a person is shown. A decision must quote
it, and an executor runs only while the stored row still hashes to the value that
was approved.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, case, exists, func, or_, select, update

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.core.models import User
from aether_os.core.security.redact import redact_secrets
from aether_os.prime.authz import (
    ACTION_TYPES, EXTERNAL_EFFECT, NEVER, PRIME, Action, Outcome, dead_reason, money_reason, needs_second_person,
)
from aether_os.prime.executors import (
    DEFAULT_EXECUTOR, ExecutionContext, ExecutionFailed, get_executor,
)
from aether_os.prime.limits import get_limits
from aether_os.prime.models import PrimeDelegation, PrimeRequest
from aether_os.prime.repository import (
    DelegationRepository, _aware_utc, _naive_utc, authority, person_in_org,
)
from aether_os.prime.service import PrimeService

logger = logging.getLogger(__name__)

REQUEST_TTL = timedelta(hours=72)
# A request still "running" after this long was interrupted mid-execution. It is
# shown as needs_attention and never picked up again by code.
EXECUTION_STALE_AFTER = timedelta(minutes=5)
_ACTING = {Outcome.EXECUTE, Outcome.EXECUTE_AND_NOTIFY}
_WAITING = {Outcome.NEEDS_APPROVAL, Outcome.ROUTE_TO_DEPUTY}


class RequestError(Exception):
    """A refusal the caller can be told about. `status` is the HTTP status to use."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, like the columns


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return _aware_utc(dt).isoformat() if dt else None


def _action(row: PrimeRequest) -> Action:
    return Action(id=row.id, type=row.action_type, on_behalf_of=row.on_behalf_of,
                  requested_by=row.requested_by, amount=row.amount, currency=row.currency,
                  params=row.params or {})


def compute_hash(row: PrimeRequest) -> str:
    """SHA-256 over everything an approver is shown. Recomputed from the stored row
    before a decision and before execution, so an edited row matches nothing."""
    return hashlib.sha256(audit_chain.canonical_payload({
        "id": row.id, "org_id": row.org_id, "type": row.action_type,
        "on_behalf_of": row.on_behalf_of, "requested_by": row.requested_by,
        "amount": row.amount, "currency": row.currency, "params": row.params or {},
        "executor": row.executor, "delegation_id": row.delegation_id, "deputy": row.deputy,
        "expires_at": row.expires_at.isoformat(),
    }).encode("utf-8")).hexdigest()


def _state(row: PrimeRequest, now: datetime) -> str:
    if row.status == "pending" and row.expires_at <= now:
        return "expired"
    return row.status


def _exec_status(row: PrimeRequest, now: datetime) -> Optional[str]:
    if row.exec_status == "running" and row.exec_started_at and \
            now - row.exec_started_at > EXECUTION_STALE_AFTER:
        return "needs_attention"
    return row.exec_status


def _live_delegation(now: datetime):
    """SQL: the request's delegation exists and confers authority at `now`."""
    return exists().where(
        PrimeDelegation.id == PrimeRequest.delegation_id,
        PrimeDelegation.revoked_at.is_(None),
        PrimeDelegation.valid_from <= now, PrimeDelegation.valid_until > now)


async def members(org_id: str, user_ids: Iterable[str]) -> set:
    """Which of these user ids are people in this organisation."""
    ids = list(user_ids)
    if not ids:
        return set()
    async with get_session_factory()() as session:
        return set((await session.execute(
            select(User.id).where(User.org_id == org_id, User.id.in_(ids)))).scalars().all())


class ApprovalService:
    def __init__(self, delegations: DelegationRepository) -> None:
        self._delegations = delegations
        self._prime = PrimeService(delegations)

    # ── submit ────────────────────────────────────────────────────────────────

    async def submit(self, action: Action, org_id: str,
                     executor: str = DEFAULT_EXECUTOR) -> Dict[str, Any]:
        """Decide `action`; record a request if a person or an executor must act on it."""
        if get_executor(executor) is None:
            raise RequestError(400, f"unknown executor '{executor}'")
        decision = await self._prime.decide(action, org_id, executor)
        out: Dict[str, Any] = {"action_id": action.id, **decision.model_dump(mode="json"),
                               "request": None}
        if decision.outcome not in _ACTING | _WAITING:
            return out  # refused or recommendation only: nothing to approve or run

        delegation = await self._delegations.get(decision.delegation_id)
        if delegation is None:
            raise RequestError(409, "the delegation behind this decision no longer exists")
        now = _now()
        auto = decision.outcome in _ACTING
        row = PrimeRequest(
            id=action.id, org_id=org_id, action_type=action.type,
            on_behalf_of=action.on_behalf_of, requested_by=action.requested_by,
            amount=str(action.amount) if action.amount is not None else None,
            currency=action.currency, params=action.model_dump(mode="json")["params"],
            executor=executor, delegation_id=delegation.id, deputy=delegation.deputy,
            outcome=decision.outcome.value, reason=decision.reason,
            status="approved" if auto else "pending",
            created_at=now,
            expires_at=min(now + REQUEST_TTL, _naive_utc(delegation.valid_until)),
        )
        row.request_hash = compute_hash(row)
        if auto:
            row.decided_by, row.decided_at, row.decided_hash = PRIME, now, row.request_hash
        await audit_chain.append(actor=action.requested_by, action="prime.approval.request",
                                 payload=self._ledger(row, status=row.status))
        async with get_session_factory()() as session:
            session.add(row)
            await session.commit()
        if auto:
            await self._execute(row.id)
        out["request"] = await self._view(await self._load(row.id), None, ())
        return out

    # ── read ──────────────────────────────────────────────────────────────────

    async def inbox(self, uid: str, identities: Iterable[str], org_id: str,
                    state: str = "pending", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """Requests the caller owns or is the active deputy for, pending first."""
        now = _now()
        ids = list(identities)
        mine = and_(PrimeRequest.org_id == org_id, or_(
            PrimeRequest.on_behalf_of == uid,
            and_(PrimeRequest.deputy.in_(ids), _live_delegation(now))))
        open_ = and_(PrimeRequest.status == "pending", PrimeRequest.expires_at > now)
        where = {
            "pending": open_,
            "expired": and_(PrimeRequest.status == "pending", PrimeRequest.expires_at <= now),
            "decided": PrimeRequest.status != "pending",
            "all": PrimeRequest.id.is_not(None),
        }[state]
        async with get_session_factory()() as session:
            total = (await session.execute(
                select(func.count()).select_from(PrimeRequest).where(mine, where))).scalar_one()
            rows = (await session.execute(
                select(PrimeRequest).where(mine, where)
                .order_by(case((open_, 0), else_=1), PrimeRequest.created_at.desc(),
                          PrimeRequest.id)
                .limit(limit).offset(offset))).scalars().all()
        return {"total": total, "limit": limit, "offset": offset, "state": state,
                "requests": [await self._view(r, uid, ids) for r in rows]}

    async def get(self, request_id: str, uid: str, identities: Iterable[str],
                  org_id: str) -> Dict[str, Any]:
        row = await self._visible(request_id, uid, list(identities), org_id)
        return await self._view(row, uid, list(identities))

    async def service_view(self, request_id: str, org_id: str, executor: str) -> Dict[str, Any]:
        """The request as GET /prime/requests/{id} shows it, for a system acting for `org_id`
        (an organisation API key). Only requests of that organisation and executor; else 404."""
        row = await self._load(request_id)
        if row is None or row.org_id != org_id or row.executor != executor:
            raise RequestError(404, "Request not found")
        return await self._view(row, None, ())

    # ── decide ────────────────────────────────────────────────────────────────

    async def decide(self, request_id: str, uid: str, identities: Iterable[str], org_id: str,
                     quoted_hash: str, approve: bool, reason: str = "") -> Dict[str, Any]:
        """Approve or reject. Idempotent for the same person and the same answer."""
        ids = list(identities)
        row = await self._visible(request_id, uid, ids, org_id)
        wanted = "approved" if approve else "rejected"
        if quoted_hash != row.request_hash or compute_hash(row) != row.request_hash:
            raise RequestError(409, "the request is not the one you were shown; reload it")
        if row.status != "pending":
            if row.status == wanted and row.decided_by == uid:
                # Same answer again: no second ledger entry. If the first call died
                # before execution was claimed, this starts it; otherwise it is a no-op.
                if approve:
                    await self._execute(row.id)
                return await self._view(await self._load(row.id), uid, ids)
            raise RequestError(409, f"this request was already {row.status}")
        blocked = await self._why_not(row, uid, ids, approve)
        if blocked:
            await audit_chain.append(actor=uid, action="prime.approval.refuse", payload={
                **self._ledger(row, status=row.status), "answer": wanted, "reason": blocked[1]})
            raise RequestError(*blocked)
        checks = (await self._violation(row, uid))[1] if approve else []

        now = _now()
        # Ledger first. ponytail: if two people decide at the same instant the loser's
        # entry stays in the ledger although the request kept the winner's answer; the
        # request row and the later execution entries show which one took effect.
        await audit_chain.append(actor=uid, action="prime.approval.decision", payload={
            **self._ledger(row, status=wanted), "reason": reason, "authority": checks})
        async with get_session_factory()() as session:
            won = (await session.execute(
                update(PrimeRequest)
                .where(PrimeRequest.id == row.id, PrimeRequest.status == "pending")
                .values(status=wanted, decided_by=uid, decided_at=now,
                        decision_reason=reason, decided_hash=row.request_hash))).rowcount
            await session.commit()
        row = await self._load(row.id)
        if not won and not (row.status == wanted and row.decided_by == uid):
            raise RequestError(409, "someone else decided this request first")
        if approve:
            await self._execute(row.id)  # claims the row, so a duplicate call runs nothing
        return await self._view(await self._load(row.id), uid, ids)

    async def _why_not(self, row: PrimeRequest, uid: str, ids: list, approve: bool):
        """(status, message) if this person may not give this answer now, else None."""
        now = _now()
        if row.status == "pending" and row.expires_at <= now:
            return 409, "this request has expired; it was not approved"
        if row.requested_by in {uid, *ids}:
            return 403, "you cannot decide a request you made yourself"
        if not approve:
            return None
        delegation = await self._delegations.get(row.delegation_id)
        dead = dead_reason(delegation, _aware_utc(now)) if delegation else "delegation missing"
        if dead:
            return 409, f"cannot approve: {dead}"
        if row.executor in EXTERNAL_EFFECT:
            # Not Prime, the requester or the person acted for: 409 (they may still reject).
            grantor = await self._grantor_ids(row)
            if uid.lower() == PRIME or {uid.lower(), *(i.lower() for i in ids)} & grantor:
                return 409, ("cannot approve: an external effect needs a human other than "
                             "the requester and the person it is for")
        violation, checks = await self._violation(row, uid)
        if violation:
            # 403 when the approver themselves lacks authority; they may still reject.
            mine = any(c["person"] == uid and not c["ok"] for c in checks) and uid != row.on_behalf_of
            return (403 if mine else 409), f"cannot approve: {violation}"
        return None

    async def _violation(self, row: PrimeRequest, approver: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Why this request may not run on `approver`'s approval now ('' if it may), and
        the authority checks made. Rules no person can override, re-checked at approval
        and again before execution, because limits and roles change."""
        action = _action(row)
        if action.type in NEVER or action.type not in ACTION_TYPES:
            return f"'{action.type}' can never be approved", []
        if get_executor(row.executor) is None:
            return f"unknown executor '{row.executor}'", []
        bad_money = money_reason(action, (await get_limits(row.org_id)).payment_ceiling)
        if bad_money:
            return bad_money, []
        # The person acted for must still hold the authority, and so must a human
        # approver: a deputy approving out of scope or over limit uses their own.
        people = [row.on_behalf_of] + ([approver] if approver not in (PRIME, row.on_behalf_of) else [])
        checks = [await authority(row.org_id, p, row.action_type, row.executor) for p in people]
        denied = next((f"{c['person']}: {c['reason']}" for c in checks if not c["ok"]), "")
        return denied, checks

    async def _grantor_ids(self, row: PrimeRequest) -> set:
        person = await person_in_org(row.org_id, row.on_behalf_of)
        return {row.on_behalf_of.lower(), person[1] if person else row.on_behalf_of.lower()}

    async def _no_second_person(self, row: PrimeRequest) -> bool:
        """Money or an external effect approved only by whoever asked for it. For an
        external effect the approver must also not be Prime or the person acted for."""
        if not needs_second_person(row.action_type, row.executor):
            return False
        grantor = await self._grantor_ids(row)
        requester, approver = row.requested_by.lower(), (row.decided_by or "").lower()
        if row.executor in EXTERNAL_EFFECT and (not approver or approver == PRIME or approver in grantor):
            return True
        return approver == requester or (approver == PRIME and requester in grantor)

    # ── execute ───────────────────────────────────────────────────────────────

    async def _execute(self, request_id: str) -> None:
        """Run the executor at most once for an approved request. Never raises, never retries."""
        row = await self._load(request_id)
        if row is None or row.status != "approved" or row.exec_status is not None:
            return
        base = self._ledger(row, status="approved")
        key = f"prime-{row.request_hash}"
        executor = get_executor(row.executor)
        refusal, checks = "", []
        if not (row.decided_hash == row.request_hash == compute_hash(row)):
            refusal = "the request no longer matches what was approved"
        elif executor is None:
            refusal = f"unknown executor '{row.executor}'"
        else:
            try:
                refusal, checks = await self._violation(row, row.decided_by or "")
                if not refusal and await self._no_second_person(row):
                    refusal = "no person other than the requester approved this"
            except Exception as e:
                logger.warning("prime: authority check for request %s failed: %s", row.id, e)
                refusal = "authority could not be checked; refusing"
        base["authority"] = checks

        now = _now()
        async with get_session_factory()() as session:
            claimed = (await session.execute(
                update(PrimeRequest)
                .where(PrimeRequest.id == row.id, PrimeRequest.status == "approved",
                       PrimeRequest.exec_status.is_(None))
                .values(exec_status="running", exec_started_at=now))).rowcount
            await session.commit()
        if not claimed:
            return  # another call owns this execution

        try:
            if refusal:
                status, result = "failed", {"error": refusal}
            else:
                # If this entry cannot be written the row stays "running" and later
                # reads as needs_attention: nothing runs without its ledger entry.
                await audit_chain.append(actor=PRIME, action="prime.execution.start", payload={
                    **base, "idempotency_key": key})
                ctx = ExecutionContext(request_id=row.id, org_id=row.org_id, action=_action(row),
                                       idempotency_key=key, approved_by=row.decided_by or "")
                try:
                    status, result = "succeeded", await executor.execute(ctx)
                except ExecutionFailed as e:
                    status, result = "failed", {"error": redact_secrets(e)}
                except Exception as e:
                    # Unknown outcome: the action may have happened. A person must look.
                    logger.error("prime: execution of request %s ended unclear: %s", row.id, e)
                    status, result = "needs_attention", {
                        "error": f"outcome unknown: {redact_secrets(e)}"}
            await audit_chain.append(actor=PRIME, action="prime.execution.result", payload={
                **base, "idempotency_key": key, "execution": status, "result": result})
            async with get_session_factory()() as session:
                await session.execute(update(PrimeRequest).where(PrimeRequest.id == row.id)
                                      .values(exec_status=status, exec_result=result))
                await session.commit()
        except Exception as e:
            logger.error("prime: request %s left running, needs attention: %s", row.id, e)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ledger(row: PrimeRequest, status: str) -> Dict[str, Any]:
        return {"request_id": row.id, "request_hash": row.request_hash, "org_id": row.org_id,
                "type": row.action_type, "on_behalf_of": row.on_behalf_of,
                "delegation_id": row.delegation_id, "executor": row.executor, "status": status}

    async def _load(self, request_id: str) -> Optional[PrimeRequest]:
        async with get_session_factory()() as session:
            return await session.get(PrimeRequest, request_id)

    async def _visible(self, request_id: str, uid: str, ids: list, org_id: str) -> PrimeRequest:
        """The request, if the caller owns it or is its active deputy; else 404."""
        now = _now()
        async with get_session_factory()() as session:
            row = (await session.execute(select(PrimeRequest).where(
                PrimeRequest.id == request_id, PrimeRequest.org_id == org_id, or_(
                    PrimeRequest.on_behalf_of == uid,
                    and_(PrimeRequest.deputy.in_(ids), _live_delegation(now))))
            )).scalar_one_or_none()
        if row is None:
            raise RequestError(404, "Request not found")
        return row

    async def _view(self, row: PrimeRequest, uid: Optional[str], ids: Iterable[str]) -> Dict[str, Any]:
        now = _now()
        state = _state(row, now)
        executor = get_executor(row.executor)
        ctx = ExecutionContext(request_id=row.id, org_id=row.org_id, action=_action(row),
                               idempotency_key=f"prime-{row.request_hash}",
                               approved_by=row.decided_by or "")
        blocked = None
        if uid is not None and state == "pending":
            blocked = await self._why_not(row, uid, list(ids), approve=True)
        return {
            "id": row.id, "state": state, "request_hash": row.request_hash,
            "action": {"type": row.action_type, "on_behalf_of": row.on_behalf_of,
                       "requested_by": row.requested_by, "amount": row.amount,
                       "currency": row.currency, "params": row.params or {}},
            "executor": row.executor,
            "what_will_happen": (await executor.describe(ctx)) if executor
            else f"Nothing: unknown executor '{row.executor}'.",
            "outcome": row.outcome, "why": row.reason,
            "delegation_id": row.delegation_id, "deputy": row.deputy,
            "created_at": _iso(row.created_at), "expires_at": _iso(row.expires_at),
            "decided_by": row.decided_by, "decided_at": _iso(row.decided_at),
            "decision_reason": row.decision_reason,
            "execution": ({"status": _exec_status(row, now), "result": row.exec_result,
                           "idempotency_key": ctx.idempotency_key}
                          if row.exec_status else None),
            "can_decide": uid is not None and state == "pending" and (
                blocked is None or blocked[0] != 403),
            "can_approve": uid is not None and state == "pending" and blocked is None,
            "blocked_reason": blocked[1] if blocked else None,
        }
