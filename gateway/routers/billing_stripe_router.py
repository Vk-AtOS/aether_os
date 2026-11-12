"""
AetherOS — Stripe Billing Router

Routes:
  POST /billing/stripe/checkout  — create a Stripe Checkout Session (plan upgrade)
  POST /billing/stripe/webhook   — handle Stripe webhook events (verifies stripe-signature)
  GET  /billing/stripe/portal    — create a Stripe Customer Portal session

Used for non-India orgs. India orgs use billing_router (Razorpay).
Routing decision is made by core.billing.router.get_billing_provider().
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])

# Stripe plan → price ID mapping (set via env vars)
STRIPE_PRICES: Dict[str, str] = {}


def _stripe_prices() -> Dict[str, str]:
    """Return plan → Stripe Price ID mapping from env, with fallback keys."""
    return {
        "pro":        os.environ.get("STRIPE_PRICE_PRO", ""),
        "enterprise": os.environ.get("STRIPE_PRICE_ENTERPRISE", ""),
    }


def _stripe_client():
    """Return a configured stripe module (lazy import to avoid hard dep at startup)."""
    try:
        import stripe  # type: ignore[import]
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="stripe package not installed. Run: pip install stripe>=7.0.0",
        )
    secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe not configured. Set STRIPE_SECRET_KEY environment variable.",
        )
    stripe.api_key = secret_key
    return stripe


def _current_user():
    return Depends(get_current_user)


@router.post("/billing/stripe/checkout")
async def stripe_checkout(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Create a Stripe Checkout Session for a plan upgrade.

    Body: { "plan": "pro" | "enterprise", "success_url": "...", "cancel_url": "..." }
    Returns: { "checkout_url": "https://checkout.stripe.com/..." }
    """
    plan_id = req.get("plan", "pro").lower()
    prices  = _stripe_prices()
    if plan_id not in prices or not prices[plan_id]:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown plan or price not configured: {plan_id}. "
                   f"Set STRIPE_PRICE_PRO / STRIPE_PRICE_ENTERPRISE.",
        )

    stripe = _stripe_client()

    # Resolve or create Stripe customer for this org
    org_id  = user["org_id"]
    email   = user.get("email", "")

    # Build absolute URLs — caller may pass them; fall back to env-based defaults
    base_url     = os.environ.get("APP_BASE_URL", "http://localhost:3000")
    success_url  = req.get("success_url") or f"{base_url}/billing?upgrade=success"
    cancel_url   = req.get("cancel_url")  or f"{base_url}/billing?upgrade=cancelled"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": prices[plan_id], "quantity": 1}],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=email or None,
            metadata={"org_id": org_id, "plan": plan_id, "user_id": user["user_id"]},
            subscription_data={"metadata": {"org_id": org_id, "plan": plan_id}},
        )
    except Exception as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")

    logger.info("Stripe checkout session created: org=%s plan=%s session=%s", org_id, plan_id, session.id)
    return {
        "checkout_url": session.url,
        "session_id":   session.id,
        "plan":         plan_id,
    }


@router.post("/billing/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events.

    Stripe sends events to this endpoint; we verify the stripe-signature header
    with STRIPE_WEBHOOK_SECRET and process checkout.session.completed and
    customer.subscription.deleted to update org plan in the database.
    """
    import json as _json

    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(status_code=500, detail="STRIPE_WEBHOOK_SECRET not configured")

    stripe = _stripe_client()

    payload   = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Stripe webhook signature verification failed")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook parse error: {exc}")

    event_type = event["type"]
    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        session   = event["data"]["object"]
        meta      = session.get("metadata", {})
        org_id    = meta.get("org_id", "")
        plan_id   = meta.get("plan", "")
        if org_id and plan_id:
            await _upgrade_org_plan(org_id, plan_id)
            logger.info("Stripe checkout complete: org=%s plan=%s", org_id, plan_id)

    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        meta         = subscription.get("metadata", {})
        org_id       = meta.get("org_id", "")
        if org_id:
            await _upgrade_org_plan(org_id, "free")
            logger.info("Stripe subscription deleted: org=%s → free", org_id)

    elif event_type in ("invoice.payment_failed", "invoice.payment_action_required"):
        invoice = event["data"]["object"]
        # Log for alerting — do not immediately downgrade (grace period policy)
        logger.warning("Stripe payment issue (%s): customer=%s", event_type, invoice.get("customer"))

    return {"received": True}


@router.get("/billing/stripe/portal")
async def stripe_portal(user: Dict[str, Any] = _current_user()):
    """Create a Stripe Customer Portal session for managing the subscription.

    The org must have a stripe_customer_id stored, or we create a new customer.
    Returns: { "portal_url": "https://billing.stripe.com/..." }
    """
    stripe    = _stripe_client()
    org_id    = user["org_id"]
    email     = user.get("email", "")
    base_url  = os.environ.get("APP_BASE_URL", "http://localhost:3000")
    return_url = f"{base_url}/billing"

    # Resolve Stripe customer ID from DB or create one
    customer_id = await _get_or_create_stripe_customer(org_id, email, stripe)

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
    except Exception as exc:
        logger.error("Stripe portal session creation failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")

    return {"portal_url": portal_session.url}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _upgrade_org_plan(org_id: str, plan_id: str) -> None:
    """Persist plan change to the Organisation row."""
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import update as _upd
        sf = get_session_factory()
        async with sf() as session:
            await session.execute(
                # Stripe subscriptions end through Stripe's own webhook, not the one-off payment period.
                _upd(Organisation).where(Organisation.id == org_id).values(plan=plan_id, plan_period_end=None)
            )
            await session.commit()
    except Exception as exc:
        logger.error("_upgrade_org_plan failed: org=%s plan=%s err=%s", org_id, plan_id, exc)


async def _get_or_create_stripe_customer(org_id: str, email: str, stripe) -> str:
    """Return the Stripe customer ID for this org, creating one if needed.

    The customer ID is stored in Organisation.stripe_customer_id when available;
    falls back to creating a new Stripe Customer and storing the ID.
    """
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation
        from sqlalchemy import select as _sel, update as _upd
        sf = get_session_factory()
        async with sf() as session:
            row = (await session.execute(
                _sel(Organisation).where(Organisation.id == org_id)
            )).scalar_one_or_none()

            if row is None:
                raise HTTPException(status_code=404, detail="Organisation not found")

            # Use stored Stripe customer ID if available
            existing_cid = getattr(row, "stripe_customer_id", None)
            if existing_cid:
                return existing_cid

            # Create a new Stripe Customer
            customer = stripe.Customer.create(
                email=email or None,
                metadata={"org_id": org_id},
            )
            cid = customer.id

            # Persist — best-effort, non-fatal if column doesn't exist yet
            try:
                await session.execute(
                    _upd(Organisation)
                    .where(Organisation.id == org_id)
                    .values(stripe_customer_id=cid)
                )
                await session.commit()
            except Exception as _col_err:
                logger.debug(
                    "stripe_customer_id column not yet migrated: %s — customer ID not persisted", _col_err
                )

            return cid
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("_get_or_create_stripe_customer failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not resolve Stripe customer")
