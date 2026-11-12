"""AetherOS — apply Stripe webhook events, confirmed with Stripe, at most once.

The webhook signature proves the event came from Stripe; it says nothing about
what the event body claims was bought. As with Razorpay (_confirmed_order in
billing_router), the object is fetched back from Stripe and the plan is taken
from the price that was actually paid, never from metadata a payer could
influence. The org comes from metadata this server wrote when it created the
checkout session. Payments go through apply_paid_order(provider="stripe"), so
billing_payments' unique constraints refuse a replayed event, and every paid
event sets the plan's period.

`stripe` is the configured SDK module, passed in so this file has no import-time
dependency on it and tests can hand in a fake.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import update

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.billing.payments import FREE_PLAN, apply_paid_order
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation

logger = logging.getLogger(__name__)


def _plan_for_price(price_id: str, prices: Dict[str, str]) -> Optional[str]:
    return next((plan for plan, pid in prices.items() if pid and pid == price_id), None)


def _single_price(lines: Any) -> Optional[str]:
    data = (lines or {}).get("data") or []
    if len(data) != 1:
        return None
    price = data[0].get("price") or {}
    return price.get("id") if isinstance(price, dict) else price


def confirmed_checkout(stripe: Any, session_id: str, prices: Dict[str, str]) -> Optional[Tuple[str, str, str, int]]:
    """(org_id, plan, payment_ref, amount) for a completed, paid subscription checkout
    of one of our prices, as Stripe holds it; None otherwise."""
    s = stripe.checkout.Session.retrieve(session_id, expand=["line_items"])
    org_id = (s.get("metadata") or {}).get("org_id") or ""
    plan = _plan_for_price(_single_price(s.get("line_items")) or "", prices)
    if (not org_id or plan is None or s.get("status") != "complete"
            or s.get("payment_status") != "paid" or s.get("mode") != "subscription"):
        return None
    return org_id, plan, str(s.get("subscription") or s.get("payment_intent") or session_id), int(s.get("amount_total") or 0)


def confirmed_renewal(stripe: Any, invoice_id: str, prices: Dict[str, str]) -> Optional[Tuple[str, str, str, int]]:
    """Same, for a paid renewal invoice of a subscription our checkout created.
    The first invoice of a subscription is applied by its checkout, not here."""
    inv = stripe.Invoice.retrieve(invoice_id)
    if inv.get("status") != "paid" or inv.get("billing_reason") != "subscription_cycle" or not inv.get("subscription"):
        return None
    sub = stripe.Subscription.retrieve(inv["subscription"])
    org_id = (sub.get("metadata") or {}).get("org_id") or ""
    plan = _plan_for_price(_single_price(inv.get("lines")) or "", prices)
    if not org_id or plan is None:
        return None
    return org_id, plan, str(inv.get("payment_intent") or invoice_id), int(inv.get("amount_paid") or 0)


async def end_subscription(stripe: Any, subscription_id: str) -> bool:
    """A subscription Stripe reports as canceled moves its org to free now. Confirmed
    with Stripe; repeating it changes nothing and is not ledgered again."""
    sub = stripe.Subscription.retrieve(subscription_id)
    org_id = (sub.get("metadata") or {}).get("org_id") or ""
    if sub.get("status") != "canceled" or not org_id:
        return False
    now = time.time()
    async with get_session_factory()() as session:
        result = await session.execute(
            update(Organisation).where(Organisation.id == org_id, Organisation.plan != FREE_PLAN)
            .values(plan=FREE_PLAN, plan_period_end=now))
        await session.commit()
    if result.rowcount:
        await get_ledger().async_log_audit_event(
            org_id=org_id, user_id="billing", action="billing.subscription_ended",
            resource_type="organisation", resource_id=org_id,
            metadata={"provider": "stripe", "subscription_id": subscription_id, "ended_at": now})
    return bool(result.rowcount)


async def apply_event(stripe: Any, event: Dict[str, Any], prices: Dict[str, str]) -> str:
    """Apply one verified event. Returns what happened (for the log); raises on a
    Stripe API error so the caller answers 5xx and Stripe delivers the event again."""
    etype = event.get("type", "")
    obj_id = ((event.get("data") or {}).get("object") or {}).get("id") or ""
    if etype in ("checkout.session.completed", "invoice.paid") and obj_id:
        confirm = confirmed_checkout if etype == "checkout.session.completed" else confirmed_renewal
        confirmed = confirm(stripe, obj_id, prices)
        if confirmed is None:
            logger.warning("stripe: %s %s is not a paid purchase of a known plan — not applied", etype, obj_id)
            return "not_applicable"
        org_id, plan, payment_ref, amount = confirmed
        applied = await apply_paid_order("stripe", obj_id, payment_ref, org_id, plan, amount=amount)
        return "applied" if applied else "already_applied"
    if etype == "customer.subscription.deleted" and obj_id:
        return "ended" if await end_subscription(stripe, obj_id) else "not_applicable"
    return "ignored"
