"""Fintech domain knowledge pack — PCI-DSS, double-entry ledger, KYC/AML."""
from __future__ import annotations

from aether_os.core.domain_knowledge.base import (
    BusinessProcessPipeline, ComplianceRule, DomainKnowledgePack,
    EntityTemplate, FieldDef, ProcessStep, WorkflowTemplate,
)

PACK = DomainKnowledgePack(
    domain="fintech",
    display_name="FinTech / Financial Services",

    entities=[
        EntityTemplate(
            name="Account", table="accounts",
            description="User financial account (wallet, bank account, sub-account)",
            fields=[
                FieldDef("user_id", "fk", pii=True),
                FieldDef("account_type", "string"),       # checking | savings | wallet
                FieldDef("currency", "string"),            # ISO 4217
                FieldDef("balance_cents", "int"),          # always store in minor units
                FieldDef("status", "string"),              # active | frozen | closed
                FieldDef("iban", "string", pii=True, encrypted_at_rest=True),
            ],
            indexes=["user_id", "status"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="Transaction", table="transactions",
            description="Immutable ledger event — never updated, only inserted",
            fields=[
                FieldDef("idempotency_key", "string"),     # caller-supplied, unique
                FieldDef("from_account_id", "fk"),
                FieldDef("to_account_id", "fk"),
                FieldDef("amount_cents", "int"),
                FieldDef("currency", "string"),
                FieldDef("type", "string"),                # credit | debit | transfer | refund
                FieldDef("status", "string"),
                FieldDef("reference", "string"),
                FieldDef("metadata", "text"),
            ],
            indexes=["idempotency_key", "from_account_id", "to_account_id", "status"],
            audit_trail=True, soft_delete=False,
        ),
        EntityTemplate(
            name="LedgerEntry", table="ledger_entries",
            description="Double-entry bookkeeping line — every transaction produces two entries",
            fields=[
                FieldDef("transaction_id", "fk"),
                FieldDef("account_id", "fk"),
                FieldDef("debit_cents", "int"),
                FieldDef("credit_cents", "int"),
                FieldDef("running_balance_cents", "int"),
                FieldDef("posted_at", "datetime"),
            ],
            indexes=["transaction_id", "account_id", "posted_at"],
            audit_trail=True,
        ),
        EntityTemplate(
            name="KYCRecord", table="kyc_records",
            description="Know-Your-Customer identity verification record",
            fields=[
                FieldDef("user_id", "fk", pii=True),
                FieldDef("full_name", "string", pii=True, encrypted_at_rest=True),
                FieldDef("date_of_birth", "datetime", pii=True, encrypted_at_rest=True),
                FieldDef("national_id", "string", pii=True, encrypted_at_rest=True),
                FieldDef("document_type", "string"),
                FieldDef("status", "string"),              # pending | approved | rejected | expired
                FieldDef("risk_level", "string"),          # low | medium | high
                FieldDef("reviewed_by", "string"),
                FieldDef("reviewed_at", "datetime"),
            ],
            indexes=["user_id", "status"],
            audit_trail=True, soft_delete=True,
        ),
        EntityTemplate(
            name="PaymentMethod", table="payment_methods",
            description="Stored payment instrument (tokenised — never raw card data)",
            fields=[
                FieldDef("user_id", "fk", pii=True),
                FieldDef("provider", "string"),            # stripe | paypal | bank_transfer
                FieldDef("provider_token", "string", pci=True, encrypted_at_rest=True),
                FieldDef("last_four", "string", pci=True),
                FieldDef("card_brand", "string"),
                FieldDef("expiry_month", "int", pci=True),
                FieldDef("expiry_year", "int", pci=True),
                FieldDef("is_default", "bool"),
            ],
            indexes=["user_id"],
            audit_trail=True,
        ),
    ],

    workflows=[
        WorkflowTemplate(
            name="PaymentFlow",
            entity="Transaction", field="status",
            states=["initiated", "processing", "settled", "failed", "refund_requested", "refunded"],
            transitions={
                "initiated":         ["processing", "failed"],
                "processing":        ["settled", "failed"],
                "settled":           ["refund_requested"],
                "failed":            [],
                "refund_requested":  ["refunded", "failed"],
                "refunded":          [],
            },
            terminal_states=["settled", "failed", "refunded"],
            description="Payment state machine — transitions must be idempotent",
        ),
        WorkflowTemplate(
            name="KYCFlow",
            entity="KYCRecord", field="status",
            states=["submitted", "under_review", "approved", "rejected", "expired"],
            transitions={
                "submitted":    ["under_review"],
                "under_review": ["approved", "rejected"],
                "approved":     ["expired"],
                "rejected":     ["submitted"],
                "expired":      ["submitted"],
            },
            terminal_states=["approved", "rejected"],
            description="KYC verification lifecycle",
        ),
    ],

    compliance=[
        ComplianceRule("PCI-DSS", "Never store raw card numbers, CVV, or full track data",
                       ["card_number", "cvv", "track_data"], "mandatory",
                       "Store only Stripe/PayPal tokenised references"),
        ComplianceRule("PCI-DSS", "Encrypt card-adjacent PII at rest",
                       ["provider_token", "last_four", "expiry_month", "expiry_year"], "mandatory",
                       "Use AES-256 or KMS-managed keys"),
        ComplianceRule("PCI-DSS", "All transaction data access must be logged", [], "mandatory",
                       "Audit trail with user_id, timestamp, action on every mutation"),
        ComplianceRule("AML", "Transactions above threshold must trigger AML check",
                       ["amount_cents"], "mandatory",
                       "Flag transactions > 10,000 USD equivalent for review"),
        ComplianceRule("GDPR", "PII fields (name, DOB, national_id) must be encryptable and deletable",
                       ["full_name", "date_of_birth", "national_id", "iban"], "mandatory",
                       "Support right-to-erasure via pseudonymisation or key deletion"),
    ],

    api_patterns=[
        "POST /payments — create payment with idempotency_key",
        "GET /accounts/{id}/transactions?page=&limit= — paginated ledger",
        "POST /kyc/submit — initiate KYC with document upload",
        "GET /kyc/status — poll KYC status for authenticated user",
        "POST /webhooks/stripe — receive Stripe payment events",
        "GET /accounts/{id}/balance — real-time balance (READ from ledger sum)",
    ],

    pipelines=[
        BusinessProcessPipeline(
            name="PaymentProcessingFlow",
            trigger="create",
            trigger_entity="Transaction",
            trigger_condition="status == initiated",
            description="Full payment processing: KYC check, fraud screen, AML check, execute, ledger post, notify.",
            integrations_required=["FraudService", "AMLService", "LedgerService", "NotificationService"],
            steps=[
                ProcessStep(
                    name="verify_kyc",
                    service_required="KYCService",
                    method="verify_kyc_status",
                    description="Confirm the sending user has an approved KYC record before allowing the transaction.",
                    input_keys=["user_id"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="screen_fraud",
                    service_required="FraudService",
                    method="screen_transaction",
                    description="Run the transaction through fraud detection rules (velocity, geo, amount anomaly).",
                    input_keys=["from_account_id", "to_account_id", "amount_cents", "currency"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="check_aml",
                    service_required="AMLService",
                    method="check_threshold",
                    description="Flag and hold transactions above AML reporting threshold (10,000 USD equivalent).",
                    input_keys=["amount_cents", "currency", "user_id"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="execute_transfer",
                    service_required="LedgerService",
                    method="post_double_entry",
                    description="Debit source account and credit destination account using SERIALIZABLE isolation.",
                    input_keys=["from_account_id", "to_account_id", "amount_cents", "currency"],
                    on_failure="FAIL",
                ),
                ProcessStep(
                    name="notify_parties",
                    service_required="NotificationService",
                    method="send_payment_confirmation",
                    description="Send payment confirmation to sender and recipient.",
                    input_keys=["execute_transfer", "user_id"],
                    on_failure="SKIP",
                ),
            ],
        ),
    ],

    prompt_injection="""FINTECH DOMAIN RULES (mandatory — do not omit):
1. Store all monetary values as INTEGER cents/minor units — never use float for money.
2. Every financial transaction MUST use an idempotency_key to prevent double-charges.
3. Use double-entry bookkeeping: every transaction creates BOTH a debit and credit LedgerEntry.
4. Transaction records are IMMUTABLE — never UPDATE or DELETE a transaction row. Issue a reversal instead.
5. Database transactions for money movement MUST use SERIALIZABLE isolation level.
6. Never store raw card numbers, CVV, or magnetic stripe data. Use payment provider tokens only.
7. PII fields (name, DOB, national_id) must be encrypted at rest (AES-256 or KMS).
8. All account and transaction mutations must write to an audit_log table.
9. KYC verification must be completed before allowing transactions above the threshold.
10. API responses must never return full card numbers — return last_four only.
""",
)
