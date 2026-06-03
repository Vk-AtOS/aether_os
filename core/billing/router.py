"""
AetherOS — Billing Provider Router

Routes payment processing to the correct gateway based on org country.
India (IN/IND/INDIA) → Razorpay
All others → Stripe
"""
from __future__ import annotations


def get_billing_provider(org) -> str:
    """Return 'razorpay' for India orgs, 'stripe' for all others."""
    country = (getattr(org, "country", None) or "").upper().strip()
    return "razorpay" if country in ("IN", "IND", "INDIA") else "stripe"
