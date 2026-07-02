"""
E-commerce Domain Pack for AetherOS.

Carries canonical entity graph, constraints, integrations, and architecture
notes for generating correct e-commerce backends and frontends.
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
        description="Product taxonomy node; categories form a tree (parent_id self-FK).",
        typical_fields=["id", "name", "slug", "description", "parent_id", "image_url", "is_active", "created_at"],
        unique_fields=["slug"],
        fk_relationships=["parent_id -> Category.id"],
        compliance_fields=[],
        indexes=["slug", "parent_id"],
    ),
    EntitySpec(
        name="Product",
        description="A sellable item with price, SKU, and inventory link.",
        typical_fields=[
            "id", "name", "slug", "description", "sku", "price", "compare_at_price",
            "category_id", "is_active", "is_featured", "weight_grams",
            "created_at", "updated_at",
        ],
        unique_fields=["sku", "slug"],
        fk_relationships=["category_id -> Category.id"],
        compliance_fields=[],
        indexes=["sku", "slug", "category_id", "is_active"],
    ),
    EntitySpec(
        name="ProductVariant",
        description="Size/color variant of a Product; has its own SKU and price override.",
        typical_fields=["id", "product_id", "name", "sku", "price_override", "attributes", "created_at"],
        unique_fields=["sku"],
        fk_relationships=["product_id -> Product.id"],
        compliance_fields=[],
        indexes=["sku", "product_id"],
    ),
    EntitySpec(
        name="ProductImage",
        description="Image attached to a Product; ordered by position.",
        typical_fields=["id", "product_id", "url", "alt_text", "position", "created_at"],
        unique_fields=[],
        fk_relationships=["product_id -> Product.id"],
        compliance_fields=[],
        indexes=["product_id"],
    ),
    EntitySpec(
        name="Inventory",
        description="Stock level per product variant; enforces non-negative quantity.",
        typical_fields=["id", "product_id", "variant_id", "quantity", "reserved_quantity", "updated_at"],
        unique_fields=[],
        fk_relationships=["product_id -> Product.id", "variant_id -> ProductVariant.id"],
        compliance_fields=[],
        indexes=["product_id", "variant_id"],
    ),
    EntitySpec(
        name="Customer",
        description="Registered buyer; may have multiple addresses and orders.",
        typical_fields=[
            "id", "email", "first_name", "last_name", "phone",
            "is_active", "created_at", "updated_at",
        ],
        unique_fields=["email"],
        fk_relationships=[],
        compliance_fields=[],
        indexes=["email"],
    ),
    EntitySpec(
        name="Cart",
        description="Session-based shopping cart using UUID primary key (supports guest checkout).",
        typical_fields=["id", "session_id", "customer_id", "created_at", "updated_at", "expires_at"],
        unique_fields=["session_id"],
        fk_relationships=["customer_id -> Customer.id"],
        compliance_fields=[],
        indexes=["session_id", "customer_id"],
    ),
    EntitySpec(
        name="CartItem",
        description="Line item within a Cart; references product and optional variant.",
        typical_fields=["id", "cart_id", "product_id", "variant_id", "quantity", "unit_price", "added_at"],
        unique_fields=[],
        fk_relationships=[
            "cart_id -> Cart.id",
            "product_id -> Product.id",
            "variant_id -> ProductVariant.id",
        ],
        compliance_fields=[],
        indexes=["cart_id", "product_id"],
    ),
    EntitySpec(
        name="Order",
        description="Confirmed purchase; total computed from OrderItems, never stored redundantly.",
        typical_fields=[
            "id", "reference_number", "customer_id", "status",
            "shipping_address_json", "billing_address_json",
            "subtotal", "tax_amount", "shipping_amount",
            "payment_intent_id",  # PCI: no card data stored
            "created_at", "updated_at", "shipped_at", "delivered_at",
        ],
        unique_fields=["reference_number", "payment_intent_id"],
        fk_relationships=["customer_id -> Customer.id"],
        compliance_fields=["payment_intent_id"],  # PCI compliance field
        indexes=["reference_number", "customer_id", "status"],
    ),
    EntitySpec(
        name="OrderItem",
        description="Line item within an Order; snapshot of price at time of purchase.",
        typical_fields=["id", "order_id", "product_id", "variant_id", "quantity", "unit_price", "line_total"],
        unique_fields=[],
        fk_relationships=[
            "order_id -> Order.id",
            "product_id -> Product.id",
            "variant_id -> ProductVariant.id",
        ],
        compliance_fields=[],
        indexes=["order_id", "product_id"],
    ),
    EntitySpec(
        name="Review",
        description="Customer review on a Product; only one review per customer per product.",
        typical_fields=["id", "product_id", "customer_id", "rating", "title", "body", "is_verified", "created_at"],
        unique_fields=[],
        fk_relationships=["product_id -> Product.id", "customer_id -> Customer.id"],
        compliance_fields=[],
        indexes=["product_id", "customer_id"],
    ),
    EntitySpec(
        name="Coupon",
        description="Discount code with type (percent/fixed), usage limits, and expiry.",
        typical_fields=[
            "id", "code", "discount_type", "discount_value",
            "min_order_amount", "max_uses", "uses_count",
            "is_active", "expires_at", "created_at",
        ],
        unique_fields=["code"],
        fk_relationships=[],
        compliance_fields=[],
        indexes=["code"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="stripe",
        purpose="Payment processing — tokenised card charges, payment intents, refunds",
        env_vars=["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY"],
        typical_methods=[
            "stripe.PaymentIntent.create",
            "stripe.PaymentIntent.retrieve",
            "stripe.Refund.create",
            "stripe.Customer.create",
            "stripe.checkout.Session.create",
        ],
    ),
    IntegrationSpec(
        name="sendgrid",
        purpose="Transactional emails — order confirmation, shipping notification, password reset",
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_order_confirmation",
            "send_shipping_notification",
            "send_password_reset",
        ],
    ),
    IntegrationSpec(
        name="twilio",
        purpose="SMS order status notifications",
        env_vars=["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
        typical_methods=["client.messages.create"],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    "Price/amount fields MUST use Decimal type with NUMERIC(12,2) in the DB — never Float (PCI compliance and precision).",
    "Cart primary key MUST be a UUID (not sequential integer) to support guest checkout without user accounts.",
    "SKU fields must be declared unique=True and indexed=True on the Column definition.",
    "Order status MUST use a Python Enum: pending / confirmed / processing / shipped / delivered / cancelled / refunded — never a free-form string.",
    "NEVER store raw card data — only store payment_intent_id (str) from Stripe; add comment '# PCI: no card data stored' near the field.",
    "Inventory quantity MUST have a DB-level non-negative constraint: CheckConstraint('quantity >= 0', name='ck_quantity_non_negative').",
    "Product price MUST have a DB-level non-negative constraint: CheckConstraint('price >= 0', name='ck_price_non_negative').",
    "Every Order MUST have a unique human-readable reference: ORD-{YYYY}-{N:06d}.",
    "Order total MUST be computed from OrderItems; do not store a redundant 'total' column that can go out of sync.",
    "Stock deduction MUST happen at order confirmation, NOT at cart add — cart items do not reduce inventory.",
    "Cart sessions expire after 30 days — include expires_at column and a background cleanup task.",
    "Product variants (size/color) need a separate ProductVariant entity, not a JSON blob on Product.",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    "email": "customer_{i}@example.com",
    "sku": "SKU-{i:05d}",
    "slug": "{entity_lower}-{i}",
    "reference_number": "ORD-2026-{i:06d}",
    "payment_intent_id": "pi_test_{i:020d}",
    "code": "COUPON{i:03d}",
    "phone": "+1555{i:07d}",
    "url": "https://cdn.example.com/images/{entity_lower}-{i}.jpg",
    "file_path": "/files/{entity_lower}-{i:03d}.pdf",
    "mrn": "MRN-{i:06d}",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Cart: use session-based UUID (no FK to user required), enabling guest checkout before account creation.",
    "Order total: compute dynamically from OrderItems via SQL SUM — never store a redundant total column.",
    "Inventory: deduct stock atomically at order confirmation using SELECT FOR UPDATE to prevent oversell.",
    "Product search: add a full-text index (PostgreSQL GIN) on Product.name + Product.description.",
    "Images: store URL references only (S3/CDN); never store binary blobs in the database.",
    "Pricing: store prices in the smallest currency unit (cents) as Integer, or use Decimal(12,2) — never Float.",
    "Reviews: enforce one-review-per-customer-per-product via a UNIQUE constraint on (product_id, customer_id).",
    "Coupons: validate on checkout (check expiry, max_uses, min_order_amount) before applying discount.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

ECOMMERCE_PACK = DomainPack(
    domain="ecommerce",
    display_name="E-Commerce",
    description=(
        "Online retail platform supporting product catalog, cart, checkout, "
        "order management, inventory, and customer accounts."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["PCI-DSS"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["ECOMMERCE_PACK"]
