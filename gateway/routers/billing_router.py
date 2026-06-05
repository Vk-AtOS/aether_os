"""
AetherOS — Billing Router
GET /billing/plans
POST /billing/create-order
POST /billing/verify-payment
POST /billing/webhook
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])

RAZORPAY_PLANS: Dict[str, Dict] = {
    "pro":        {"name": "Pro",        "amount": 99900,  "currency": "INR", "period": "monthly"},
    "enterprise": {"name": "Enterprise", "amount": 499900, "currency": "INR", "period": "monthly"},
}


def _razorpay_client():
    import razorpay
    key_id     = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment gateway not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
    return razorpay.Client(auth=(key_id, key_secret))


def _current_user():
    return Depends(get_current_user)


@router.get("/billing/plans")
async def list_plans():
    """Return available subscription plans (public endpoint)."""
    return {
        "plans": [
            {
                "id": "trial",
                "name": "Trial",
                "price_inr": 0,
                "period": "forever",
                "runs": 3,
                "storage_gb": 0.5,
                "features": ["3 factory runs", "500 MB artifact storage", "All 12 phases", "Community support"],
                "cta": "Start Free Trial",
            },
            {
                "id": "pro",
                "name": "Pro",
                "price_inr": 999,
                "period": "month",
                "runs": None,  # unlimited
                "storage_gb": 10,
                "features": ["Unlimited runs", "10 GB storage", "Priority queue", "Email support",
                             "Codebase import (GitHub/GitLab/SSH)", "CLI + VS Code extension"],
                "cta": "Upgrade to Pro",
                "highlight": True,
            },
            {
                "id": "enterprise",
                "name": "Enterprise",
                "price_inr": 4999,
                "period": "month",
                "runs": None,
                "storage_gb": 100,
                "features": ["Everything in Pro", "100 GB storage", "Dedicated support SLA",
                             "SSO / SAML", "Custom LLM models", "On-prem deployment", "SLA 99.9%"],
                "cta": "Contact Sales",
            },
        ]
    }


@router.post("/billing/create-order")
async def create_order(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Create a Razorpay order for a plan upgrade."""
    import uuid as _uuid_rz
    plan_id = req.get("plan", "pro").lower()
    if plan_id not in RAZORPAY_PLANS:
        raise HTTPException(status_code=422, detail=f"Unknown plan: {plan_id}. Choose pro or enterprise.")
    plan = RAZORPAY_PLANS[plan_id]
    client = _razorpay_client()
    receipt = f"aether_{user['org_id'][:8]}_{plan_id}_{int(time.time())}"
    order = client.order.create({
        "amount":   plan["amount"],
        "currency": plan["currency"],
        "receipt":  receipt,
        "notes": {
            "org_id":  user["org_id"],
            "plan":    plan_id,
            "user_id": user["user_id"],
        },
    })
    return {
        "order_id":   order["id"],
        "amount":     order["amount"],
        "currency":   order["currency"],
        "plan":       plan_id,
        "plan_name":  plan["name"],
        "key_id":     os.environ.get("RAZORPAY_KEY_ID", ""),
    }


