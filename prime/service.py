"""Prime — decision service: authorise, write both sides to the audit chain, return."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from aether_os.core.audit import chain as audit_chain
from aether_os.prime.authz import PRIME, Action, Decision, Outcome, authorize
from aether_os.prime.limits import get_limits
from aether_os.prime.repository import DelegationRepository, org_payload

logger = logging.getLogger(__name__)


class PrimeService:
    def __init__(self, delegations: DelegationRepository) -> None:
        self._delegations = delegations

    async def decide(self, action: Action, org_id: Optional[str] = None) -> Decision:
        """Authorise `action` and record request + decision in the audit chain.

        Executes nothing. If the chain cannot be written this raises, so no
        Decision exists without its ledger entries.
        """
        await audit_chain.append(
            actor=action.requested_by, action="prime.request",
            payload={**action.model_dump(mode="json"), **org_payload(org_id)},
        )
        try:
            limits = await get_limits(org_id)
            delegations = await self._delegations.for_grantor(action.on_behalf_of)
            decision = authorize(action, datetime.now(timezone.utc), delegations,
                                 payment_ceiling=limits.payment_ceiling)
        except Exception as e:
            logger.warning("prime: delegation lookup failed for action %s: %s", action.id, e)
            decision = Decision(outcome=Outcome.REFUSE,
                                reason="delegations or limits could not be loaded; refusing")
        await audit_chain.append(
            actor=PRIME, action="prime.decision",
            payload={"action_id": action.id, "on_behalf_of": action.on_behalf_of,
                     **decision.model_dump(mode="json"), **org_payload(org_id)},
        )
        return decision
