"""
Marketplace Domain Pack for AetherOS.

Carries canonical entity graph, constraints, integrations, and seed patterns
for generating correct two-sided marketplace backends and frontends.
"""
from __future__ import annotations

from aether_os.core.domain_packs import (
    DomainPack,
    EntitySpec,
    IntegrationSpec,
)

# ── Entities ──────────────────────────────────────────────────────────────────

_ENTITIES = [
    EntitySpec(
        name="Category",
        description=(
            "Product taxonomy node forming a tree via parent_id self-FK. "
            "parent_id is nullable (root categories have no parent)."
        ),
        typical_fields=[
            "id", "name", "slug", "description",
            "parent_id",  # nullable FK to self — Category tree
            "image_url", "sort_order", "is_active",
            "created_at", "updated_at",
        ],
        unique_fields=["slug"],
        fk_relationships=["parent_id -> Category.id"],  # nullable self-referential FK
        compliance_fields=[],
        indexes=["slug", "parent_id", "is_active"],
    ),
    EntitySpec(
        name="Seller",
        description=(
            "Verified merchant account. Sellers list products and receive "
            "payouts via Stripe Connect."
        ),
        typical_fields=[
            "id", "user_id",
            "business_name", "slug",
            "description", "logo_url",
            "stripe_account_id",  # Stripe Connect account for payouts
            "is_verified", "is_active",
            "commission_rate",  # platform commission: Numeric(5,4)
            "rating_avg",       # Numeric(3,2) — computed from Reviews
            "total_sales",
            "created_at", "updated_at",
        ],
        unique_fields=["user_id", "slug", "stripe_account_id"],
        fk_relationships=["user_id -> User.id"],
        compliance_fields=["stripe_account_id"],
        indexes=["slug", "user_id", "is_verified", "is_active"],
    ),
    EntitySpec(
        name="Buyer",
        description="Registered buyer who can place orders and leave reviews.",
        typical_fields=[
            "id", "user_id",
            "display_name", "avatar_url",
            "shipping_address_json",
            "billing_address_json",
            "is_active",
            "created_at", "updated_at",
        ],
        unique_fields=["user_id"],
        fk_relationships=["user_id -> User.id"],
        compliance_fields=[],
        indexes=["user_id", "is_active"],
    ),
    EntitySpec(
        name="Listing",
        description=(
            "An item listed for sale by a Seller. A Listing is the marketplace "
            "wrapper around a Product — it can have condition, price override, "
            "and listing-specific availability."
        ),
        typical_fields=[
            "id", "seller_id", "product_id",
            "title", "description",
            "price",       # Numeric(12,2) — listing price may differ from product price
            "currency",
            "condition",   # new / used_like_new / used_good / used_fair / refurbished
            "quantity_available",
            "is_active", "is_featured",
            "views_count", "saves_count",
            "created_at", "updated_at",
        ],
        unique_fields=[],
        fk_relationships=[
            "seller_id -> Seller.id",
            "product_id -> Product.id",
        ],
        compliance_fields=[],
        indexes=["seller_id", "product_id", "is_active", "price"],
    ),
    EntitySpec(
        name="Product",
        description=(
            "Canonical product definition in the marketplace catalog. "
            "Belongs to a Category and may be listed by multiple Sellers."
        ),
        typical_fields=[
            "id", "name", "slug", "description",
            "category_id",
            "brand", "model_number",
            "base_price",   # Numeric(12,2)
            "currency",
            "image_urls_json",  # list of CDN URLs — no BLOBs in DB
            "attributes_json",  # color, size, weight, etc.
            "rating_avg",       # Numeric(3,2) — computed from Reviews
            "review_count",
            "is_active",
            "created_at", "updated_at",
        ],
        unique_fields=["slug"],
        fk_relationships=["category_id -> Category.id"],
        compliance_fields=[],
        indexes=["slug", "category_id", "is_active", "base_price"],
    ),
    EntitySpec(
        name="Order",
        description=(
            "Buyer order for one or more Listings. Contains snapshot of prices "
            "at time of purchase. References a completed payment."
        ),
        typical_fields=[
            "id", "reference_number",  # ORD-{YYYY}-{i:06d}
            "buyer_id",
            "status",  # pending / confirmed / processing / shipped / delivered / cancelled / refunded
            "subtotal",    # Numeric(12,2)
            "platform_fee",  # Numeric(12,2) — marketplace commission
            "tax_amount",   # Numeric(12,2)
            "shipping_amount",  # Numeric(12,2)
            "shipping_address_json",
            "stripe_payment_intent_id",  # PCI: no raw card data
            "created_at", "updated_at", "delivered_at",
        ],
        unique_fields=["reference_number", "stripe_payment_intent_id"],
        fk_relationships=["buyer_id -> Buyer.id"],
        compliance_fields=["stripe_payment_intent_id"],  # PCI
        indexes=["reference_number", "buyer_id", "status", "created_at"],
    ),
    EntitySpec(
        name="Review",
        description=(
            "Buyer review on a completed Order's Listing. "
            "A Review MUST reference a completed Order — enforce at application layer."
        ),
        typical_fields=[
            "id", "buyer_id", "seller_id", "product_id", "order_id",
            "rating",  # Integer 1–5
            "title", "body",
            "is_verified",  # True only if order.status == 'delivered'
            "seller_response",  # seller can reply to review
            "created_at", "updated_at",
        ],
        unique_fields=[],
        fk_relationships=[
            "buyer_id -> Buyer.id",
            "seller_id -> Seller.id",
            "product_id -> Product.id",
            "order_id -> Order.id",
        ],
        compliance_fields=[],
        indexes=["buyer_id", "seller_id", "product_id", "order_id", "rating"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="stripe",
        purpose="Buyer payments and Stripe Connect seller payouts with platform commission split",
        env_vars=[
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
            "STRIPE_PUBLISHABLE_KEY", "STRIPE_PLATFORM_ACCOUNT_ID",
        ],
        typical_methods=[
            "stripe.PaymentIntent.create",
            "stripe.Transfer.create",          # seller payout
            "stripe.Account.create",           # Stripe Connect onboarding
            "stripe.AccountLink.create",       # onboarding link for seller
            "stripe.checkout.Session.create",
        ],
    ),
    IntegrationSpec(
        name="sendgrid",
        purpose="Order confirmations, seller payout notifications, review request emails",
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_order_confirmation",
            "send_order_shipped",
            "send_payout_notification",
            "send_review_request",
            "send_seller_new_order",
        ],
    ),
    IntegrationSpec(
        name="twilio",
        purpose="SMS delivery alerts and urgent order status notifications",
        env_vars=["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
        typical_methods=["client.messages.create"],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    # Entity relationship rules
    "Product MUST have FK category_id -> Category.id (non-nullable) — every product belongs to a category.",
    "Listing MUST have FK seller_id -> Seller.id (non-nullable) — only verified sellers can list products.",
    "Order MUST have FK buyer_id -> Buyer.id (non-nullable) — all orders must be traced to a buyer.",
    "Review MUST reference a completed Order — validate order.status == 'delivered' before allowing review creation; reject with HTTP 422 otherwise.",
    "Category tree: parent_id is nullable FK to Category.id — root categories have parent_id=None; enforce no circular parent references at application layer.",
    # Pricing and commission
    "All price and amount columns MUST use Numeric(12,2) — never Float (prevents currency rounding errors).",
    "Order total is computed as subtotal + tax_amount + shipping_amount — never store a redundant total column.",
    "Platform fee (commission) MUST be computed and stored at order creation time, not recalculated later.",
    # Payment security (PCI)
    "NEVER store raw card data — store only stripe_payment_intent_id; add comment '# PCI: no card data stored'.",
    "Order status MUST use an Enum: pending / confirmed / processing / shipped / delivered / cancelled / refunded.",
    # Seller payouts
    "Seller payout MUST deduct platform_fee before transferring via Stripe Connect — never pay full order amount.",
    "Stripe Connect seller onboarding MUST be completed before a Seller can receive payouts — check stripe_account_id is set.",
    # Review integrity
    "A Buyer may leave only one Review per Order — enforce UNIQUE constraint on (buyer_id, order_id).",
    "Review rating MUST be Integer between 1 and 5 — enforce CheckConstraint('rating >= 1 AND rating <= 5').",
    "Order reference numbers MUST follow format ORD-{YYYY}-{i:06d} and be unique.",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    "reference_number": "ORD-2026-{i:06d}",
    "stripe_payment_intent_id": "pi_test_{i:020d}",
    "slug": "{entity_lower}-{i}",
    "email": "user_{i}@example.com",
    "base_price": "{10 + i * 7}.99",
    "price": "{12 + i * 8}.99",
    "currency": "USD|EUR|GBP",
    "condition": "new|used_like_new|used_good|refurbished",
    "status_order": "pending|confirmed|shipped|delivered|cancelled",
    "rating": "1|2|3|4|5",
    "commission_rate": "0.0{(i % 5) + 5}",
    "stripe_account_id": "acct_test_{i:016d}",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Two-sided marketplace: Buyer and Seller are profile entities that wrap User — a single User can be both Buyer and Seller.",
    "Stripe Connect: use destination charges so the platform collects payment, deducts commission, and transfers to the seller's connected account.",
    "Category tree: implement recursive CTE (WITH RECURSIVE) for fetching category hierarchy — avoid N+1 queries on parent lookups.",
    "Review gate: in the review creation endpoint, query Order to confirm status='delivered' and buyer_id matches — enforce at service layer.",
    "Product images: store image_urls_json as an array of CDN URLs — never store binary blobs in the database.",
    "Seller rating: maintain rating_avg on Seller as a denormalized column updated via background task after each review; include review_count for Bayesian averaging.",
    "Search: add PostgreSQL GIN full-text index on Product.name + Product.description + Listing.title for keyword search.",
    "Order total: compute dynamically from Listing prices and quantities; store subtotal, platform_fee, tax, shipping as separate columns for auditability.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

MARKETPLACE_PACK = DomainPack(
    domain="marketplace",
    display_name="Two-Sided Marketplace",
    description=(
        "Two-sided marketplace platform connecting Sellers and Buyers with "
        "product listings, order management, Stripe Connect payouts, and verified reviews."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["PCI-DSS"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["MARKETPLACE_PACK"]