@router.post("/billing/verify-payment")
async def verify_payment(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Verify Razorpay payment signature and upgrade org plan."""
    import hmac as _hmac, hashlib as _hashlib
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import select as _sel, update as _upd

    order_id   = req.get("razorpay_order_id", "")
    payment_id = req.get("razorpay_payment_id", "")
    signature  = req.get("razorpay_signature", "")
    plan_id    = req.get("plan", "pro").lower()

    if not order_id or not payment_id or not signature:
        raise HTTPException(status_code=422, detail="razorpay_order_id, razorpay_payment_id, razorpay_signature are required")
    if plan_id not in RAZORPAY_PLANS:
        raise HTTPException(status_code=422, detail="Invalid plan")

    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_secret:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")

    # Verify HMAC-SHA256 signature
    msg = f"{order_id}|{payment_id}".encode()
    expected = _hmac.new(key_secret.encode(), msg, _hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    # Upgrade org plan in DB
    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            _upd(Organisation)
            .where(Organisation.id == user["org_id"])
            .values(plan=plan_id)
        )
        await session.commit()

    # Log payment
    logger.info(f"Payment verified: org={user['org_id']} plan={plan_id} payment={payment_id}")
    return {
        "success": True,
        "plan":    plan_id,
        "message": f"Successfully upgraded to {RAZORPAY_PLANS[plan_id]['name']}",
    }


@router.get("/billing/invoices")
async def list_invoices(user: Dict[str, Any] = _current_user()):
    """Return invoices for the authenticated org.

    If Stripe is configured and the org has a stripe_customer_id, real invoices
    are fetched from Stripe.  Otherwise returns an empty list (Razorpay orgs can
    view payment history through the Razorpay dashboard).
    """
    org_id = user["org_id"]

    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if stripe_key:
        try:
            import stripe as _stripe  # type: ignore[import]
            _stripe.api_key = stripe_key

            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Organisation
            from sqlalchemy import select as _sel
            sf = get_session_factory()
            async with sf() as session:
                row = (await session.execute(
                    _sel(Organisation).where(Organisation.id == org_id)
                )).scalar_one_or_none()
            customer_id = getattr(row, "stripe_customer_id", None) if row else None

            if customer_id:
                raw = _stripe.Invoice.list(customer=customer_id, limit=50)
                invoices = [
                    {
                        "id": inv.id,
                        "number": inv.number,
                        "status": inv.status,
                        "amount_paid": inv.amount_paid,
                        "currency": inv.currency,
                        "period_start": inv.period_start,
                        "period_end": inv.period_end,
                        "hosted_invoice_url": inv.hosted_invoice_url,
                        "invoice_pdf": inv.invoice_pdf,
                        "created": inv.created,
                    }
                    for inv in raw.data
                ]
                return {"invoices": invoices, "total": len(invoices), "org_id": org_id}
        except Exception as exc:
            logger.warning("Stripe invoice fetch failed: %s", exc)

    return {"invoices": [], "total": 0, "org_id": org_id, "note": "No billing provider configured or no invoices found."}


@router.post("/billing/cancel")
async def cancel_subscription(user: Dict[str, Any] = _current_user()):
    """Cancel active subscription via Stripe (if configured) then downgrade org to free."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import select as _sel_cancel, update as _upd_cancel

    org_id = user["org_id"]

    # If Stripe is configured, cancel the active subscription there first
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if stripe_key:
        try:
            import stripe as _stripe  # type: ignore[import]
            _stripe.api_key = stripe_key
            sf = get_session_factory()
            async with sf() as session:
                row = (await session.execute(
                    _sel_cancel(Organisation).where(Organisation.id == org_id)
                )).scalar_one_or_none()
            customer_id = getattr(row, "stripe_customer_id", None) if row else None
            if customer_id:
                subs = _stripe.Subscription.list(customer=customer_id, status="active", limit=5)
                for sub in subs.data:
                    _stripe.Subscription.cancel(sub.id)
                    logger.info("Cancelled Stripe subscription %s for org %s", sub.id, org_id)
        except Exception as _stripe_err:
            logger.warning("Stripe subscription cancel failed (proceeding with DB downgrade): %s", _stripe_err)

    # Always update the plan in DB regardless of Stripe outcome
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(
                _upd_cancel(Organisation)
                .where(Organisation.id == org_id)
                .values(plan="free")
            )
            await session.commit()
    except Exception as _e:
        logger.warning("cancel_subscription DB update failed: %s", _e)

    return {"success": True, "plan": "free", "message": "Subscription cancelled. Plan downgraded to free."}


_VALID_DOWNGRADE_PLANS = {"free", "trial", "starter", "pro", "enterprise"}


@router.post("/billing/downgrade")
async def downgrade_subscription(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Downgrade the org to a lower plan."""
    target_plan = req.get("target_plan", "").lower()
    if target_plan not in _VALID_DOWNGRADE_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid target_plan: {target_plan}. Choose from: {sorted(_VALID_DOWNGRADE_PLANS)}")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import update as _upd_down
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(
                _upd_down(Organisation)
                .where(Organisation.id == user["org_id"])
                .values(plan=target_plan)
            )
            await session.commit()
    except Exception as _e:
        logger.warning("downgrade_subscription DB update failed: %s", _e)
    return {"success": True, "plan": target_plan, "message": f"Plan downgraded to {target_plan}."}


@router.post("/billing/webhook")
async def razorpay_webhook(request: Request):
    """Handle Razorpay webhook events (payment.captured, subscription events)."""
    import hmac as _hmac_wh, hashlib as _hashlib_wh
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import update as _upd_wh

    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured. Set RAZORPAY_WEBHOOK_SECRET.")

    body = await request.body()

    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = _hmac_wh.new(webhook_secret.encode(), body, _hashlib_wh.sha256).hexdigest()
    if not _hmac_wh.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Webhook signature invalid")

    payload = await request.json()
    event   = payload.get("event", "")
    entity  = payload.get("payload", {}).get("payment", {}).get("entity", {})
    notes   = entity.get("notes", {})
    org_id  = notes.get("org_id", "")
    plan_id = notes.get("plan", "")

    if event in ("payment.captured", "order.paid") and org_id and plan_id in RAZORPAY_PLANS:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(
                _upd_wh(Organisation)
                .where(Organisation.id == org_id)
                .values(plan=plan_id)
            )
            await session.commit()
        logger.info(f"Webhook: upgraded org={org_id} to plan={plan_id}")

    return {"received": True}
