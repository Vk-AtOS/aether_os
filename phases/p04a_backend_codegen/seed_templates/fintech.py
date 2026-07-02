"""
Seed template for fintech domain.

Generates realistic financial seed data with:
- Account numbers in format ACC-{i:010d}
- Transaction amounts as Decimal strings (2 d.p.) — maps to Numeric(18,6)
- Transaction reference IDs: TXN-{year}-{i:08d}
- Ledger entries: each transaction generates a debit + credit LedgerEntry
- Pre-calculated account balances (sum of credits - sum of debits)

All monetary values are Decimal strings, never Python floats.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_YEAR = 2026

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

_ACCOUNT_TYPES = [
    "checking", "savings", "investment", "credit", "loan",
    "checking", "savings", "investment", "checking", "savings",
    "checking", "credit", "savings", "investment", "checking",
    "savings", "loan", "checking", "investment", "savings",
]

_CURRENCIES = ["USD"] * 14 + ["EUR"] * 3 + ["GBP"] * 2 + ["CAD"]

_TRANSACTION_TYPES = [
    "credit", "debit", "credit", "debit", "credit",
    "debit", "credit", "credit", "debit", "credit",
    "debit", "credit", "debit", "credit", "debit",
    "credit", "debit", "credit", "debit", "credit",
]

_TRANSACTION_DESCRIPTIONS = [
    "Direct deposit — payroll",
    "Utility bill payment",
    "Online transfer received",
    "Grocery store purchase",
    "Freelance invoice payment",
    "Subscription renewal",
    "Wire transfer received",
    "ATM withdrawal",
    "Dividend payment",
    "Insurance premium",
    "Rental income",
    "Credit card payment",
    "Investment return",
    "Tax refund deposit",
    "Healthcare expense",
    "Interest earned",
    "Restaurant purchase",
    "Refund received",
    "Loan disbursement",
    "Consulting fee received",
]

_TRANSACTION_AMOUNTS = [
    "3500.00", "145.67", "1200.00", "87.43", "2500.00",
    "29.99", "5000.00", "200.00", "342.18", "456.00",
    "1800.00", "750.00", "980.55", "1240.00", "320.75",
    "12.50", "65.80", "199.00", "10000.00", "4200.00",
]

_INVOICE_STATUSES = [
    "paid", "pending", "overdue", "paid", "pending",
    "paid", "paid", "overdue", "pending", "paid",
    "paid", "pending", "overdue", "paid", "pending",
    "paid", "paid", "overdue", "pending", "paid",
]

_PAYMENT_PLAN_STATUSES = [
    "active", "active", "completed", "paused", "active",
    "active", "completed", "active", "paused", "active",
    "active", "active", "completed", "active", "paused",
    "active", "active", "completed", "paused", "active",
]


def get_fintech_seed_data(entities: list[str]) -> dict[str, list[dict]]:
    """Return fintech seed data keyed by entity name.

    Account balances are pre-calculated from ledger entries.
    All monetary values are Decimal strings.
    """
    result: dict[str, list[dict]] = {}
    now = datetime.utcnow()

    # ── 1. Account ───────────────────────────────────────────────────────────
    # Account balances are computed from ledger entries — stored here as a
    # pre-calculated snapshot for seed convenience only.
    _account_balances = [
        _compute_balance(i) for i in range(20)
    ]

    if _any_match(entities, ["account", "accounts"]):
        result["Account"] = [
            {
                "id": i + 1,
                "account_number": f"ACC-{(i+1):010d}",  # unique, indexed
                "account_type": _ACCOUNT_TYPES[i],
                "currency": _CURRENCIES[i],
                "owner_name": f"Account Holder {i+1}",
                "owner_email": f"holder{i+1:03d}@fintech-example.com",  # unique
                # Balance is computed from ledger; stored here for display only
                "balance_snapshot": _account_balances[i],  # Decimal string
                "is_active": True,
                "opened_at": (now - timedelta(days=730 - i * 30)).isoformat(),
                "created_at": (now - timedelta(days=730 - i * 30)).isoformat(),
                "updated_at": (now - timedelta(days=1)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 2. Transaction ───────────────────────────────────────────────────────
    if _any_match(entities, ["transaction", "transactions"]):
        result["Transaction"] = [
            {
                "id": i + 1,
                "reference_id": f"TXN-{_YEAR}-{(i+1):08d}",  # unique, indexed
                "account_id": (i % 20) + 1,  # references Account
                "transaction_type": _TRANSACTION_TYPES[i],
                "amount": _TRANSACTION_AMOUNTS[i],  # Decimal string
                "currency": "USD",
                "description": _TRANSACTION_DESCRIPTIONS[i],
                "status": "completed",
                "created_at": (now - timedelta(days=90 - i * 4)).isoformat(),
                "completed_at": (now - timedelta(days=89 - i * 4)).isoformat(),
                "metadata": f'{{"channel": "online", "ip": "10.0.{i}.1"}}',
            }
            for i in range(20)
        ]

    # ── 3. LedgerEntry ───────────────────────────────────────────────────────
    # Ledger pattern: every transaction produces exactly 2 entries (debit + credit)
    # that together sum to zero. This is the double-entry bookkeeping requirement.
    if _any_match(entities, ["ledgerentry", "ledger_entry", "ledger", "ledgerentries"]):
        ledger_entries = []
        entry_id = 1
        for i in range(20):
            txn_ref = f"TXN-{_YEAR}-{(i+1):08d}"
            amount = _TRANSACTION_AMOUNTS[i]
            acc_id = (i % 20) + 1

            if _TRANSACTION_TYPES[i] == "credit":
                # Credit: money coming IN to account (debit cash/asset, credit account)
                # Entry 1 — debit side (source account)
                ledger_entries.append({
                    "id": entry_id,
                    "transaction_reference": txn_ref,
                    "account_id": acc_id,
                    "entry_type": "debit",
                    "amount": amount,  # Decimal string, always non-negative
                    "currency": "USD",
                    "description": f"Debit leg: {_TRANSACTION_DESCRIPTIONS[i]}",
                    "created_at": (now - timedelta(days=90 - i * 4)).isoformat(),
                })
                entry_id += 1
                # Entry 2 — credit side (destination account)
                ledger_entries.append({
                    "id": entry_id,
                    "transaction_reference": txn_ref,
                    "account_id": acc_id,
                    "entry_type": "credit",
                    "amount": amount,  # Decimal string, always non-negative
                    "currency": "USD",
                    "description": f"Credit leg: {_TRANSACTION_DESCRIPTIONS[i]}",
                    "created_at": (now - timedelta(days=90 - i * 4)).isoformat(),
                })
                entry_id += 1
            else:
                # Debit: money going OUT of account
                ledger_entries.append({
                    "id": entry_id,
                    "transaction_reference": txn_ref,
                    "account_id": acc_id,
                    "entry_type": "credit",
                    "amount": amount,
                    "currency": "USD",
                    "description": f"Credit leg: {_TRANSACTION_DESCRIPTIONS[i]}",
                    "created_at": (now - timedelta(days=90 - i * 4)).isoformat(),
                })
                entry_id += 1
                ledger_entries.append({
                    "id": entry_id,
                    "transaction_reference": txn_ref,
                    "account_id": acc_id,
                    "entry_type": "debit",
                    "amount": amount,
                    "currency": "USD",
                    "description": f"Debit leg: {_TRANSACTION_DESCRIPTIONS[i]}",
                    "created_at": (now - timedelta(days=90 - i * 4)).isoformat(),
                })
                entry_id += 1

        result["LedgerEntry"] = ledger_entries

    # ── 4. Invoice ───────────────────────────────────────────────────────────
    _invoice_amounts = [
        "1200.00", "450.00", "3200.00", "89.99", "2750.00",
        "600.00", "1800.00", "320.00", "4500.00", "175.50",
        "980.00", "2100.00", "540.00", "1650.00", "290.00",
        "3800.00", "720.00", "1100.00", "420.00", "5000.00",
    ]
    if _any_match(entities, ["invoice", "invoices"]):
        result["Invoice"] = [
            {
                "id": i + 1,
                "invoice_number": f"INV-{_YEAR}-{(i+1):06d}",  # unique
                "account_id": (i % 20) + 1,
                "amount": _invoice_amounts[i],  # Decimal string
                "tax_amount": str(
                    (Decimal(_invoice_amounts[i]) * Decimal("0.10")).quantize(
                        Decimal("0.01")
                    )
                ),
                "total_amount": str(
                    (Decimal(_invoice_amounts[i]) * Decimal("1.10")).quantize(
                        Decimal("0.01")
                    )
                ),
                "currency": "USD",
                "status": _INVOICE_STATUSES[i],
                "issue_date": (now - timedelta(days=60 - i * 3)).date().isoformat(),
                "due_date": (now + timedelta(days=30 - i % 30)).date().isoformat(),
                "paid_at": (
                    (now - timedelta(days=30 - i % 30)).isoformat()
                    if _INVOICE_STATUSES[i] == "paid"
                    else None
                ),
                "description": f"Invoice for services rendered — period {i+1}",
                "created_at": (now - timedelta(days=60 - i * 3)).isoformat(),
                "updated_at": (now - timedelta(days=10)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 5. PaymentPlan ───────────────────────────────────────────────────────
    _plan_totals = [
        "12000.00", "5000.00", "24000.00", "8500.00", "3600.00",
        "15000.00", "7200.00", "9600.00", "4800.00", "18000.00",
        "6000.00", "10800.00", "3000.00", "14400.00", "2400.00",
        "20000.00", "4200.00", "7800.00", "1800.00", "11400.00",
    ]
    if _any_match(entities, ["paymentplan", "payment_plan", "paymentplans"]):
        result["PaymentPlan"] = [
            {
                "id": i + 1,
                "plan_reference": f"PLAN-{_YEAR}-{(i+1):06d}",  # unique
                "account_id": (i % 20) + 1,
                "total_amount": _plan_totals[i],  # Decimal string
                "installments": [3, 6, 12, 24, 6][i % 5],
                "installment_amount": str(
                    (Decimal(_plan_totals[i]) / [3, 6, 12, 24, 6][i % 5]).quantize(
                        Decimal("0.01")
                    )
                ),
                "paid_installments": i % [3, 6, 12, 24, 6][i % 5],
                "remaining_amount": str(
                    (
                        Decimal(_plan_totals[i])
                        - (Decimal(_plan_totals[i]) / [3, 6, 12, 24, 6][i % 5]).quantize(
                            Decimal("0.01")
                        ) * (i % [3, 6, 12, 24, 6][i % 5])
                    ).quantize(Decimal("0.01"))
                ),
                "status": _PAYMENT_PLAN_STATUSES[i],
                "start_date": (now - timedelta(days=180 - i * 8)).date().isoformat(),
                "next_payment_date": (now + timedelta(days=30)).date().isoformat(),
                "created_at": (now - timedelta(days=180 - i * 8)).isoformat(),
                "updated_at": (now - timedelta(days=5)).isoformat(),
            }
            for i in range(20)
        ]

    return result


def _compute_balance(account_index: int) -> str:
    """Pre-calculate account balance as credits minus debits for seed data.

    In production the balance is computed from LedgerEntry rows — this is a
    convenience snapshot only and should match the ledger total.
    """
    credits = Decimal("0.00")
    debits = Decimal("0.00")
    for i in range(20):
        if (i % 20) == account_index:
            amount = Decimal(_TRANSACTION_AMOUNTS[i])
            if _TRANSACTION_TYPES[i] == "credit":
                credits += amount
            else:
                debits += amount
    # Starting balance: inject 10,000 + index * 500 as opening entry
    opening = Decimal("10000.00") + Decimal(str(account_index * 500))
    balance = opening + credits - debits
    return str(balance.quantize(Decimal("0.01")))


def _any_match(entities: list[str], candidates: list[str]) -> bool:
    """Return True if any entity name (case-insensitive) matches a candidate."""
    lower_entities = [e.lower() for e in entities]
    return any(c in lower_entities for c in candidates)
