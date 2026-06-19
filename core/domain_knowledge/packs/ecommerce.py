"""E-commerce domain knowledge pack — orders, inventory, cart, fulfilment, PCI-DSS."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    ComplianceRule, DomainKnowledgePack, EntityTemplate, FieldDef, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="ecommerce",
    display_name="E-Commerce / Retail",

    entities=[
        EntityTemplate(
            name="Product", table="products",
            description="Catalogue item available for sale",
            fields=[
                FieldDef("sku", "string"),
                FieldDef("name", "string"),
                FieldDef("description", "text"),
                FieldDef("price_cents", "int"),          # always store in minor units
                FieldDef("compare_at_price_cents", "int", required=False),
                FieldDef("currency", "string"),           # ISO 4217
                FieldDef("category_id", "fk"),
                FieldDef("brand", "string"),
                FieldDef("weight_grams", "int"),
                FieldDef("status", "string"),             # active | draft | archived
                FieldDef("is_digital", "bool"),
            ],
            indexes=["sku", "category_id", "status"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="Inventory", table="inventory",
            description="Stock levels per product variant per warehouse",
            fields=[
                FieldDef("product_id", "fk"),
                FieldDef("variant_id", "fk"),
                FieldDef("warehouse_id", "fk"),
                FieldDef("quantity_on_hand", "int"),
                FieldDef("quantity_reserved", "int"),
                FieldDef("reorder_point", "int"),
                FieldDef("reorder_quantity", "int"),
            ],
            indexes=["product_id", "warehouse_id"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Cart", table="carts",
            description="User shopping session — items before checkout",
            fields=[
                FieldDef("user_id", "fk", pii=True),
                FieldDef("session_id", "string"),         # anonymous cart support
                FieldDef("status", "string"),             # active | merged | abandoned | converted
                FieldDef("currency", "string"),
                FieldDef("expires_at", "datetime"),
            ],
            indexes=["user_id", "session_id", "status"],
            soft_delete=False,
        ),
        EntityTemplate(
            name="CartItem", table="cart_items",
            description="Single line item within a cart",
            fields=[
                FieldDef("cart_id", "fk"),
                FieldDef("product_id", "fk"),
                FieldDef("variant_id", "fk"),
                FieldDef("quantity", "int"),
                FieldDef("unit_price_cents", "int"),      # price at time of adding
            ],
            indexes=["cart_id", "product_id"],
        ),
        EntityTemplate(
            name="Order", table="orders",
            description="Confirmed purchase — immutable financial record",
            fields=[
                FieldDef("user_id", "fk", pii=True),
                FieldDef("order_number", "string"),        # human-readable, unique
                FieldDef("status", "string"),
                FieldDef("subtotal_cents", "int"),
                FieldDef("tax_cents", "int"),
                FieldDef("shipping_cents", "int"),
                FieldDef("discount_cents", "int"),
                FieldDef("total_cents", "int"),
                FieldDef("currency", "string"),
                FieldDef("shipping_address_id", "fk"),
                FieldDef("billing_address_id", "fk"),
                FieldDef("payment_method_id", "fk"),
                FieldDef("notes", "text", required=False),
            ],
            indexes=["user_id", "order_number", "status"],
            audit_trail=True, soft_delete=False,          # orders are immutable
        ),
        EntityTemplate(
            name="OrderItem", table="order_items",
            description="Line item snapshot — frozen at checkout time",
            fields=[
                FieldDef("order_id", "fk"),
                FieldDef("product_id", "fk"),
                FieldDef("variant_id", "fk"),
                FieldDef("sku", "string"),
                FieldDef("name", "string"),
                FieldDef("quantity", "int"),
                FieldDef("unit_price_cents", "int"),
                FieldDef("total_price_cents", "int"),
            ],
            indexes=["order_id"],
        ),
        EntityTemplate(
            name="Fulfilment", table="fulfilments",
            description="Shipment tracking for an order or partial order",
            fields=[
                FieldDef("order_id", "fk"),
                FieldDef("carrier", "string"),
                FieldDef("tracking_number", "string"),
                FieldDef("status", "string"),             # pending | picked | packed | shipped | delivered | failed
                FieldDef("shipped_at", "datetime", required=False),
                FieldDef("estimated_delivery_at", "datetime", required=False),
                FieldDef("delivered_at", "datetime", required=False),
                FieldDef("warehouse_id", "fk"),
            ],
            indexes=["order_id", "tracking_number", "status"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="Review", table="reviews",
            description="Customer product review",
            fields=[
                FieldDef("product_id", "fk"),
                FieldDef("user_id", "fk", pii=True),
                FieldDef("rating", "int"),                # 1-5
                FieldDef("title", "string"),
                FieldDef("body", "text"),
                FieldDef("verified_purchase", "bool"),
                FieldDef("status", "string"),             # pending | approved | rejected
            ],
            indexes=["product_id", "user_id", "status"],
            soft_delete=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="OrderLifecycle",
            entity="Order", field="status",
            states=["pending_payment", "payment_failed", "confirmed", "processing",
                    "partially_shipped", "shipped", "delivered", "return_requested",
                    "returned", "cancelled", "refunded"],
            transitions={
                "pending_payment":   ["confirmed", "payment_failed", "cancelled"],
                "payment_failed":    ["pending_payment", "cancelled"],
                "confirmed":         ["processing", "cancelled"],
                "processing":        ["partially_shipped", "shipped", "cancelled"],
                "partially_shipped": ["shipped"],
                "shipped":           ["delivered"],
                "delivered":         ["return_requested"],
                "return_requested":  ["returned", "delivered"],
                "returned":          ["refunded"],
                "cancelled":         ["refunded"],
                "refunded":          [],
            },
            terminal_states=["delivered", "refunded"],
            description="Order state machine from payment through fulfilment",
        ),
        WorkflowTemplate(
            name="FulfilmentFlow",
            entity="Fulfilment", field="status",
            states=["pending", "picked", "packed", "shipped", "delivered", "failed"],
            transitions={
                "pending":   ["picked", "failed"],
                "picked":    ["packed", "failed"],
                "packed":    ["shipped", "failed"],
                "shipped":   ["delivered", "failed"],
                "delivered": [],
                "failed":    ["pending"],
            },
            terminal_states=["delivered", "failed"],
            description="Warehouse pick-pack-ship lifecycle",
        ),
    ],

    compliance=[
        ComplianceRule("PCI-DSS", "Never store raw card numbers or CVV in order records",
                       ["card_number", "cvv"], "mandatory",
                       "Use payment provider tokens; store last_four only for display"),
        ComplianceRule("PCI-DSS", "All payment-adjacent data access must be logged",
                       [], "mandatory",
                       "Audit trail on orders, payments, refunds tables"),
        ComplianceRule("GDPR", "Customer PII (name, address, email) must be exportable and erasable",
                       ["user_id", "shipping_address_id", "billing_address_id"], "mandatory",
                       "Pseudonymisation endpoint; FHIR-style data export on request"),
        ComplianceRule("GDPR", "Cart abandonment emails require explicit opt-in",
                       ["user_id"], "mandatory",
                       "Check marketing_consent before sending abandoned cart emails"),
        ComplianceRule("TAX", "Store tax amount separately — never fold into price",
                       ["tax_cents", "subtotal_cents", "total_cents"], "mandatory",
                       "Itemised tax on order and line items for VAT reporting"),
    ],

    api_patterns=[
        "GET /products?category=&page=&limit= — paginated catalogue",
        "GET /products/{id} — product detail with variants and inventory",
        "POST /cart — create or get active cart for session/user",
        "POST /cart/{id}/items — add item with quantity",
        "DELETE /cart/{id}/items/{item_id} — remove cart item",
        "POST /checkout — convert cart to order, reserve inventory, charge payment",
        "GET /orders/{id} — order detail with line items and fulfilment",
        "GET /orders/{id}/fulfilment — tracking info",
        "POST /orders/{id}/cancel — cancel with refund",
        "POST /reviews — submit product review",
    ],

    prompt_injection="""ECOMMERCE DOMAIN RULES (mandatory):
1. Store all prices as INTEGER cents/minor units — never use float for money.
2. At checkout, FREEZE all prices in OrderItem — never re-read from Product after order is placed.
3. Inventory must be reserved (quantity_reserved++) atomically when order is placed; release on cancel.
4. Use idempotency keys for payment charges to prevent double-billing.
5. Order records are IMMUTABLE — never UPDATE a placed order. Issue a cancellation + new order instead.
6. Never store raw card data. Store payment provider token and last_four only.
7. Cart must support anonymous sessions (session_id) that merge on login.
8. Tax must be stored as a separate tax_cents field — never embedded in product price.
9. Stock checks must use SELECT FOR UPDATE or optimistic locking to prevent oversell.
10. Fulfilment status transitions must emit webhook events (order.shipped, order.delivered).
""",
)
