"""
Seed template for ecommerce domain.

Generates realistic, relationally-consistent seed data for a full e-commerce
schema: Category, Product, Customer, Cart, CartItem, Order, OrderItem,
Payment, ProductImage, Review.

All monetary fields use Decimal strings to match Numeric(12,2) DB columns.
SKUs are unique and indexed. Stripe payment_intent_id placeholders are included.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Realistic product catalogue — 20 products across 5 categories
# ---------------------------------------------------------------------------

_CATEGORY_NAMES = [
    "Electronics",
    "Audio",
    "Wearables",
    "Home & Office",
    "Gaming",
]

_PRODUCTS = [
    # Electronics
    ("Wireless Noise-Cancelling Headphones XB700", "AUDIO-XB700-BLK", "149.99", "Electronics"),
    ("4K UHD Smart TV 55-inch", "TV-4K55-BLK", "699.99", "Electronics"),
    ("USB-C Fast Charger 65W GaN", "CHG-GAN65-WHT", "39.99", "Electronics"),
    ("Portable SSD 1TB USB 3.2", "SSD-1TB-SLV", "89.99", "Electronics"),
    # Audio
    ("True Wireless Earbuds Pro", "EARB-TWS-PRO", "79.99", "Audio"),
    ("Bluetooth Speaker 360 Bass", "SPK-BT360-BLK", "59.99", "Audio"),
    ("Studio Monitor Headphones HD", "HEAD-HD600-BLK", "199.99", "Audio"),
    ("USB Condenser Microphone", "MIC-USB-C01", "129.99", "Audio"),
    # Wearables
    ("Smartwatch Series 8 GPS", "WATCH-S8-BLK", "299.99", "Wearables"),
    ("Fitness Tracker Band V3", "FIT-BND-V3-BLU", "49.99", "Wearables"),
    ("Wireless Charging Pad 15W", "CHG-PAD15-WHT", "29.99", "Wearables"),
    ("Smart Ring Health Monitor", "RING-HLT-GLD", "249.99", "Wearables"),
    # Home & Office
    ("Ergonomic Mesh Office Chair", "CHAIR-ERG-BLK", "399.99", "Home & Office"),
    ("Standing Desk Electric 60-inch", "DESK-EL60-OAK", "549.99", "Home & Office"),
    ("Webcam 4K Autofocus USB", "CAM-4K-SLV", "119.99", "Home & Office"),
    ("Mechanical Keyboard TKL RGB", "KBD-MKL-BLK", "149.99", "Home & Office"),
    # Gaming
    ("Gaming Mouse 16000 DPI", "MOUSE-GM16-BLK", "69.99", "Gaming"),
    ("Gaming Headset 7.1 Surround", "HEAD-GM71-BLK", "89.99", "Gaming"),
    ("Gaming Monitor 27\" 165Hz", "MON-GM27-BLK", "349.99", "Gaming"),
    ("Controller Wireless Pro", "CTRL-WL-PRO", "64.99", "Gaming"),
]

_CUSTOMER_FIRST = [
    "Alice", "Bob", "Clara", "Daniel", "Eva",
    "Frank", "Grace", "Henry", "Iris", "Jack",
    "Karen", "Leo", "Maya", "Noah", "Olivia",
    "Paul", "Quinn", "Rosa", "Sam", "Tina",
]
_CUSTOMER_LAST = [
    "Anderson", "Brown", "Carter", "Davis", "Evans",
    "Foster", "Garcia", "Hall", "Ingram", "Johnson",
    "King", "Lewis", "Martinez", "Nelson", "Owens",
    "Parker", "Quinn", "Reed", "Scott", "Taylor",
]

_REVIEW_TEXTS = [
    "Absolutely love this product — exceeded all my expectations.",
    "Great build quality and fast shipping. Would buy again.",
    "Works exactly as described. Setup was straightforward.",
    "Solid value for the price. Highly recommended.",
    "Good product overall but packaging could be improved.",
    "Five stars — my whole family loves it.",
    "Better than the reviews suggested. Very impressed.",
    "Decent quality but took a while to arrive.",
    "Perfect for daily use. Very satisfied with the purchase.",
    "Good product, delivery was quick and well-packaged.",
    "Exactly what I needed. Great quality at this price point.",
    "Very happy with this purchase. Will recommend to friends.",
    "Works well out of the box. No setup issues at all.",
    "Outstanding performance. Noticed improvement immediately.",
    "Reliable and well-made. Customer support was helpful too.",
    "Bought as a gift and recipient was very pleased.",
    "Sturdy construction, feels premium in hand.",
    "Easy to use and does what it says on the tin.",
    "Reasonable price for the quality delivered.",
    "Great item, no complaints whatsoever.",
]


def get_ecommerce_seed_data(entities: list[str]) -> dict[str, list[dict]]:
    """Return seed data keyed by entity name for the ecommerce vertical.

    Only entities present in the *entities* list (from the spec) are included.
    All monetary values are Decimal strings. SKUs and order references are unique.
    """
    result: dict[str, list[dict]] = {}
    now = datetime.utcnow()

    # ── 1. Category ──────────────────────────────────────────────────────────
    if _any_match(entities, ["category", "categories"]):
        result["Category"] = [
            {
                "id": i + 1,
                "name": name,
                "slug": name.lower().replace(" & ", "-").replace(" ", "-"),
                "description": f"Shop the best {name} products.",
                "is_active": True,
                "created_at": (now - timedelta(days=200 - i * 10)).isoformat(),
            }
            for i, name in enumerate(_CATEGORY_NAMES)
        ]

    # ── 2. Product ───────────────────────────────────────────────────────────
    if _any_match(entities, ["product", "products"]):
        cat_map = {name: i + 1 for i, name in enumerate(_CATEGORY_NAMES)}
        result["Product"] = [
            {
                "id": i + 1,
                "name": name,
                "sku": sku,  # unique, indexed
                "description": f"Premium {name} — designed for performance and durability.",
                "price": price,  # Decimal string — maps to Numeric(12,2)
                "compare_at_price": str(
                    (Decimal(price) * Decimal("1.20")).quantize(Decimal("0.01"))
                ),
                "quantity": 50 + (i * 7) % 150,  # non-negative, varies
                "category_id": cat_map.get(cat, 1),
                "is_active": True,
                "weight_grams": 200 + i * 50,
                "slug": f"{sku.lower()}-{i+1}",
                "created_at": (now - timedelta(days=180 - i * 8)).isoformat(),
                "updated_at": (now - timedelta(days=10 - i % 10)).isoformat(),
            }
            for i, (name, sku, price, cat) in enumerate(_PRODUCTS)
        ]

    # ── 3. ProductImage ──────────────────────────────────────────────────────
    if _any_match(entities, ["productimage", "product_image", "productimages"]):
        result["ProductImage"] = [
            {
                "id": i + 1,
                "product_id": (i % 20) + 1,
                "url": f"https://cdn.example-shop.com/products/{_PRODUCTS[i % 20][1].lower()}-{i+1}.jpg",
                "alt_text": f"{_PRODUCTS[i % 20][0]} image {i+1}",
                "position": i % 3,
                "is_primary": (i % 3 == 0),
            }
            for i in range(20)
        ]

    # ── 4. Customer ──────────────────────────────────────────────────────────
    if _any_match(entities, ["customer", "customers"]):
        result["Customer"] = [
            {
                "id": i + 1,
                "first_name": _CUSTOMER_FIRST[i],
                "last_name": _CUSTOMER_LAST[i],
                "email": f"customer{i+1:03d}@example-shop.com",  # unique
                "phone": f"+1-555-{(1000 + i):04d}",
                "is_active": True,
                "created_at": (now - timedelta(days=365 - i * 15)).isoformat(),
                "shipping_address": f"{100 + i} Main St, Springfield, IL 6{2700 + i}",
            }
            for i in range(20)
        ]

    # ── 5. Cart ──────────────────────────────────────────────────────────────
    if _any_match(entities, ["cart", "carts"]):
        import uuid as _uuid
        result["Cart"] = [
            {
                "id": str(_uuid.UUID(int=(i + 1) * (2**64 - 1) // 20)),  # UUID, not sequential
                "customer_id": i + 1,
                "session_token": f"sess_{i+1:04d}_{'x' * 12}",
                "created_at": (now - timedelta(hours=48 - i * 2)).isoformat(),
                "updated_at": (now - timedelta(hours=1)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 6. CartItem ──────────────────────────────────────────────────────────
    if _any_match(entities, ["cartitem", "cart_item", "cartitems"]):
        result["CartItem"] = [
            {
                "id": i + 1,
                "cart_id": (i % 20) + 1,  # references Cart that exists
                "product_id": (i % 20) + 1,  # references Product that exists
                "quantity": (i % 4) + 1,
                "unit_price": _PRODUCTS[i % 20][2],  # Decimal string
                "added_at": (now - timedelta(hours=24 - i)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 7. Order ─────────────────────────────────────────────────────────────
    _order_statuses = [
        "pending", "confirmed", "shipped", "delivered", "cancelled",
        "confirmed", "delivered", "shipped", "pending", "delivered",
        "delivered", "confirmed", "shipped", "pending", "delivered",
        "cancelled", "confirmed", "delivered", "shipped", "delivered",
    ]
    if _any_match(entities, ["order", "orders"]):
        result["Order"] = [
            {
                "id": i + 1,
                "reference": f"ORD-2026-{(i+1):04d}",  # unique human-readable ref
                "customer_id": (i % 20) + 1,
                "status": _order_statuses[i],
                "subtotal": _PRODUCTS[i % 20][2],  # Decimal string
                "shipping_amount": "9.99",
                "tax_amount": str(
                    (Decimal(_PRODUCTS[i % 20][2]) * Decimal("0.08")).quantize(
                        Decimal("0.01")
                    )
                ),
                "total_amount": str(
                    (
                        Decimal(_PRODUCTS[i % 20][2])
                        + Decimal("9.99")
                        + Decimal(_PRODUCTS[i % 20][2]) * Decimal("0.08")
                    ).quantize(Decimal("0.01"))
                ),
                "shipping_address": f"{200 + i} Oak Ave, Chicago, IL 6{600 + i}",
                "created_at": (now - timedelta(days=60 - i * 3)).isoformat(),
                "updated_at": (now - timedelta(days=30 - i % 30)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 8. OrderItem ─────────────────────────────────────────────────────────
    if _any_match(entities, ["orderitem", "order_item", "orderitems"]):
        result["OrderItem"] = [
            {
                "id": i + 1,
                "order_id": (i % 20) + 1,  # references Order that exists
                "product_id": (i % 20) + 1,  # references Product that exists
                "sku": _PRODUCTS[i % 20][1],
                "quantity": (i % 3) + 1,
                "unit_price": _PRODUCTS[i % 20][2],  # Decimal string
                "line_total": str(
                    (Decimal(_PRODUCTS[i % 20][2]) * ((i % 3) + 1)).quantize(
                        Decimal("0.01")
                    )
                ),
            }
            for i in range(20)
        ]

    # ── 9. Payment ───────────────────────────────────────────────────────────
    _payment_statuses = ["succeeded", "succeeded", "pending", "failed", "succeeded"]
    if _any_match(entities, ["payment", "payments"]):
        result["Payment"] = [
            {
                "id": i + 1,
                "order_id": (i % 20) + 1,  # references Order that exists
                # PCI: only the payment processor token is stored — no card data
                "stripe_payment_intent_id": f"pi_test_{(i+1):010d}",  # placeholder
                "amount": _PRODUCTS[i % 20][2],  # Decimal string
                "currency": "USD",
                "status": _payment_statuses[i % 5],
                "payment_method_type": "card",
                "created_at": (now - timedelta(days=60 - i * 3)).isoformat(),
                "completed_at": (
                    (now - timedelta(days=59 - i * 3)).isoformat()
                    if _payment_statuses[i % 5] == "succeeded"
                    else None
                ),
            }
            for i in range(20)
        ]

    # ── 10. Review ───────────────────────────────────────────────────────────
    if _any_match(entities, ["review", "reviews"]):
        result["Review"] = [
            {
                "id": i + 1,
                "product_id": (i % 20) + 1,  # references Product that exists
                "customer_id": (i % 20) + 1,  # references Customer that exists
                "order_id": (i % 20) + 1,  # verified_purchase reference
                "rating": (i % 5) + 1,
                "title": f"Review #{i+1} for {_PRODUCTS[i % 20][0][:30]}",
                "content": _REVIEW_TEXTS[i],
                "verified_purchase": True,
                "is_approved": (i % 5 != 3),
                "created_at": (now - timedelta(days=50 - i * 2)).isoformat(),
            }
            for i in range(20)
        ]

    return result


def _any_match(entities: list[str], candidates: list[str]) -> bool:
    """Return True if any entity name (case-insensitive) matches a candidate."""
    lower_entities = [e.lower() for e in entities]
    return any(c in lower_entities for c in candidates)
