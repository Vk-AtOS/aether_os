"""Source of the generated billing_webhook.py (placeholder __SLUG__): Stripe events change tenant state.

State lives in the app's own database (table billing_accounts, one row per tenant):
  active     payment_succeeded: paid up, grace period cleared
  past_due   payment_failed: grace period starts (BILLING_GRACE_DAYS, default 7), then access stops
  suspended  customer.subscription.deleted: access stops at once
require_active_subscription is the dependency that enforces it; add it to the routes (or the
router) that must stop for a tenant that does not pay. The tenant of a Stripe customer comes from
the customer/subscription metadata key tenant_id (set it when creating the Checkout session).
"""

WEBHOOK_SRC = '''\
"""
Stripe webhook handler for __SLUG__.

Verifies the Stripe-Signature header before processing any event, then records the tenant's
billing state (billing_accounts) so the app can act on it.
Mount this router in your FastAPI app: app.include_router(billing_router)

Environment variables:
  STRIPE_WEBHOOK_SECRET  whsec_... signing secret from the Stripe Dashboard (required)
  BILLING_GRACE_DAYS     days of access after a failed payment (default 7)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import Column, Float, String, select

# The generated backend's own modules, by the plain names main.py imports them under. Trying
# "src.database" first made a second module with its own Base, so create_all never made billing_accounts.
try:
    from database import AsyncSessionLocal, Base
except ImportError:
    from src.database import AsyncSessionLocal, Base
try:
    from auth import get_current_user
except ImportError:
    from src.auth import get_current_user

logger = logging.getLogger(__name__)

billing_router = APIRouter(prefix="/billing", tags=["billing"])
router = billing_router  # the s10 auto-wire imports the name "router"

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
GRACE_SECONDS = int(float(os.getenv("BILLING_GRACE_DAYS", "7")) * 86400)
_SignatureError = getattr(stripe, "SignatureVerificationError", None) or stripe.error.SignatureVerificationError


class BillingAccount(Base):
    __tablename__ = "billing_accounts"

    tenant_id = Column(String(64), primary_key=True)
    stripe_customer_id = Column(String(64), unique=True, index=True, nullable=True)
    status = Column(String(16), nullable=False, default="active")     # active | past_due | suspended
    grace_until = Column(Float, nullable=True)                        # epoch seconds, set while past_due
    updated_at = Column(Float, nullable=False, default=time.time)


def _tenant_from_event(obj: dict) -> Optional[str]:
    """tenant_id carried in the Stripe object's metadata (invoice, subscription or customer)."""
    for holder in (obj.get("subscription_details") or {}, obj):
        tenant = (holder.get("metadata") or {}).get("tenant_id")
        if tenant:
            return str(tenant)
    return None


async def _get_tenant_by_customer(session, customer_id: str, obj: dict) -> Optional[str]:
    """Tenant of a Stripe customer: the stored mapping, else the metadata of this event (stored)."""
    row = (await session.execute(
        select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id)
    )).scalar_one_or_none()
    if row is not None:
        return row.tenant_id
    tenant = _tenant_from_event(obj)
    if tenant:
        existing = await session.get(BillingAccount, tenant)
        if existing is None:
            session.add(BillingAccount(tenant_id=tenant, stripe_customer_id=customer_id))
        else:
            existing.stripe_customer_id = customer_id
        await session.flush()
    return tenant


async def _set_state(session, tenant_id: str, new_status: str) -> None:
    acct = await session.get(BillingAccount, tenant_id)
    if acct is None:
        acct = BillingAccount(tenant_id=tenant_id)
        session.add(acct)
    now = time.time()
    if new_status == "past_due":
        # A retry of the same failure must not push the end of the grace period out.
        if acct.status != "past_due" or not acct.grace_until:
            acct.grace_until = now + GRACE_SECONDS
    else:
        acct.grace_until = None
    acct.status = new_status
    acct.updated_at = now


_EVENT_STATE = {
    "invoice.payment_succeeded": "active",
    "invoice.payment_failed": "past_due",
    "customer.subscription.deleted": "suspended",
}


@billing_router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
) -> dict:
    """Receive and process Stripe webhook events for __SLUG__."""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Billing webhook is not configured")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
    except _SignatureError as exc:
        logger.warning("stripe_webhook: invalid signature: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from exc
    except Exception as exc:
        logger.warning("stripe_webhook: payload parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Malformed payload") from exc

    event_type = event.get("type", "")
    new_status = _EVENT_STATE.get(event_type)
    if new_status is None:
        logger.debug("stripe_webhook: unhandled event type=%s", event_type)
        return {"received": True, "type": event_type}

    obj = event.get("data", {}).get("object", {})
    customer_id = obj.get("customer")
    async with AsyncSessionLocal() as session:
        tenant_id = await _get_tenant_by_customer(session, customer_id, obj) if customer_id else None
        if tenant_id is None:
            # 200, not an error: Stripe would retry an event we can never map. It is logged for the operator.
            logger.warning("stripe_webhook: %s for unknown customer %s (no tenant_id metadata)", event_type, customer_id)
            return {"received": True, "type": event_type, "ignored": "unknown customer"}
        await _set_state(session, tenant_id, new_status)
        await session.commit()
    logger.info("stripe_webhook: %s -> tenant=%s status=%s", event_type, tenant_id, new_status)
    return {"received": True, "type": event_type, "tenant_status": new_status}


async def require_active_subscription(user: dict = Depends(get_current_user)) -> dict:
    """Dependency: 402 for a tenant that is suspended or past its grace period."""
    tenant_id = str(user.get("org_id") or "")
    async with AsyncSessionLocal() as session:
        acct = await session.get(BillingAccount, tenant_id) if tenant_id else None
    if acct is not None and (
        acct.status == "suspended"
        or (acct.status == "past_due" and acct.grace_until is not None and acct.grace_until < time.time())
    ):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Subscription inactive")
    return user


@billing_router.get("/status")
async def billing_status(user: dict = Depends(get_current_user)) -> dict:
    """The signed-in tenant's billing state."""
    tenant_id = str(user.get("org_id") or "")
    async with AsyncSessionLocal() as session:
        acct = await session.get(BillingAccount, tenant_id) if tenant_id else None
    return {
        "status": acct.status if acct else "active",
        "grace_until": acct.grace_until if acct else None,
    }
'''
