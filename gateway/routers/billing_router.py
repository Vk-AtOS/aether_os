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
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.policy_guard import enforce
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.billing.payments import BillingPayment, apply_paid_order, billing_status
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation
from sqlalchemy import select as _sel
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
def _confirmed_order(order_id: str) -> Optional[Tuple[str, str, int]]:
    """(org_id, plan, amount) of a paid order as Razorpay holds it, or None if it is not one of ours.

    The org and plan come from the notes create_order wrote on the order, and the amount
    must be that plan's price. Both verify-payment and the webhook go through here, so
    neither can be talked into a plan by values the payer controls (the request body, or
    the notes on a payment, which are set at checkout).
    """
    order = _razorpay_client().order.fetch(order_id)
    notes = order.get("notes") or {}
    plan_id = str(notes.get("plan", "")).lower()
    org_id = notes.get("org_id") or ""
    if (not org_id or plan_id not in RAZORPAY_PLANS
            or order.get("amount") != RAZORPAY_PLANS[plan_id]["amount"] or order.get("status") != "paid"):
        return None
    return org_id, plan_id, order["amount"]


def _razorpay_client():
    key_id     = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment gateway not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
    return razorpay.Client(auth=(key_id, key_secret))
def _current_user():
    return Depends(get_current_user)
