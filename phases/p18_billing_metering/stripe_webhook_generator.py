"""Generates the Stripe webhook handler of a generated app (split out of metering_generator.py).

The emitted module owns one small table, billing_tenants, in the app's own database
(DATABASE_URL), so billing events change real tenant state without assuming the app's schema.
"""
from __future__ import annotations

_TEMPLATE = '''\
"""
Stripe webhook handler for __SLUG__.

Billing state lives in the table billing_tenants (created on first use in DATABASE_URL):
  checkout.session.completed      links the Stripe customer to the tenant (client_reference_id) -> active
  invoice.payment_succeeded       -> active, grace cleared
  invoice.payment_failed          -> past_due, grace period starts once (BILLING_GRACE_DAYS, default 7)
  customer.subscription.deleted   -> suspended (final until a new checkout)
Protect routes with Depends(require_active_billing(tenant_id_dependency)): suspended tenants and
past_due tenants after the grace period get HTTP 402.

Environment: STRIPE_WEBHOOK_SECRET (required: without it every webhook is refused), DATABASE_URL.
Mount: app.include_router(billing_router)
"""
from __future__ import annotations

import logging
import os
import time

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)

billing_router = APIRouter(prefix="/billing", tags=["billing"])
router = billing_router  # the s10 auto-wire imports the name "router"

GRACE_SECONDS = int(os.getenv("BILLING_GRACE_DAYS", "7")) * 86400
_engine = None
_ready = False


def _db_url() -> str:
    url = os.environ["DATABASE_URL"]
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _conn():
    global _engine, _ready
    if _engine is None:
        _engine = create_async_engine(_db_url(), pool_pre_ping=True)
    if not _ready:
        async with _engine.begin() as c:
            await c.execute(text(
                "CREATE TABLE IF NOT EXISTS billing_tenants ("
                "stripe_customer_id VARCHAR(255) PRIMARY KEY, tenant_id VARCHAR(255) NOT NULL, "
                "status VARCHAR(32) NOT NULL, grace_until BIGINT, updated_at BIGINT NOT NULL)"))
            await c.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_billing_tenants_tenant ON billing_tenants (tenant_id)"))
        _ready = True
    return _engine.begin()


async def _get_tenant_by_customer(customer_id: str) -> str | None:
    """tenant_id linked to this Stripe customer at checkout, or None when unknown."""
    async with await _conn() as c:
        row = (await c.execute(text("SELECT tenant_id FROM billing_tenants WHERE stripe_customer_id = :c"),
                               {"c": customer_id})).first()
    return row[0] if row else None


async def _link_customer(customer_id: str, tenant_id: str) -> None:
    async with await _conn() as c:
        await c.execute(text(
            "INSERT INTO billing_tenants (stripe_customer_id, tenant_id, status, grace_until, updated_at) "
            "VALUES (:c, :t, 'active', NULL, :now) ON CONFLICT (stripe_customer_id) DO UPDATE SET "
            "tenant_id = :t, status = 'active', grace_until = NULL, updated_at = :now"),
            {"c": customer_id, "t": tenant_id, "now": int(time.time())})


async def _set_status(customer_id: str, new_status: str) -> bool:
    """Change the tenant's billing status; False when the customer is not linked to a tenant."""
    now = int(time.time())
    # grace starts at the FIRST failed payment; Stripe retries must not extend it
    grace = "COALESCE(grace_until, :g)" if new_status == "past_due" else "NULL"
    async with await _conn() as c:
        res = await c.execute(text(
            f"UPDATE billing_tenants SET status = :s, grace_until = {grace}, updated_at = :now "
            # suspended is final until a new checkout re-links the customer (late invoices must not revive it)
            "WHERE stripe_customer_id = :c AND (status != 'suspended' OR :s = 'suspended')"),
            {"s": new_status, "g": now + GRACE_SECONDS, "now": now, "c": customer_id})
    return res.rowcount > 0


async def tenant_billing_status(tenant_id: str) -> str:
    """'active', 'past_due' (inside grace), 'restricted' (grace over), 'suspended', or 'none' (never billed)."""
    async with await _conn() as c:
        rows = (await c.execute(text("SELECT status, grace_until FROM billing_tenants WHERE tenant_id = :t"),
                                {"t": tenant_id})).all()
    if not rows:
        return "none"
    if any(s == "active" for s, _ in rows):
        return "active"
    if any(s == "past_due" and (g or 0) > time.time() for s, g in rows):
        return "past_due"
    return "restricted" if any(s == "past_due" for s, _ in rows) else "suspended"


def require_active_billing(tenant_id_dependency):
    """FastAPI dependency factory: 402 for suspended tenants and for past_due tenants after the grace period."""
    async def _check(tenant_id: str = Depends(tenant_id_dependency)) -> str:
        state = await tenant_billing_status(str(tenant_id))
        if state in ("suspended", "restricted"):
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Billing {state}")
        return tenant_id
    return _check


@billing_router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
) -> dict:
    """Receive and process Stripe webhook events for __SLUG__."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        # An empty signing secret would let anyone forge events: refuse instead.
        logger.error("stripe_webhook: STRIPE_WEBHOOK_SECRET is not set; refusing event")
        raise HTTPException(status_code=503, detail="Billing webhook not configured")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, secret)
    except stripe.error.SignatureVerificationError as exc:
        logger.warning("stripe_webhook: invalid signature: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from exc
    except Exception as exc:
        logger.warning("stripe_webhook: payload parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Malformed payload") from exc

    event_type = event["type"]
    obj = event["data"]["object"]
    customer_id = obj.get("customer")
    new_status = {
        "invoice.payment_succeeded": "active",
        "invoice.payment_failed": "past_due",
        "customer.subscription.deleted": "suspended",
    }.get(event_type)

    if event_type == "checkout.session.completed":
        tenant_id = obj.get("client_reference_id")
        if not (customer_id and tenant_id):
            logger.warning("stripe_webhook: checkout without customer or client_reference_id; tenant not linked")
        else:
            await _link_customer(customer_id, str(tenant_id))
            logger.info("stripe_webhook: tenant=%s linked and active", tenant_id)
    elif new_status and customer_id:
        if await _set_status(customer_id, new_status):
            logger.info("stripe_webhook: %s -> billing status %s", event_type, new_status)
        else:
            # 200 so Stripe stops retrying an event we can never apply; the log is the alert.
            logger.error("stripe_webhook: %s for a customer with no linked tenant; state unchanged", event_type)
    else:
        logger.debug("stripe_webhook: unhandled event type=%s", event_type)

    return {"received": True, "type": event_type}
'''


def generate_stripe_webhook_handler(slug: str) -> str:
    """FastAPI Stripe webhook endpoint that changes tenant billing state (see the emitted docstring)."""
    return _TEMPLATE.replace("__SLUG__", slug)
