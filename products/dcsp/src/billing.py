"""
Stripe billing integration for DCSP.

Plans:
  - Free: 5 repairs/month at no charge
  - Pro: $49/mo, 100 repairs/month
  - Enterprise: $199/mo, unlimited repairs

Reads STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET from environment.
If either is absent, billing endpoints return 503 — the app still starts.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

PLAN_PRICES = {
    "pro": os.environ.get("STRIPE_PRO_PRICE_ID", "price_pro_placeholder"),
    "enterprise": os.environ.get("STRIPE_ENTERPRISE_PRICE_ID", "price_enterprise_placeholder"),
}

PLAN_LIMITS = {
    "free": 5,
    "pro": 100,
    "enterprise": None,  # unlimited
}


def _stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def _get_stripe():
    """Return the stripe module initialised with the secret key, or raise."""
    if not _stripe_configured():
        raise RuntimeError("Stripe is not configured — set STRIPE_SECRET_KEY env var")
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        return stripe
    except ImportError as e:
        raise RuntimeError("stripe package is not installed") from e


def create_checkout_session(
    tenant_id: str,
    plan: str,
    success_url: str,
    cancel_url: str,
) -> dict:
    """
    Create a Stripe Checkout session for the given plan.

    Returns {"url": checkout_url} on success.
    Returns {"error": message} if Stripe is not configured.
    """
    if not _stripe_configured():
        return {"error": "Billing not configured"}

    price_id = PLAN_PRICES.get(plan)
    if not price_id:
        return {"error": f"Unknown plan: {plan}"}

    try:
        stripe = _get_stripe()
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": tenant_id, "plan": plan},
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Stripe create_checkout_session failed: %s", e)
        return {"error": str(e)}


def handle_stripe_webhook(payload: bytes, sig_header: str) -> dict:
    """
    Verify Stripe webhook signature and process the event.

    Returns {"handled": event_type} on success.
    Returns {"error": message} on failure.
    """
    if not _stripe_configured() or not STRIPE_WEBHOOK_SECRET:
        return {"error": "Billing not configured"}

    try:
        stripe = _get_stripe()
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        return {"error": f"Invalid signature: {e}"}

    event_type = event["type"]

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(event["data"]["object"])
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(event["data"]["object"])
        else:
            logger.info("Unhandled Stripe event: %s", event_type)
    except Exception as e:
        logger.error("Error processing Stripe event %s: %s", event_type, e)
        return {"error": str(e)}

    return {"handled": event_type}


def _handle_checkout_completed(session: dict) -> None:
    """Upgrade the tenant's plan after successful checkout."""
    tenant_id = session.get("metadata", {}).get("tenant_id")
    plan = session.get("metadata", {}).get("plan")
    if not tenant_id or not plan:
        logger.warning("Checkout session missing tenant_id or plan metadata")
        return

    try:
        from src.database import SessionLocal
        from src.db.tenant_repo import update_tenant_plan
        db = SessionLocal()
        try:
            update_tenant_plan(db, tenant_id, plan)
            logger.info("Tenant %s upgraded to plan %s", tenant_id, plan)
        finally:
            db.close()
    except Exception as e:
        logger.error("Failed to update tenant plan after checkout: %s", e)


def _handle_subscription_deleted(subscription: dict) -> None:
    """Downgrade the tenant to free when a subscription is cancelled."""
    tenant_id = subscription.get("metadata", {}).get("tenant_id")
    if not tenant_id:
        logger.warning("Subscription deleted event missing tenant_id metadata")
        return

    try:
        from src.database import SessionLocal
        from src.db.tenant_repo import update_tenant_plan
        db = SessionLocal()
        try:
            update_tenant_plan(db, tenant_id, "free")
            logger.info("Tenant %s downgraded to free after subscription deletion", tenant_id)
        finally:
            db.close()
    except Exception as e:
        logger.error("Failed to downgrade tenant after subscription deleted: %s", e)


def get_subscription_status(tenant_id: str) -> dict:
    """Return the current plan and status for a tenant."""
    try:
        from src.database import SessionLocal
        from src.db.tenant_repo import get_tenant_by_id
        db = SessionLocal()
        try:
            tenant = get_tenant_by_id(db, tenant_id)
            if not tenant:
                return {"plan": "free", "status": "unknown"}
            limit = PLAN_LIMITS.get(tenant.plan)
            return {
                "plan": tenant.plan,
                "status": "active" if tenant.is_active else "inactive",
                "repair_limit": limit,
            }
        finally:
            db.close()
    except Exception as e:
        logger.error("get_subscription_status failed for tenant %s: %s", tenant_id, e)
        return {"plan": "free", "status": "unknown"}