async def _require_billing_admin(user: Dict[str, Any]) -> None:
    """Plan changes affect the whole org — owner/admin only (API keys have role 'api')."""
    await enforce("billing.change_plan", user)
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
    await _require_billing_admin(user)
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
    await _require_billing_admin(user)
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
    # by which org, is on the server-side order — never taken from the request body.
    try:
        confirmed = _confirmed_order(order_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("verify_payment: Razorpay order fetch failed for %s: %s", order_id, exc)
        raise HTTPException(status_code=502, detail="Could not confirm order with payment gateway")
    if confirmed is None or confirmed[0] != user["org_id"]:
        logger.warning("verify_payment: order %s does not match org=%s", order_id, user["org_id"])
        raise HTTPException(status_code=400, detail="Order does not match this organisation or plan")
    _, plan_id, amount = confirmed
    # Record the order and upgrade the plan in one transaction. A paid order is
    # good for exactly one upgrade: presented again (after a cancel, or racing
    # itself) it is refused by the unique constraint, not by a check-then-write.
    if not await apply_paid_order("razorpay", order_id, payment_id, user["org_id"], plan_id, amount=amount):
        raise HTTPException(status_code=409, detail="This payment has already been applied")
    # Log payment
    logger.info(f"Payment verified: org={user['org_id']} plan={plan_id} payment={payment_id}")
    return {
        "success": True,
        "plan":    plan_id,
        "period_end": ((await billing_status(user["org_id"])) or {}).get("period_end"),
        "message": f"Successfully upgraded to {RAZORPAY_PLANS[plan_id]['name']}",
    }
@router.get("/billing/status")
async def get_billing_status(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """The org's plan in force and when its paid period ends (unix seconds, or null)."""
    status = await billing_status(user["org_id"])
    if status is None:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return status
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
# Lowest to highest. Raising the plan only ever happens through a verified payment.
_PLAN_ORDER = ["free", "trial", "starter", "pro", "enterprise"]
_VALID_DOWNGRADE_PLANS = set(_PLAN_ORDER)
_UNPAID_PLANS = ("free", "trial")


async def _reduce_stripe_billing(org_id: str, target_plan: str) -> None:
    """Provider side of a plan reduction, for orgs that pay through Stripe.

    A plan with a Stripe price (pro) is switched on the live subscription, without proration, so
    renewals bill the lower price (renewals take the plan from the price paid, stripe_events); any
    other target ends the subscription. If Stripe fails the org is still billed at the old price, so
    the plan must not change: 502 and nothing written. Orgs with no Stripe subscription (Razorpay
    pays per period, nothing recurs) have nothing to do here.
    """
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key:
        return
    price = os.environ.get(f"STRIPE_PRICE_{target_plan.upper()}", "") if target_plan not in _UNPAID_PLANS else ""
    try:
        _stripe.api_key = stripe_key
        async with get_session_factory()() as session:
            row = (await session.execute(_sel(Organisation).where(Organisation.id == org_id))).scalar_one_or_none()
        customer_id = getattr(row, "stripe_customer_id", None) if row else None
        if customer_id:
            subs = _stripe.Subscription.list(customer=customer_id, status="active", limit=5).data
        else:
            # Subscribed before the customer id was recorded: only an org that ever paid through Stripe
            # can have a subscription there (a Razorpay org must not depend on Stripe being reachable).
            async with get_session_factory()() as session:
                paid_stripe = (await session.execute(_sel(BillingPayment.id).where(
                    BillingPayment.org_id == org_id, BillingPayment.provider == "stripe").limit(1))).first()
            if not paid_stripe:
                return
            subs = _stripe.Subscription.search(query=f"metadata['org_id']:'{org_id}' AND status:'active'").data
        for sub in subs:
            if price:
                _stripe.Subscription.modify(
                    sub.id, items=[{"id": sub["items"]["data"][0]["id"], "price": price}],
                    proration_behavior="none", metadata={"plan": target_plan})
                logger.info("Moved Stripe subscription %s to %s for org %s", sub.id, target_plan, org_id)
            else:
                _stripe.Subscription.cancel(sub.id)
                logger.info("Cancelled Stripe subscription %s for org %s", sub.id, org_id)
    except Exception as exc:
        logger.error("Stripe plan reduction to %s failed for org %s: %s", target_plan, org_id, exc)
        raise HTTPException(status_code=502, detail="Could not change the subscription with the payment provider; nothing was changed. Try again.")


async def _reduce_plan(user: Dict[str, Any], target_plan: str) -> Dict[str, Any]:
    """The one path for cancel and downgrade, for Razorpay and Stripe orgs alike: the provider first
    (_reduce_stripe_billing), then the org row. Moving to free/trial ends the paid period; a lower paid plan
    keeps the period already paid for. Returns the status after the change."""
    org_id = user["org_id"]
    await _reduce_stripe_billing(org_id, target_plan)
    values: Dict[str, Any] = {"plan": target_plan}
    if target_plan in _UNPAID_PLANS:
        values["plan_period_end"] = None
    try:
        async with get_session_factory()() as session:
            await session.execute(_upd_down(Organisation).where(Organisation.id == org_id).values(**values))
            await session.commit()
    except Exception as exc:
        logger.error("plan reduction DB update failed for org %s: %s", org_id, exc)
        raise HTTPException(status_code=503, detail="Could not update the plan; try again.")
    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id=user.get("user_id", "-"), action="billing.plan_reduced",
        resource_type="organisation", resource_id=org_id, metadata={"plan": target_plan})
    return (await billing_status(org_id)) or {}


@router.post("/billing/cancel")
async def cancel_subscription(user: Dict[str, Any] = _current_user()):
    """Cancel the paid plan: same path as a downgrade to free (provider first, then the org)."""
    await _require_billing_admin(user)
    await _reduce_plan(user, "free")
    return {"success": True, "plan": "free", "message": "Subscription cancelled. Plan downgraded to free."}


@router.post("/billing/downgrade")
async def downgrade_subscription(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Move the org to a lower plan now (owner/admin). A lower paid plan keeps the paid period; free/trial end it."""
    target_plan = str(req.get("target_plan", "")).lower()
    if target_plan not in _VALID_DOWNGRADE_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid target_plan: {target_plan}. Choose from: {sorted(_VALID_DOWNGRADE_PLANS)}")
    await _require_billing_admin(user)
    # Compare against the plan in the DB (the JWT claim can be an hour stale).
    status = await billing_status(user["org_id"])
    current_plan = (status or {}).get("plan")
    # Unknown current plan -> treated as lowest, so nothing can be "downgraded" up from it.
    current_rank = _PLAN_ORDER.index(current_plan) if current_plan in _PLAN_ORDER else 0
    if _PLAN_ORDER.index(target_plan) >= current_rank:
        raise HTTPException(status_code=403, detail="target_plan must be lower than the current plan; upgrades require payment")
    after = await _reduce_plan(user, target_plan)
    return {"success": True, "plan": target_plan, "period_end": after.get("period_end"),
            "message": f"Plan downgraded to {target_plan}."}
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
    order_id, payment_id = entity.get("order_id", ""), entity.get("id", "")
    if event in ("payment.captured", "order.paid"):
        if not order_id or not payment_id:
            # Without ids the event cannot be tied to one payment, so it could be replayed.
            logger.warning("Webhook: %s has no order/payment id — not applied", event)
            return {"received": True}
        try:
            confirmed = _confirmed_order(order_id)
        except Exception as exc:
            # 5xx makes Razorpay deliver the event again later.
            logger.warning("Webhook: could not confirm order %s: %s", order_id, exc)
            raise HTTPException(status_code=502, detail="Could not confirm order with payment gateway")
        if confirmed is None:
            logger.warning("Webhook: order %s is not a paid order for a known plan — not applied", order_id)
        elif await apply_paid_order("razorpay", order_id, payment_id, confirmed[0], confirmed[1], amount=confirmed[2]):
            logger.info("Webhook: upgraded org=%s to plan=%s", confirmed[0], confirmed[1])
        # else: already applied (by verify-payment or an earlier delivery) — still acknowledge.
    return {"received": True}