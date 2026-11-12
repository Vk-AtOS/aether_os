"""Prime — decision service: authorise, write both sides to the audit chain, return."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from aether_os.core.audit import chain as audit_chain
from aether_os.prime.authz import (
    PRIME, Action, Decision, Outcome, authority_reason, authorize, needs_second_person,
)
from aether_os.prime.executors import DEFAULT_EXECUTOR
from aether_os.prime.limits import get_limits
from aether_os.prime.repository import DelegationRepository, org_payload, person_in_org

logger = logging.getLogger(__name__)

_ACTING = {Outcome.EXECUTE, Outcome.EXECUTE_AND_NOTIFY}


class PrimeService:
    def __init__(self, delegations: DelegationRepository) -> None:
        self._delegations = delegations

    async def decide(self, action: Action, org_id: Optional[str] = None,
                     executor: str = DEFAULT_EXECUTOR) -> Decision:
        """Authorise `action` and record request + decision in the audit chain.

        Executes nothing. If the chain cannot be written this raises, so no
        Decision exists without its ledger entries. The person acted for must hold
        authority over the action and the executor in `org_id` right now.
        """
        await audit_chain.append(
            actor=action.requested_by, action="prime.request",
            payload={**action.model_dump(mode="json"), "executor": executor,
                     **org_payload(org_id)},
        )
        auth: Dict[str, Any] = {"person": action.on_behalf_of, "role": None,
                                "executor": executor, "ok": False}
        try:
            person = await person_in_org(org_id, action.on_behalf_of)
            auth["role"] = person[0] if person else None
            auth["reason"] = authority_reason(auth["role"], action.type, executor)
            auth["ok"] = not auth["reason"]
            limits = await get_limits(org_id)
            delegations = await self._delegations.for_grantor(action.on_behalf_of)
            decision = authorize(action, datetime.now(timezone.utc), delegations,
                                 payment_ceiling=limits.payment_ceiling)
            if decision.outcome is not Outcome.REFUSE and not auth["ok"]:
                # A delegation cannot pass on authority its grantor no longer holds.
                decision = Decision(outcome=Outcome.REFUSE, delegation_id=decision.delegation_id,
                                    reason=f"{action.on_behalf_of}: {auth['reason']}")
            elif decision.outcome in _ACTING and needs_second_person(action.type, executor) \
                    and action.requested_by.lower() in {action.on_behalf_of.lower(), person[1]}:
                # Money or an external effect asked for by the grantor themselves: the
                # delegation is no second person, so someone else must approve.
                decision = Decision(
                    outcome=Outcome.NEEDS_APPROVAL, delegation_id=decision.delegation_id,
                    reason=f"{decision.reason}; requested by the grantor, so a second "
                           "person must approve")
        except Exception as e:
            logger.warning("prime: delegation lookup failed for action %s: %s", action.id, e)
            decision = Decision(outcome=Outcome.REFUSE,
                                reason="delegations or limits could not be loaded; refusing")
        await audit_chain.append(
            actor=PRIME, action="prime.decision",
            payload={"action_id": action.id, "on_behalf_of": action.on_behalf_of,
                     **decision.model_dump(mode="json"), "authority": auth,
                     **org_payload(org_id)},
        )
        return decision
