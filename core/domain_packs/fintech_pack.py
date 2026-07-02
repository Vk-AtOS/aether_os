"""
FinTech Domain Pack for AetherOS.

Carries canonical entity graph, PCI-DSS constraints, integrations, and seed
patterns for generating correct financial application backends and frontends.
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
        name="Account",
        description=(
            "Financial account owned by a user. Balance is computed from "
            "LedgerEntry rows — never stored as a mutable raw column."
        ),
        typical_fields=[
            "id", "account_number",  # ACC-{i:010d}
            "user_id",
            "account_type",  # checking / savings / wallet / credit
            "currency",  # ISO 4217: USD / EUR / GBP / JPY
            "status",  # active / frozen / closed
            "created_at", "updated_at",
        ],
        unique_fields=["account_number"],
        fk_relationships=["user_id -> User.id"],
        compliance_fields=["account_number"],  # PCI: never expose raw in logs
        indexes=["account_number", "user_id", "status"],
    ),
    EntitySpec(
        name="Transaction",
        description=(
            "Immutable financial event record. Amounts stored as Numeric(18,6). "
            "Every transaction generates two LedgerEntry rows (debit + credit)."
        ),
        typical_fields=[
            "id", "reference_id",  # TXN-{YYYY}-{i:08d}
            "from_account_id", "to_account_id",
            "transaction_type",  # debit / credit / transfer / refund / fee
            "amount",   # Numeric(18,6) — never Float
            "currency",
            "description",
            "status",  # pending / completed / failed / reversed
            "stripe_payment_intent_id",  # PCI: token only, no raw card data
            "metadata_json",
            "created_at", "completed_at",
        ],
        unique_fields=["reference_id"],
        fk_relationships=[
            "from_account_id -> Account.id",
            "to_account_id -> Account.id",
        ],
        compliance_fields=[
            "stripe_payment_intent_id",  # PCI: token reference only
            "reference_id",
        ],
        indexes=["reference_id", "from_account_id", "to_account_id", "status", "created_at"],
    ),
    EntitySpec(
        name="Invoice",
        description=(
            "Billing document issued by one party to another. "
            "Amount fields use Numeric(10,2) for two-decimal currency precision."
        ),
        typical_fields=[
            "id", "invoice_number",  # INV-{YYYY}-{i:06d}
            "issuer_account_id", "recipient_account_id",
            "subtotal",   # Numeric(10,2)
            "tax_amount", # Numeric(10,2)
            "total",      # Numeric(10,2)
            "currency",
            "status",  # draft / sent / paid / overdue / cancelled / void
            "due_date", "paid_at",
            "line_items_json",
            "created_at", "updated_at",
        ],
        unique_fields=["invoice_number"],
        fk_relationships=[
            "issuer_account_id -> Account.id",
            "recipient_account_id -> Account.id",
        ],
        compliance_fields=["invoice_number", "total"],
        indexes=["invoice_number", "issuer_account_id", "recipient_account_id", "status"],
    ),
    EntitySpec(
        name="Payment",
        description=(
            "Record of a payment event linked to an Invoice. "
            "Stores Stripe token reference only — no raw card data ever."
        ),
        typical_fields=[
            "id", "payment_reference",  # PAY-{YYYY}-{i:08d}
            "invoice_id", "account_id",
            "amount",    # Numeric(10,2)
            "currency",
            "payment_method",  # card / bank_transfer / wallet / crypto
            "stripe_payment_intent_id",  # PCI: token only — # PCI: no card data stored
            "status",  # pending / succeeded / failed / refunded
            "processor_response_json",  # masked, no raw PAN
            "created_at", "completed_at",
        ],
        unique_fields=["payment_reference", "stripe_payment_intent_id"],
        fk_relationships=[
            "invoice_id -> Invoice.id",
            "account_id -> Account.id",
        ],
        compliance_fields=[
            "stripe_payment_intent_id",  # PCI: token reference only
        ],
        indexes=["payment_reference", "invoice_id", "account_id", "status"],
    ),
    EntitySpec(
        name="Wallet",
        description=(
            "Digital wallet for instant peer-to-peer transfers. "
            "Balance computed from LedgerEntry — never a raw mutable balance column."
        ),
        typical_fields=[
            "id", "wallet_id",  # WLT-{i:010d}
            "user_id",
            "currency",
            "status",  # active / frozen / closed
            "daily_limit",   # Numeric(12,2)
            "monthly_limit", # Numeric(12,2)
            "created_at", "updated_at",
        ],
        unique_fields=["wallet_id"],
        fk_relationships=["user_id -> User.id"],
        compliance_fields=["wallet_id"],
        indexes=["wallet_id", "user_id", "status"],
    ),
    EntitySpec(
        name="AuditLog",
        description=(
            "Immutable financial audit trail. Written on every transaction, "
            "payment, and account-state change. Never updated or deleted."
        ),
        typical_fields=[
            "id", "entity_type", "entity_id",
            "action",  # created / updated / deleted / accessed / payment_processed
            "actor_user_id", "actor_role",
            "ip_address", "user_agent",
            "before_state_json", "after_state_json",
            "timestamp",  # UTC, indexed
        ],
        unique_fields=[],
        fk_relationships=["actor_user_id -> User.id"],
        compliance_fields=[
            "actor_user_id", "timestamp",  # PCI DSS requirement 10
        ],
        indexes=["entity_type", "entity_id", "actor_user_id", "timestamp"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="stripe",
        purpose="Payment processing — payment intents, refunds, customer management, webhooks",
        env_vars=["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY"],
        typical_methods=[
            "stripe.PaymentIntent.create",
            "stripe.PaymentIntent.retrieve",
            "stripe.Refund.create",
            "stripe.Customer.create",
            "stripe.Invoice.create",
            "stripe.Invoice.pay",
        ],
    ),
    IntegrationSpec(
        name="sendgrid",
        purpose="Invoice delivery, payment confirmation, overdue reminders, fraud alerts",
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_invoice",
            "send_payment_confirmation",
            "send_overdue_reminder",
            "send_fraud_alert",
            "send_account_statement",
        ],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    # PCI-DSS card data
    "NEVER store card numbers (PAN), CVV, or PIN in any table, log, or cache — not even temporarily.",
    "Store only the Stripe payment_intent_id or token — add comment '# PCI: no card data stored' next to the field.",
    "Never log or return full card numbers in API responses — if a card reference must be shown, mask all but the last 4 digits: **** **** **** 1234.",
    "Payment processing code MUST be isolated in a dedicated payments.py module — never mix business logic with Stripe calls.",
    # Numeric precision
    "ALL monetary amount columns MUST use Numeric(precision=18, scale=6) for high-value assets, or Numeric(10, 2) for standard currency — NEVER Float or plain int.",
    "Never perform float arithmetic on currency — use Python's Decimal type for all in-memory computations.",
    # Ledger integrity
    "Every financial transaction MUST create exactly 2 LedgerEntry rows (one debit, one credit) that sum to zero — implement double-entry bookkeeping.",
    "Account balance MUST be computed from SUM(LedgerEntry) — never stored as a mutable column that can go out of sync.",
    "Amount columns MUST have a DB-level non-negative CheckConstraint('amount >= 0', name='ck_amount_non_negative').",
    # Audit and immutability
    "Every transaction, payment, and account state change MUST write an AuditLog record (entity_type, entity_id, action, actor_user_id, ip_address, timestamp).",
    "Transaction records are IMMUTABLE after status='completed' — implement a DB-level trigger or application-level guard that rejects UPDATE on completed rows.",
    "Transaction reference IDs MUST follow format TXN-{YYYY}-{i:08d} and be globally unique.",
    "Invoice numbers MUST follow format INV-{YYYY}-{i:06d} and be unique.",
    "Account numbers MUST follow format ACC-{i:010d} and be unique and indexed.",
    # API security
    "Payment endpoints MUST be logged: log user_id, account_id, amount, currency, action — but NEVER log the full card token or secret key.",
    "All payment and account endpoints require auth — no public financial data endpoints.",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    "account_number": "ACC-{i:010d}",
    "reference_id": "TXN-2026-{i:08d}",
    "invoice_number": "INV-2026-{i:06d}",
    "payment_reference": "PAY-2026-{i:08d}",
    "wallet_id": "WLT-{i:010d}",
    "stripe_payment_intent_id": "pi_test_{i:020d}",
    "amount": "{50 + i * 17}.{(i * 13) % 100:02d}",
    "currency": "USD|EUR|GBP|JPY|CAD",
    "account_type": "checking|savings|wallet|credit",
    "transaction_type": "debit|credit|transfer|refund|fee",
    "status_transaction": "pending|completed|failed|reversed",
    "status_invoice": "draft|sent|paid|overdue|cancelled",
    "payment_method": "card|bank_transfer|wallet",
    "email": "user_{i}@example.com",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Double-entry bookkeeping: every money movement writes two LedgerEntry rows — a debit on one account and a credit on another; they must sum to zero.",
    "Balance computation: compute account balance as SELECT COALESCE(SUM(amount), 0) FROM ledger_entries WHERE account_id=? AND type='credit' MINUS debits — never trust a cached balance column.",
    "Idempotency: payment endpoints must accept an idempotency_key (UUID) and deduplicate on it — Stripe supports this natively.",
    "Webhooks: handle Stripe webhook events (payment_intent.succeeded, payment_intent.payment_failed) and reconcile AuditLog entries.",
    "Currency: always store currency as ISO 4217 3-letter code (USD, EUR, GBP) in an Enum column, never a free-form string.",
    "Rate limiting: apply per-user rate limiting on payment endpoints (max 10 payments/minute) to prevent card testing attacks.",
    "Fraud detection: flag transactions > $10,000 or more than 5 failed attempts in 1 hour for manual review — write FRAUD_FLAG to AuditLog.",
    "PCI scope isolation: isolate payment processing code behind an internal API boundary; the main app should never touch raw card data.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

FINTECH_PACK = DomainPack(
    domain="fintech",
    display_name="FinTech / Payments",
    description=(
        "Financial technology platform supporting accounts, transactions, invoices, "
        "payments, wallets, and PCI-DSS-compliant audit trails with double-entry bookkeeping."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["PCI-DSS"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["FINTECH_PACK"]
