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
from aether_os.core.billing.stripe_events import apply_event
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
        raise HTTPException(status_code=502, detail="Payment provider error; try again later")

    logger.info("Stripe checkout session created: org=%s plan=%s session=%s", org_id, plan_id, session.id)
    return {
        "checkout_url": session.url,
        "session_id":   session.id,
        "plan":         plan_id,
    }


@router.post("/billing/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (public: Stripe calls it; the stripe-signature
    header, checked against STRIPE_WEBHOOK_SECRET, is the authentication).

    Paid checkouts and renewals are confirmed with Stripe and applied once
    (core.billing.stripe_events); a canceled subscription moves the org to free.
    """
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhooks are not configured")
    stripe = _stripe_client()   # 503 when the SDK or STRIPE_SECRET_KEY is missing

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, request.headers.get("stripe-signature", ""),
                                               webhook_secret)
    except Exception as exc:
        # Never echo parser or signature errors to the caller.
        logger.warning("Stripe webhook rejected: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook")

    try:
        outcome = await apply_event(stripe, event, _stripe_prices())
    except Exception as exc:
        # 5xx makes Stripe deliver the event again later.
        logger.warning("Stripe webhook %s could not be confirmed: %s", event.get("type"), exc)
        raise HTTPException(status_code=502, detail="Could not confirm the event with Stripe")
    logger.info("Stripe webhook %s %s: %s", event.get("type"), event.get("id"), outcome)
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
        raise HTTPException(status_code=502, detail="Payment provider error; try again later")

    return {"portal_url": portal_session.url}


# ── Helpers ───────────────────────────────────────────────────────────────────

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
