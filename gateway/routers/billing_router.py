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
from aether_os.core.billing.payments import apply_paid_order
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation
from sqlalchemy import select as _sel
from sqlalchemy import select as _sel_cancel, update as _upd_cancel
from sqlalchemy import update as _upd_down
import hmac as _hmac, hashlib as _hashlib
import hmac as _hmac_wh, hashlib as _hashlib_wh
import razorpay
import stripe as _stripe  # type: ignore[import]
import uuid as _uuid_rz
logger = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])
RAZORPAY_PLANS: Dict[str, Dict] = {
    "pro":        {"name": "Pro",        "amount": 99900,  "currency": "INR", "period": "monthly"},
    "enterprise": {"name": "Enterprise", "amount": 499900, "currency": "INR", "period": "monthly"},
}
def _razorpay_client():
    key_id     = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment gateway not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
    return razorpay.Client(auth=(key_id, key_secret))
def _current_user():
    return Depends(get_current_user)
def _require_billing_admin(user: Dict[str, Any]) -> None:
    """Plan changes affect the whole org — owner/admin only (API keys have role 'api')."""
    if user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only org owners and admins can change the plan")
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
    order_id   = req.get("razorpay_order_id", "")
    payment_id = req.get("razorpay_payment_id", "")
    signature  = req.get("razorpay_signature", "")
    if not order_id or not payment_id or not signature:
        raise HTTPException(status_code=422, detail="razorpay_order_id, razorpay_payment_id, razorpay_signature are required")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_secret:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")
    # Verify HMAC-SHA256 signature
    msg = f"{order_id}|{payment_id}".encode()
    expected = _hmac.new(key_secret.encode(), msg, _hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Payment signature verification failed")
    # The signature only proves order_id|payment_id is genuine. What was paid for, and
    # by which org, is on the server-side order (notes set in create_order) — never
    # take the plan from the request body, or paying for Pro unlocks Enterprise.
    try:
        order = _razorpay_client().order.fetch(order_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("verify_payment: Razorpay order fetch failed for %s: %s", order_id, exc)
        raise HTTPException(status_code=502, detail="Could not confirm order with payment gateway")
    notes = order.get("notes") or {}
    plan_id = str(notes.get("plan", "")).lower()
    if (
        plan_id not in RAZORPAY_PLANS
        or notes.get("org_id") != user["org_id"]
        or order.get("amount") != RAZORPAY_PLANS[plan_id]["amount"]
        or order.get("status") != "paid"
    ):
        logger.warning("verify_payment: order %s does not match org=%s (plan=%r)", order_id, user["org_id"], plan_id)
        raise HTTPException(status_code=400, detail="Order does not match this organisation or plan")
    # Record the order and upgrade the plan in one transaction. A paid order is
    # good for exactly one upgrade: presented again (after a cancel, or racing
    # itself) it is refused by the unique constraint, not by a check-then-write.
    if not await apply_paid_order("razorpay", order_id, payment_id, user["org_id"], plan_id,
                                  amount=order.get("amount")):
        raise HTTPException(status_code=409, detail="This payment has already been applied")
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
            _stripe.api_key = stripe_key
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
    _require_billing_admin(user)
    org_id = user["org_id"]
    # If Stripe is configured, cancel the active subscription there first
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if stripe_key:
        try:
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
# Lowest to highest. Raising the plan only ever happens through a verified payment.
_PLAN_ORDER = ["free", "trial", "starter", "pro", "enterprise"]
_VALID_DOWNGRADE_PLANS = set(_PLAN_ORDER)
@router.post("/billing/downgrade")
async def downgrade_subscription(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Downgrade the org to a lower plan."""
    target_plan = req.get("target_plan", "").lower()
    if target_plan not in _VALID_DOWNGRADE_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid target_plan: {target_plan}. Choose from: {sorted(_VALID_DOWNGRADE_PLANS)}")
    _require_billing_admin(user)
    # Compare against the plan in the DB (the JWT claim can be an hour stale).
    async with get_session_factory()() as session:
        current_plan = (await session.execute(
            _sel(Organisation.plan).where(Organisation.id == user["org_id"])
        )).scalar_one_or_none()
    # Unknown current plan → treated as lowest, so nothing can be "downgraded" up from it.
    current_rank = _PLAN_ORDER.index(current_plan) if current_plan in _PLAN_ORDER else 0
    if _PLAN_ORDER.index(target_plan) >= current_rank:
        raise HTTPException(status_code=403, detail="target_plan must be lower than the current plan; upgrades require payment")
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
        order_id, payment_id = entity.get("order_id", ""), entity.get("id", "")
        if not order_id or not payment_id:
            # Without ids the event cannot be tied to one payment, so it could be replayed.
            logger.warning("Webhook: %s for org=%s has no order/payment id — not applied", event, org_id)
        elif await apply_paid_order("razorpay", order_id, payment_id, org_id, plan_id,
                                    amount=entity.get("amount")):
            logger.info(f"Webhook: upgraded org={org_id} to plan={plan_id}")
        # else: already applied (by verify-payment or an earlier delivery) — still acknowledge.
    return {"received": True}