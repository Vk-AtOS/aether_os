"""
Guarded decision helper for risky operations.

This module encapsulates the logic for deciding whether an operation
(e.g. guarded_python_fix) should:

- be allowed immediately
- require approval (with an approval ticket)
- be blocked

It is designed to sit in front of higher-risk endpoints and coordinate
with an external approvals store (from approval_workflow).

The key entrypoint is:

    evaluate_and_prepare(...)

which returns a GuardedDecisionResult with:

- allowed / requires_approval
- whether a new ticket was created
- policy_reason
- ticket flags (approved / denied / pending)
- ticket (as a DICT, for easy JSON/logging & legacy code accessing
  ticket["id"], ticket["status"], ...).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, is_dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SEVERITY_ORDER = {
    "NONE": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


def _normalize_risk_label(label: Any) -> str:
    """
    Normalize risk labels to a stable uppercase value.
    """
    if not isinstance(label, str):
        return "UNKNOWN"
    return label.strip().upper() or "UNKNOWN"


def _severity(label: Any) -> int:
    lbl = _normalize_risk_label(label)
    return _SEVERITY_ORDER.get(lbl, _SEVERITY_ORDER["MEDIUM"])


def _get_policy_threshold(policy: Any) -> str:
    """
    Extract `max_risk_without_approval` from a policy object or dict, with a
    safe default of 'LOW'.

    Supported shapes for policy:

        - dict-like:  policy["max_risk_without_approval"]
        - object:     policy.max_risk_without_approval
    """
    default = "LOW"
    if policy is None:
        return default

    # dict-like
    if isinstance(policy, dict):
        val = policy.get("max_risk_without_approval", default)
        return _normalize_risk_label(val)

    # object with attribute
    val = getattr(policy, "max_risk_without_approval", default)
    return _normalize_risk_label(val)


def _ticket_to_dict(ticket: Any) -> Dict[str, Any]:
    """
    Convert an ApprovalTicket-like object into a plain dict.

    This is intentionally defensive and duck-typed so it works with the
    existing ApprovalTicket implementation *without* depending on its
    exact definition.

    Priority:

        1. dataclasses.asdict(...)
        2. ticket.__dict__
        3. minimal mapping with id/status if present
    """
    if ticket is None:
        return {}

    # dataclass support
    if is_dataclass(ticket):
        try:
            return asdict(ticket)
        except Exception as exc:
            logger.debug("_ticket_to_dict: asdict() failed, falling back to __dict__: %s", exc)

    # Generic object with __dict__
    if hasattr(ticket, "__dict__"):
        try:
            data = dict(ticket.__dict__)
        except Exception as exc:
            logger.debug("_ticket_to_dict: __dict__ copy failed: %s", exc)
            data = {}
    else:
        data = {}

    # Ensure id/status are present if available as attributes
    for key in ("id", "status", "operation_type", "risk_level"):
        if key not in data and hasattr(ticket, key):
            data[key] = getattr(ticket, key)

    return data


def _store_get_ticket(approvals_store: Any, ticket_id: int) -> Optional[Dict[str, Any]]:
    """
    Safely call approvals_store.get_ticket(ticket_id) if available and
    return a dict, else None.
    """
    if approvals_store is None:
        return None

    getter = getattr(approvals_store, "get_ticket", None)
    if getter is None:
        return None

    try:
        ticket_obj = getter(ticket_id)  # type: ignore[call-arg]
    except Exception as exc:
        logger.debug("_store_get_ticket: get_ticket(%s) raised: %s", ticket_id, exc)
        return None

    if ticket_obj is None:
        return None

    return _ticket_to_dict(ticket_obj)


def _store_create_ticket(
    approvals_store: Any,
    *,
    project_root: str,
    ctx: Dict[str, Any],
    risk_label: str,
) -> Optional[Dict[str, Any]]:
    """
    Create a new approval ticket via approvals_store if it supports
    `create_ticket(...)`. If not, returns None.

    Expected (duck-typed) call shape:

        approvals_store.create_ticket(
            project_root=project_root,
            operation_type=ctx["operation_type"],
            summary=ctx.get("summary"),
            risk_level=risk_label,
            payload=ctx.get("payload"),
            requester=ctx.get("actor") or "unknown",
        )
    """
    if approvals_store is None:
        return None

    creator = getattr(approvals_store, "create_ticket", None)
    if creator is None:
        return None

    operation_type = ctx.get("operation_type", "unknown_operation")
    summary = ctx.get("summary") or f"Operation {operation_type} at risk {risk_label}"
    payload = ctx.get("payload")
    requester = ctx.get("actor") or "unknown"

    try:
        ticket_obj = creator(
            project_root=project_root,
            operation_type=operation_type,
            summary=summary,
            risk_level=risk_label,
            payload=payload,
            requester=requester,
        )
    except Exception as exc:
        logger.debug("_store_create_ticket: create_ticket() raised for %s: %s", operation_type, exc)
        return None

    return _ticket_to_dict(ticket_obj)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class GuardedDecisionResult:
    """
    Outcome of a guarded decision.

    Fields:
        allowed:            Is the operation allowed to proceed right now?
        requires_approval:  Does this operation require approval first?
        created_new_ticket: Did this call create a new approval ticket?

        effective_risk:     Final risk label considered for this decision.
        policy_reason:      Human-readable explanation of the decision.

        ticket_is_approved: True if we found an APPROVED ticket in this context.
        ticket_is_denied:   True if we found a DENIED ticket.
        ticket_is_pending:  True if we found a ticket, but it's still PENDING.

        ticket:             A dict view of the ticket (id, status, etc.) if any.
                            This is intentionally a dict so legacy code like
                            `result.ticket["id"]` continues to work.
    """

    allowed: bool
    requires_approval: bool
    created_new_ticket: bool

    effective_risk: str
    policy_reason: str

    ticket_is_approved: bool
    ticket_is_denied: bool
    ticket_is_pending: bool

    ticket: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core decision function
# ---------------------------------------------------------------------------


def evaluate_and_prepare(
    *,
    project_root: str,
    policy: Any,
    approvals_store: Any,
    ctx: Dict[str, Any],
    is_guarded: bool,
    existing_ticket_id: Optional[int] = None,
) -> GuardedDecisionResult:
    """
    Decide whether an operation should be allowed, require approval, or be blocked.

    Args:
        project_root:       Root of the project (for ticket metadata).
        policy:             Policy object or dict. We currently look for
                            `max_risk_without_approval`, falling back to 'LOW'.
        approvals_store:    Arbitrary approvals store. Duck-typed; if it exposes
                            `get_ticket` / `create_ticket`, we will use them.
        ctx:                Context dictionary describing the operation:
                                {
                                    "operation_type": "guarded_python_fix",
                                    "summary": "...",
                                    "actor": "local-dev",
                                    "risk_level": "HIGH",
                                    "payload": { ... },
                                }
        is_guarded:         If False, we skip approval checks and allow (best-effort)
                            using the risk information only for logging.
        existing_ticket_id: Optional ticket id to re-evaluate an in-flight ticket.

    Returns:
        GuardedDecisionResult with a dict-based `ticket` field.
    """
    operation_type = ctx.get("operation_type", "unknown_operation")
    raw_risk_label = ctx.get("risk_level", ctx.get("risk_label", "MEDIUM"))

    risk_label = _normalize_risk_label(raw_risk_label)
    effective_risk = risk_label

    max_without_approval = _get_policy_threshold(policy)

    # If not running in guarded mode, allow but still express the effective risk.
    if not is_guarded:
        reason = (
            f"Ungarded mode: operation '{operation_type}' at risk '{risk_label}' "
            f"allowed without approvals (policy threshold={max_without_approval})."
        )
        return GuardedDecisionResult(
            allowed=True,
            requires_approval=False,
            created_new_ticket=False,
            effective_risk=effective_risk,
            policy_reason=reason,
            ticket_is_approved=False,
            ticket_is_denied=False,
            ticket_is_pending=False,
            ticket=None,
        )

    # Guarded mode: compare severity against the policy threshold.
    risk_sev = _severity(risk_label)
    thresh_sev = _severity(max_without_approval)

    # If risk is within threshold, allow without approval.
    if risk_sev <= thresh_sev:
        reason = (
            f"Operation '{operation_type}' at risk '{risk_label}' is within "
            f"max_risk_without_approval={max_without_approval}; allowed."
        )
        return GuardedDecisionResult(
            allowed=True,
            requires_approval=False,
            created_new_ticket=False,
            effective_risk=effective_risk,
            policy_reason=reason,
            ticket_is_approved=False,
            ticket_is_denied=False,
            ticket_is_pending=False,
            ticket=None,
        )

    # At this point, risk exceeds threshold => approvals are required.
    # First, see if there is an existing ticket we should respect.
    if existing_ticket_id is not None:
        ticket_dict = _store_get_ticket(approvals_store, existing_ticket_id)
        if ticket_dict is None:
            # Ticket not found => still pending / required
            reason = (
                f"Operation '{operation_type}' at risk '{risk_label}' exceeds "
                f"max_risk_without_approval={max_without_approval}; "
                f"existing ticket {existing_ticket_id} not found; approval required."
            )
            return GuardedDecisionResult(
                allowed=False,
                requires_approval=True,
                created_new_ticket=False,
                effective_risk=effective_risk,
                policy_reason=reason,
                ticket_is_approved=False,
                ticket_is_denied=False,
                ticket_is_pending=True,
                ticket=None,
            )

        status = str(ticket_dict.get("status", "PENDING")).upper()

        if status == "APPROVED":
            reason = (
                f"Operation '{operation_type}' at risk '{risk_label}' previously "
                f"approved via ticket {existing_ticket_id}; allowed."
            )
            return GuardedDecisionResult(
                allowed=True,
                requires_approval=False,
                created_new_ticket=False,
                effective_risk=effective_risk,
                policy_reason=reason,
                ticket_is_approved=True,
                ticket_is_denied=False,
                ticket_is_pending=False,
                ticket=ticket_dict,
            )

        if status == "DENIED":
            reason = (
                f"Operation '{operation_type}' at risk '{risk_label}' denied via "
                f"ticket {existing_ticket_id}; blocked."
            )
            return GuardedDecisionResult(
                allowed=False,
                requires_approval=True,
                created_new_ticket=False,
                effective_risk=effective_risk,
                policy_reason=reason,
                ticket_is_approved=False,
                ticket_is_denied=True,
                ticket_is_pending=False,
                ticket=ticket_dict,
            )

        # Anything else => treat as pending
        reason = (
            f"Operation '{operation_type}' at risk '{risk_label}' exceeds "
            f"max_risk_without_approval={max_without_approval}; "
            f"ticket {existing_ticket_id} is still pending."
        )
        return GuardedDecisionResult(
            allowed=False,
            requires_approval=True,
            created_new_ticket=False,
            effective_risk=effective_risk,
            policy_reason=reason,
            ticket_is_approved=False,
            ticket_is_denied=False,
            ticket_is_pending=True,
            ticket=ticket_dict,
        )

    # No existing ticket and approvals are required => create one if possible.
    ticket_dict = _store_create_ticket(
        approvals_store=approvals_store,
        project_root=project_root,
        ctx=ctx,
        risk_label=risk_label,
    )

    if ticket_dict is not None:
        tid = ticket_dict.get("id")
        reason = (
            f"Operation '{operation_type}' at risk '{risk_label}' exceeds "
            f"max_risk_without_approval={max_without_approval}; "
            f"approval required. Created ticket id={tid!r}."
        )
        return GuardedDecisionResult(
            allowed=False,
            requires_approval=True,
            created_new_ticket=True,
            effective_risk=effective_risk,
            policy_reason=reason,
            ticket_is_approved=False,
            ticket_is_denied=False,
            ticket_is_pending=True,
            ticket=ticket_dict,
        )

    # Fallback when approvals_store does not support ticket creation:
    reason = (
        f"Operation '{operation_type}' at risk '{risk_label}' exceeds "
        f"max_risk_without_approval={max_without_approval}; "
        f"approval required, but approvals_store does not support ticket creation."
    )
    return GuardedDecisionResult(
        allowed=False,
        requires_approval=True,
        created_new_ticket=False,
        effective_risk=effective_risk,
        policy_reason=reason,
        ticket_is_approved=False,
        ticket_is_denied=False,
        ticket_is_pending=True,
        ticket=None,
    )

